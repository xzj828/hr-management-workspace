from tempfile import TemporaryDirectory

from django.contrib.auth.models import User
from django.test import override_settings
from rest_framework.test import APITestCase

from attendance.models import AccountProfile
from recruitment.demo_data import load_demo_data
from recruitment.models import JobApplication, Resume


class RecruitmentPagesApiTests(APITestCase):
    def setUp(self):
        self.temp_media = TemporaryDirectory()
        self.override = override_settings(MEDIA_ROOT=self.temp_media.name)
        self.override.enable()
        self.hr = User.objects.create_user(username="workspace-hr")
        AccountProfile.objects.create(user=self.hr, role=AccountProfile.Role.HR)
        self.viewer = User.objects.create_user(username="workspace-viewer")
        AccountProfile.objects.create(user=self.viewer, role=AccountProfile.Role.VIEWER)
        load_demo_data(self.hr)
        self.client.force_login(self.hr)

    def tearDown(self):
        self.override.disable()
        self.temp_media.cleanup()

    def test_jobs_include_candidate_counts(self):
        response = self.client.get("/api/recruitment/jobs/?is_demo=true")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 3)
        self.assertTrue(all("candidate_count" in item for item in response.data["results"]))
        self.assertEqual(sum(item["candidate_count"] for item in response.data["results"]), 10)

    def test_candidates_support_search_and_stage_filters(self):
        response = self.client.get("/api/recruitment/candidates/?search=林&stage=to_screen")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 1)
        candidate = response.data["results"][0]
        self.assertEqual(candidate["name"], "林雨薇")
        self.assertEqual(candidate["applications"][0]["stage"], "to_screen")
        self.assertIn("resume_count", candidate)

    def test_hr_can_update_only_the_application_stage(self):
        application = JobApplication.objects.filter(is_demo=True).first()

        response = self.client.patch(
            f"/api/recruitment/applications/{application.pk}/",
            {"stage": JobApplication.Stage.INTERVIEWING, "source": "changed"},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        application.refresh_from_db()
        self.assertEqual(application.stage, JobApplication.Stage.INTERVIEWING)
        self.assertEqual(application.source, "demo")

    def test_invalid_application_stage_is_rejected(self):
        application = JobApplication.objects.filter(is_demo=True).first()

        response = self.client.patch(
            f"/api/recruitment/applications/{application.pk}/",
            {"stage": "not-a-stage"},
            format="json",
        )

        self.assertEqual(response.status_code, 400)

    def test_resume_file_supports_inline_download_and_missing_state(self):
        resume = Resume.objects.filter(is_demo=True).first()

        inline = self.client.get(f"/api/recruitment/resumes/{resume.pk}/file/")
        self.assertEqual(inline.status_code, 200)
        self.assertEqual(inline["Content-Type"], "application/pdf")
        self.assertTrue(inline["Content-Disposition"].startswith("inline"))
        inline.close()

        download = self.client.get(f"/api/recruitment/resumes/{resume.pk}/file/?download=1")
        self.assertTrue(download["Content-Disposition"].startswith("attachment"))
        download.close()

        resume.file.storage.delete(resume.file.name)
        detail = self.client.get(f"/api/recruitment/resumes/{resume.pk}/")
        self.assertFalse(detail.data["file_available"])
        missing = self.client.get(f"/api/recruitment/resumes/{resume.pk}/file/")
        self.assertEqual(missing.status_code, 404)

    def test_demo_data_endpoint_reports_loads_and_clears(self):
        status_response = self.client.get("/api/recruitment/demo-data/")
        self.assertEqual(status_response.status_code, 200)
        self.assertEqual(status_response.data["counts"]["candidates"], 10)

        with self.captureOnCommitCallbacks(execute=True):
            cleared = self.client.delete("/api/recruitment/demo-data/")
        self.assertEqual(cleared.status_code, 200)
        self.assertFalse(cleared.data["loaded"])

        loaded = self.client.post("/api/recruitment/demo-data/", {}, format="json")
        self.assertEqual(loaded.status_code, 201)
        self.assertEqual(loaded.data["counts"]["resumes"], 3)

    def test_viewer_cannot_mutate_demo_data_or_pipeline(self):
        application = JobApplication.objects.filter(is_demo=True).first()
        self.client.force_login(self.viewer)

        self.assertEqual(self.client.get("/api/recruitment/demo-data/").status_code, 200)
        self.assertEqual(self.client.post("/api/recruitment/demo-data/", {}, format="json").status_code, 403)
        self.assertEqual(self.client.delete("/api/recruitment/demo-data/").status_code, 403)
        self.assertEqual(
            self.client.patch(
                f"/api/recruitment/applications/{application.pk}/",
                {"stage": JobApplication.Stage.HIRED},
                format="json",
            ).status_code,
            403,
        )

    def test_anonymous_user_cannot_read_resume_file(self):
        resume = Resume.objects.filter(is_demo=True).first()
        self.client.logout()

        response = self.client.get(f"/api/recruitment/resumes/{resume.pk}/file/")

        self.assertEqual(response.status_code, 403)
