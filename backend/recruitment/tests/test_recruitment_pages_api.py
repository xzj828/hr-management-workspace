from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import override_settings
from rest_framework.test import APITestCase

from attendance.models import AccountProfile
from recruitment.demo_data import load_demo_data
from recruitment.models import (
    AiProcessingTask,
    BossAccount,
    Candidate,
    JobApplication,
    RecruitmentAuditLog,
    RecruitmentJob,
    Resume,
)


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
            {"stage": JobApplication.Stage.INTERVIEWING, "stage_reason": "HR 完成人工复核", "source": "changed"},
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
        frame_options = inline["X-Frame-Options"]
        inline.close()
        self.assertEqual(frame_options, "SAMEORIGIN")

        download = self.client.get(f"/api/recruitment/resumes/{resume.pk}/file/?download=1")
        self.assertTrue(download["Content-Disposition"].startswith("attachment"))
        download.close()

        resume.file.storage.delete(resume.file.name)
        detail = self.client.get(f"/api/recruitment/resumes/{resume.pk}/")
        self.assertFalse(detail.data["file_available"])
        missing = self.client.get(f"/api/recruitment/resumes/{resume.pk}/file/")
        self.assertEqual(missing.status_code, 404)

    def test_hr_can_purge_resume_file_and_repeat_safely(self):
        resume = Resume.objects.filter(is_demo=True).first()
        stored_name = resume.file.name
        released_bytes = resume.file_size
        queued_task = AiProcessingTask.objects.create(
            kind=AiProcessingTask.Kind.RESUME_STRUCTURE,
            status=AiProcessingTask.Status.PENDING,
            requested_by=self.hr,
            resume=resume,
            idempotency_key=f"purge-pending:{resume.pk}",
        )
        self.assertTrue(resume.file.storage.exists(stored_name))

        response = self.client.post(f"/api/recruitment/resumes/{resume.pk}/purge/", {}, format="json")

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["released_bytes"], released_bytes)
        resume.refresh_from_db()
        queued_task.refresh_from_db()
        self.assertEqual(resume.file.name, "")
        self.assertEqual(resume.file_size, 0)
        self.assertIsNotNone(resume.archived_at)
        self.assertFalse(resume.file.storage.exists(stored_name))
        self.assertEqual(queued_task.status, AiProcessingTask.Status.FAILED)
        self.assertEqual(queued_task.error_code, "source_file_deleted")
        self.assertTrue(
            RecruitmentAuditLog.objects.filter(action="resume_file_purged", target_id=str(resume.pk)).exists()
        )
        preview = self.client.get(f"/api/recruitment/resumes/{resume.pk}/file/")
        self.assertEqual(preview.status_code, 404)
        screening = self.client.get(f"/api/recruitment/screening-results/?job={resume.application.job_id}")
        result = next(item for item in screening.data["results"] if item["application"]["id"] == resume.application_id)
        self.assertIsNone(result["resume"])

        repeated = self.client.post(f"/api/recruitment/resumes/{resume.pk}/purge/", {}, format="json")
        self.assertEqual(repeated.status_code, 200, repeated.data)
        self.assertEqual(repeated.data["released_bytes"], 0)

    def test_resume_purge_rejects_in_flight_ai_task_without_deleting_file(self):
        resume = Resume.objects.filter(is_demo=True).first()
        stored_name = resume.file.name
        AiProcessingTask.objects.create(
            kind=AiProcessingTask.Kind.RESUME_STRUCTURE,
            status=AiProcessingTask.Status.MODEL,
            requested_by=self.hr,
            resume=resume,
            idempotency_key=f"purge-active:{resume.pk}",
        )

        response = self.client.post(f"/api/recruitment/resumes/{resume.pk}/purge/", {}, format="json")

        self.assertEqual(response.status_code, 409, response.data)
        resume.refresh_from_db()
        self.assertIsNone(resume.archived_at)
        self.assertEqual(resume.file.name, stored_name)
        self.assertTrue(resume.file.storage.exists(stored_name))

    def test_other_hr_cannot_purge_resume(self):
        resume = Resume.objects.filter(is_demo=True).first()
        other = User.objects.create_user(username="resume-purge-other")
        AccountProfile.objects.create(user=other, role=AccountProfile.Role.HR)
        self.client.force_login(other)

        response = self.client.post(f"/api/recruitment/resumes/{resume.pk}/purge/", {}, format="json")

        self.assertEqual(response.status_code, 404)
        resume.refresh_from_db()
        self.assertIsNone(resume.archived_at)

    def test_resume_purge_storage_failure_preserves_database_state(self):
        resume = Resume.objects.filter(is_demo=True).first()
        stored_name = resume.file.name
        with patch.object(resume.file.storage, "delete", side_effect=OSError("locked")):
            response = self.client.post(f"/api/recruitment/resumes/{resume.pk}/purge/", {}, format="json")

        self.assertEqual(response.status_code, 503, response.data)
        resume.refresh_from_db()
        self.assertIsNone(resume.archived_at)
        self.assertEqual(resume.file.name, stored_name)
        self.assertTrue(resume.file.storage.exists(stored_name))

    def test_hr_can_bulk_purge_resumes_and_keep_processing_files(self):
        resumes = list(Resume.objects.filter(is_demo=True).order_by("id")[:2])
        blocked = resumes[1]
        blocked_name = blocked.file.name
        AiProcessingTask.objects.create(
            kind=AiProcessingTask.Kind.RESUME_STRUCTURE,
            status=AiProcessingTask.Status.MODEL,
            requested_by=self.hr,
            resume=blocked,
            idempotency_key=f"bulk-purge-active:{blocked.pk}",
        )

        response = self.client.post(
            "/api/recruitment/resumes/bulk-purge/",
            {"resume_ids": [resume.pk for resume in resumes]},
            format="json",
        )

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["purged_count"], 1)
        self.assertEqual(response.data["failed_count"], 1)
        self.assertEqual(response.data["failures"][0]["code"], "resume_processing")
        resumes[0].refresh_from_db()
        blocked.refresh_from_db()
        self.assertIsNotNone(resumes[0].archived_at)
        self.assertIsNone(blocked.archived_at)
        self.assertEqual(blocked.file.name, blocked_name)
        self.assertTrue(blocked.file.storage.exists(blocked_name))

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
        self.assertEqual(
            self.client.post(
                "/api/recruitment/applications/bulk-archive/",
                {"application_ids": [application.pk]},
                format="json",
            ).status_code,
            403,
        )
        application.refresh_from_db()
        self.assertIsNone(application.archived_at)

    def test_anonymous_user_cannot_read_resume_file(self):
        resume = Resume.objects.filter(is_demo=True).first()
        self.client.logout()

        response = self.client.get(f"/api/recruitment/resumes/{resume.pk}/file/")

        self.assertEqual(response.status_code, 403)

    def test_job_scoped_endpoints_do_not_leak_other_jobs_or_accounts(self):
        other = User.objects.create_user(username="workspace-other-hr")
        AccountProfile.objects.create(user=other, role=AccountProfile.Role.HR)
        visible_account = BossAccount.objects.create(
            name="可见招聘账号",
            browser_profile="visible-recruitment-account",
            cdp_port=53601,
        )
        visible_account.authorized_users.add(self.hr)
        hidden_account = BossAccount.objects.create(
            name="隐藏招聘账号",
            browser_profile="hidden-recruitment-account",
            cdp_port=53602,
        )
        hidden_account.authorized_users.add(other)
        visible_job = RecruitmentJob.objects.create(
            boss_account=visible_account,
            owner=self.hr,
            external_id="visible-open-job",
            title="可见在招职位",
            status=RecruitmentJob.Status.OPEN,
        )
        closed_job = RecruitmentJob.objects.create(
            boss_account=visible_account,
            owner=self.hr,
            external_id="visible-closed-job",
            title="可见关闭职位",
            status=RecruitmentJob.Status.CLOSED,
        )
        hidden_job = RecruitmentJob.objects.create(
            boss_account=hidden_account,
            owner=other,
            external_id="hidden-open-job",
            title="隐藏在招职位",
            status=RecruitmentJob.Status.OPEN,
        )
        shared_candidate = Candidate.objects.create(identity_key="shared-candidate", name="跨岗位候选人")
        visible_application = JobApplication.objects.create(
            candidate=shared_candidate,
            job=visible_job,
            owner=self.hr,
            source="boss",
        )
        hidden_application = JobApplication.objects.create(
            candidate=shared_candidate,
            job=hidden_job,
            owner=other,
            source="boss",
        )
        closed_candidate = Candidate.objects.create(identity_key="closed-candidate", name="关闭职位候选人")
        closed_application = JobApplication.objects.create(
            candidate=closed_candidate,
            job=closed_job,
            owner=self.hr,
            source="boss",
        )
        visible_resume = Resume.objects.create(
            candidate=shared_candidate,
            application=visible_application,
            original_name="visible.pdf",
            file="recruitment/resumes/visible.pdf",
        )
        Resume.objects.create(
            candidate=closed_candidate,
            application=closed_application,
            original_name="closed.pdf",
            file="recruitment/resumes/closed.pdf",
        )

        jobs = self.client.get("/api/recruitment/jobs/?status=open")
        self.assertIn(visible_job.id, {item["id"] for item in jobs.data["results"]})
        self.assertNotIn(closed_job.id, {item["id"] for item in jobs.data["results"]})
        self.assertNotIn(hidden_job.id, {item["id"] for item in jobs.data["results"]})

        applications = self.client.get(f"/api/recruitment/applications/?job={visible_job.id}")
        self.assertEqual(applications.data["count"], 1)
        self.assertEqual(applications.data["results"][0]["id"], visible_application.id)
        self.assertIn("phone", applications.data["results"][0]["candidate"])
        self.assertIn("resume_count", applications.data["results"][0])
        self.assertEqual(applications.data["results"][0]["other_applications"], [])
        self.assertEqual(
            self.client.get(f"/api/recruitment/applications/{hidden_application.id}/").status_code,
            404,
        )
        self.assertEqual(
            self.client.get(f"/api/recruitment/applications/?job={hidden_job.id}").status_code,
            404,
        )
        self.assertEqual(
            self.client.get(f"/api/recruitment/applications/?job={closed_job.id}").status_code,
            404,
        )

        candidates = self.client.get(f"/api/recruitment/candidates/?job={visible_job.id}")
        self.assertEqual(candidates.data["count"], 1)
        self.assertEqual(
            [item["job"] for item in candidates.data["results"][0]["applications"]],
            [visible_job.id],
        )

        resumes = self.client.get(f"/api/recruitment/resumes/?job={visible_job.id}")
        self.assertEqual(resumes.data["count"], 1)
        self.assertEqual(resumes.data["results"][0]["id"], visible_resume.id)

    def test_applications_support_candidate_search_inside_selected_job(self):
        target = JobApplication.objects.select_related("candidate", "job").get(candidate__name="林雨薇")

        response = self.client.get(
            f"/api/recruitment/applications/?job={target.job_id}&search=林&stage={target.stage}"
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(response.data["results"][0]["candidate"]["name"], "林雨薇")

    def test_archiving_application_keeps_candidate_and_other_application(self):
        target = JobApplication.objects.filter(is_demo=True).select_related("candidate", "job").first()
        other_job = RecruitmentJob.objects.filter(is_demo=True).exclude(pk=target.job_id).first()
        other = JobApplication.objects.create(
            candidate=target.candidate,
            job=other_job,
            owner=self.hr,
            source="demo",
            is_demo=True,
        )
        candidate_id = target.candidate_id

        archived = self.client.post(f"/api/recruitment/applications/{target.id}/archive/")

        self.assertEqual(archived.status_code, 200)
        target.refresh_from_db()
        self.assertIsNotNone(target.archived_at)
        self.assertTrue(Candidate.objects.filter(pk=candidate_id).exists())
        self.assertTrue(JobApplication.objects.filter(pk=other.id, archived_at__isnull=True).exists())
        self.assertFalse(
            any(item["id"] == target.id for item in self.client.get("/api/recruitment/applications/").data["results"])
        )

        restored = self.client.post(f"/api/recruitment/applications/{target.id}/restore/?archived=1")

        self.assertEqual(restored.status_code, 200)
        target.refresh_from_db()
        self.assertIsNone(target.archived_at)

    def test_hr_can_bulk_archive_candidate_records_without_archiving_candidate_master(self):
        target = JobApplication.objects.filter(is_demo=True).select_related("candidate", "job").first()
        second_candidate = Candidate.objects.create(
            identity_key="bulk-archive-second-candidate",
            name="批量清除候选人",
        )
        same_job = JobApplication.objects.create(
            candidate=second_candidate,
            job=target.job,
            owner=self.hr,
            source="boss",
        )
        other_job = RecruitmentJob.objects.filter(is_demo=True).exclude(pk=target.job_id).first()
        other_application = JobApplication.objects.create(
            candidate=target.candidate,
            job=other_job,
            owner=self.hr,
            source="demo",
            is_demo=True,
        )

        response = self.client.post(
            "/api/recruitment/applications/bulk-archive/",
            {"application_ids": [target.pk, same_job.pk, 999999]},
            format="json",
        )

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["archived_count"], 2)
        self.assertEqual(response.data["skipped_count"], 1)
        target.refresh_from_db()
        same_job.refresh_from_db()
        self.assertIsNotNone(target.archived_at)
        self.assertIsNotNone(same_job.archived_at)
        self.assertIsNone(target.candidate.archived_at)
        self.assertTrue(Resume.objects.filter(application=target).exists())
        self.assertTrue(JobApplication.objects.filter(pk=other_application.pk, archived_at__isnull=True).exists())
        ranking = self.client.get(f"/api/recruitment/screening-results/?job={target.job_id}")
        ranked_ids = {row["application"]["id"] for row in ranking.data["results"]}
        self.assertNotIn(target.pk, ranked_ids)
        self.assertNotIn(same_job.pk, ranked_ids)
