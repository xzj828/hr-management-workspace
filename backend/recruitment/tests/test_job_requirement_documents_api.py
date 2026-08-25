from tempfile import TemporaryDirectory

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from rest_framework.test import APITestCase

from attendance.models import AccountProfile
from recruitment.models import BossAccount, JobRequirementDocument, RecruitmentJob


class JobRequirementDocumentApiTests(APITestCase):
    def setUp(self):
        self.media = TemporaryDirectory()
        self.settings = override_settings(MEDIA_ROOT=self.media.name)
        self.settings.enable()
        self.user = User.objects.create_user(username="document-hr")
        AccountProfile.objects.create(user=self.user, role=AccountProfile.Role.HR)
        self.account = BossAccount.objects.create(
            name="Document account",
            browser_profile="document-account",
            cdp_port=53992,
        )
        self.account.authorized_users.add(self.user)
        self.job = RecruitmentJob.objects.create(
            boss_account=self.account,
            external_id="document-job",
            title="前端工程师",
            owner=self.user,
        )
        self.client.force_login(self.user)

    def tearDown(self):
        self.settings.disable()
        self.media.cleanup()

    def _file(self, name="岗位画像.docx", content=b"PK\x03\x04word-document"):
        return SimpleUploadedFile(
            name,
            content,
            content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )

    def test_creates_document_with_current_version_and_hash(self):
        response = self.client.post(
            "/api/recruitment/job-documents/",
            {
                "job": self.job.pk,
                "category": JobRequirementDocument.Category.PERSONA,
                "title": "前端候选人画像",
                "file": self._file(),
            },
            format="multipart",
        )

        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data["current_version"]["version"], 1)
        self.assertEqual(len(response.data["current_version"]["sha256"]), 64)
        self.assertEqual(response.data["job"], self.job.pk)

    def test_adds_version_switches_current_and_downloads_it(self):
        created = self.client.post(
            "/api/recruitment/job-documents/",
            {
                "job": self.job.pk,
                "category": JobRequirementDocument.Category.REQUIREMENT,
                "title": "岗位需求",
                "file": self._file("需求-v1.doc"),
            },
            format="multipart",
        )
        document_id = created.data["id"]

        added = self.client.post(
            f"/api/recruitment/job-documents/{document_id}/versions/",
            {"file": self._file("需求-v2.docx", b"PK\x03\x04new-version")},
            format="multipart",
        )

        self.assertEqual(added.status_code, 201, added.data)
        self.assertEqual(added.data["current_version"]["version"], 2)
        self.assertEqual([item["version"] for item in added.data["versions"]], [2, 1])
        downloaded = self.client.get(
            f"/api/recruitment/job-document-versions/{added.data['current_version']['id']}/file/"
        )
        self.assertEqual(downloaded.status_code, 200)
        self.assertTrue(downloaded["Content-Disposition"].startswith("attachment"))
        downloaded.close()

    def test_rejects_non_word_files_and_hidden_jobs(self):
        invalid = self.client.post(
            "/api/recruitment/job-documents/",
            {
                "job": self.job.pk,
                "category": JobRequirementDocument.Category.OTHER,
                "title": "非法附件",
                "file": SimpleUploadedFile("notes.txt", b"plain text", content_type="text/plain"),
            },
            format="multipart",
        )
        self.assertEqual(invalid.status_code, 400)

        other = User.objects.create_user(username="other-document-hr")
        AccountProfile.objects.create(user=other, role=AccountProfile.Role.HR)
        self.client.force_login(other)
        hidden = self.client.get(f"/api/recruitment/job-documents/?job={self.job.pk}")
        self.assertEqual(hidden.status_code, 404)

    def test_archives_saved_document_without_deleting_versions(self):
        created = self.client.post(
            "/api/recruitment/job-documents/",
            {"job": self.job.pk, "category": "persona", "title": "候选人画像", "file": self._file()},
            format="multipart",
        )
        response = self.client.post(f"/api/recruitment/job-documents/{created.data['id']}/archive/")

        self.assertEqual(response.status_code, 200, response.data)
        document = JobRequirementDocument.objects.get(pk=created.data["id"])
        self.assertIsNotNone(document.archived_at)
        self.assertEqual(document.versions.count(), 1)
        self.assertEqual(self.client.get(f"/api/recruitment/job-documents/?job={self.job.pk}").data["count"], 0)
