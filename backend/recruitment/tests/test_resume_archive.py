from django.contrib.auth.models import User
from django.core.files.storage import default_storage
from django.test import TestCase, override_settings

from recruitment.models import Candidate, JobApplication, RecruitmentJob, Resume
from recruitment.services.resumes import archive_pdf


@override_settings(MEDIA_ROOT="test-media-resume-archive")
class ResumeArchiveTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("hr-resume")
        self.job = RecruitmentJob.objects.create(external_id="job-resume", title="设计师", owner=self.user)
        self.candidate = Candidate.objects.create(identity_key="resume-candidate", name="陈月")
        self.application = JobApplication.objects.create(candidate=self.candidate, job=self.job, source="boss")

    def tearDown(self):
        for resume in Resume.objects.all():
            if resume.file:
                default_storage.delete(resume.file.name)

    def test_pdf_is_hashed_versioned_and_deduplicated(self):
        content = b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\n%%EOF"
        first, created = archive_pdf(
            application=self.application, filename="陈月简历.pdf", content=content, source="boss"
        )
        duplicate, duplicate_created = archive_pdf(
            application=self.application, filename="再次下载.pdf", content=content, source="boss"
        )
        second, second_created = archive_pdf(
            application=self.application,
            filename="陈月简历-v2.pdf",
            content=b"%PDF-1.4\n2 0 obj\n<<>>\nendobj\n%%EOF",
            source="boss",
        )
        self.assertTrue(created)
        self.assertFalse(duplicate_created)
        self.assertEqual(duplicate.pk, first.pk)
        self.assertTrue(second_created)
        self.assertEqual((first.version, second.version), (1, 2))
        self.application.refresh_from_db()
        self.assertEqual(self.application.stage, JobApplication.Stage.RESUME_RECEIVED)

    def test_non_pdf_content_is_rejected(self):
        with self.assertRaises(ValueError):
            archive_pdf(
                application=self.application, filename="伪装.pdf", content=b"not a pdf", source="boss"
            )

