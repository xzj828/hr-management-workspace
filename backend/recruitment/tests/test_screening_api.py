import uuid

from django.contrib.auth.models import User
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from rest_framework.exceptions import ValidationError
from rest_framework.test import APITestCase

from attendance.models import AccountProfile
from recruitment.models import (
    AiProcessingTask,
    ApplicationScreeningDecision,
    BossAccount,
    Candidate,
    FileTextExtraction,
    JobApplication,
    JobStandardVersion,
    RecruitmentJob,
    Resume,
    ResumeAssessment,
    ScreeningDecisionBatch,
    StructuredResumeVersion,
)
from recruitment.services.screening import create_screening_decisions


class ScreeningApiTests(APITestCase):
    def setUp(self):
        self.hr = User.objects.create_user("screening-hr")
        AccountProfile.objects.create(user=self.hr, role=AccountProfile.Role.HR)
        self.account = BossAccount.objects.create(
            name="Screening account",
            browser_profile="screening-account",
            cdp_port=54321,
        )
        self.account.authorized_users.add(self.hr)
        self.job = RecruitmentJob.objects.create(
            boss_account=self.account,
            external_id="screening-job",
            title="高级产品经理",
            owner=self.hr,
        )
        self.standard = JobStandardVersion.objects.create(
            job=self.job,
            version=1,
            status=JobStandardVersion.Status.PUBLISHED,
            criteria={"summary": "当前标准", "dimensions": []},
            created_by=self.hr,
            published_by=self.hr,
        )
        self.client.force_login(self.hr)

    def _application(self, index, *, stage=JobApplication.Stage.NEW):
        candidate = Candidate.objects.create(
            identity_key=f"screening-candidate-{index}",
            external_id=f"boss-{index}",
            name=f"候选人{index}",
            current_title="产品经理",
            current_city="上海",
        )
        return JobApplication.objects.create(
            candidate=candidate,
            job=self.job,
            source="boss",
            owner=self.hr,
            stage=stage,
        )

    def _resume(self, application, version):
        resume = Resume.objects.create(
            candidate=application.candidate,
            application=application,
            original_name=f"resume-{application.pk}-{version}.pdf",
            file=f"recruitment/resumes/resume-{application.pk}-{version}.pdf",
            content_type="application/pdf",
            file_size=100,
            sha256=f"{application.pk:032x}{version:032x}"[-64:],
            version=version,
        )
        extraction = FileTextExtraction.objects.create(
            source_kind=FileTextExtraction.SourceKind.RESUME,
            source_id=resume.pk,
            source_sha256=resume.sha256,
            method=FileTextExtraction.Method.PDF_TEXT,
            plain_text="候选人简历",
            blocks=[{"id": f"resume-{resume.pk}-block-1", "text": "候选人简历"}],
            status=FileTextExtraction.Status.READY,
        )
        structure = StructuredResumeVersion.objects.create(
            resume=resume,
            version=1,
            extraction=extraction,
            data={"summary": "候选人简历"},
            evidence=[],
            model_name="test-model",
        )
        return resume, structure

    def _assessment(self, structure, standard, score, *, version=1):
        return ResumeAssessment.objects.create(
            structured_resume=structure,
            standard=standard,
            version=version,
            total_score=score,
            dimension_scores=[],
            hard_failures=[],
            evidence=[],
            gaps=[],
            verification_questions=[],
            confidence="0.800",
            recommendation=ResumeAssessment.Recommendation.ADVANCE,
            model_name="test-model",
        )

    def test_results_rank_only_current_resume_and_current_published_standard(self):
        first = self._application(1, stage=JobApplication.Stage.REJECTED)
        second = self._application(2)
        unscored = self._application(3)
        archived = self._application(4)
        archived.archived_at = archived.updated_at
        archived.save(update_fields=["archived_at"])

        old_standard = JobStandardVersion.objects.create(
            job=self.job,
            version=5,
            status=JobStandardVersion.Status.SUPERSEDED,
            criteria={"summary": "历史标准", "dimensions": []},
            created_by=self.hr,
        )
        old_resume, old_structure = self._resume(first, 1)
        current_resume, current_structure = self._resume(first, 2)
        _, second_structure = self._resume(second, 1)
        self._assessment(old_structure, old_standard, "99.00")
        self._assessment(current_structure, self.standard, "80.00")
        self._assessment(second_structure, self.standard, "90.00")

        response = self.client.get(f"/api/recruitment/screening-results/?job={self.job.pk}")

        self.assertEqual(response.status_code, 200, response.data)
        rows = response.data["results"]
        self.assertEqual([row["application"]["id"] for row in rows], [second.pk, first.pk, unscored.pk])
        self.assertEqual([row["rank"] for row in rows], [1, 2, None])
        first_row = next(row for row in rows if row["application"]["id"] == first.pk)
        self.assertEqual(first_row["resume"]["id"], current_resume.pk)
        self.assertEqual(first_row["assessment"]["total_score"], "80.00")
        self.assertEqual(first_row["application"]["stage"], JobApplication.Stage.REJECTED)
        self.assertIsNone(first_row["hr_decision"])
        self.assertEqual(first_row["notification"]["status"], "not_requested")
        self.assertNotIn("external_id", first_row["resume"])
        self.assertNotIn("sha256", first_row["resume"])
        self.assertNotIn("data", first_row["structure"])
        self.assertNotIn("evidence", first_row["structure"])
        for heavy_field in (
            "dimension_scores", "evidence", "gaps", "verification_questions", "hard_failures",
        ):
            self.assertNotIn(heavy_field, first_row["assessment"])

    def test_results_query_count_does_not_grow_with_candidate_count(self):
        for index in range(100, 112):
            application = self._application(index)
            _, structure = self._resume(application, 1)
            self._assessment(structure, self.standard, f"{index % 100}.00")

        with CaptureQueriesContext(connection) as queries:
            response = self.client.get(f"/api/recruitment/screening-results/?job={self.job.pk}")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data["results"]), 12)
        self.assertLessEqual(len(queries), 18, [query["sql"] for query in queries])

    def test_results_keep_processing_failed_and_no_resume_rows_unranked(self):
        processing = self._application(10)
        failed = self._application(11)
        no_resume = self._application(12)
        processing_resume, processing_structure = self._resume(processing, 1)
        failed_resume, failed_structure = self._resume(failed, 1)
        AiProcessingTask.objects.create(
            kind=AiProcessingTask.Kind.RESUME_SCORE,
            status=AiProcessingTask.Status.MODEL,
            requested_by=self.hr,
            job=self.job,
            resume=processing_resume,
            standard=self.standard,
            idempotency_key=f"resume-score:{uuid.uuid4()}:{processing_structure.pk}:{self.standard.pk}",
        )
        AiProcessingTask.objects.create(
            kind=AiProcessingTask.Kind.RESUME_SCORE,
            status=AiProcessingTask.Status.FAILED,
            requested_by=self.hr,
            job=self.job,
            resume=failed_resume,
            standard=self.standard,
            idempotency_key=f"resume-score:{uuid.uuid4()}:{failed_structure.pk}:{self.standard.pk}",
            error_code="model_timeout",
        )

        response = self.client.get(f"/api/recruitment/screening-results/?job={self.job.pk}")
        states = {row["application"]["id"]: row["ai_state"] for row in response.data["results"]}
        self.assertEqual(states[processing.pk], "processing")
        self.assertEqual(states[failed.pk], "failed")
        self.assertEqual(states[no_resume.pk], "no_resume")
        self.assertTrue(all(row["rank"] is None for row in response.data["results"]))

    def test_old_standard_or_old_structure_tasks_do_not_define_current_ai_state(self):
        application = self._application(13)
        resume, current_structure = self._resume(application, 1)
        old_standard = JobStandardVersion.objects.create(
            job=self.job,
            version=9,
            status=JobStandardVersion.Status.SUPERSEDED,
            criteria={"summary": "历史标准", "dimensions": []},
            created_by=self.hr,
        )
        AiProcessingTask.objects.create(
            kind=AiProcessingTask.Kind.RESUME_SCORE,
            status=AiProcessingTask.Status.FAILED,
            requested_by=self.hr,
            job=self.job,
            resume=resume,
            standard=old_standard,
            idempotency_key=f"resume-score:{uuid.uuid4()}:{current_structure.pk}:{old_standard.pk}",
        )
        AiProcessingTask.objects.create(
            kind=AiProcessingTask.Kind.RESUME_SCORE,
            status=AiProcessingTask.Status.MODEL,
            requested_by=self.hr,
            job=self.job,
            resume=resume,
            standard=self.standard,
            idempotency_key=f"resume-score:{uuid.uuid4()}:999999:{self.standard.pk}",
        )

        response = self.client.get(f"/api/recruitment/screening-results/?job={self.job.pk}")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["results"][0]["ai_state"], "unscored")

    def test_results_are_scoped_to_accessible_jobs(self):
        outsider = User.objects.create_user("screening-outsider")
        AccountProfile.objects.create(user=outsider, role=AccountProfile.Role.VIEWER)
        self.client.force_login(outsider)
        response = self.client.get(f"/api/recruitment/screening-results/?job={self.job.pk}")
        self.assertEqual(response.status_code, 404)

    def test_bulk_decision_is_append_only_idempotent_and_does_not_change_stage(self):
        applications = [self._application(20), self._application(21)]
        request_id = uuid.uuid4()
        payload = {
            "request_id": str(request_id),
            "job": self.job.pk,
            "application_ids": [application.pk for application in reversed(applications)],
            "decision": "fail",
            "reason": "当前岗位匹配度不足",
        }

        created = self.client.post("/api/recruitment/screening-decisions/bulk/", payload, format="json")
        replayed = self.client.post("/api/recruitment/screening-decisions/bulk/", payload, format="json")

        self.assertEqual(created.status_code, 201, created.data)
        self.assertEqual(replayed.status_code, 200, replayed.data)
        self.assertEqual(created.data["decision_batch_id"], replayed.data["decision_batch_id"])
        self.assertEqual(ScreeningDecisionBatch.objects.count(), 1)
        self.assertEqual(ApplicationScreeningDecision.objects.count(), 2)
        self.assertEqual(
            list(ApplicationScreeningDecision.objects.order_by("application_id").values_list("version", flat=True)),
            [1, 1],
        )
        self.assertTrue(
            all(stage == JobApplication.Stage.NEW for stage in JobApplication.objects.filter(pk__in=[a.pk for a in applications]).values_list("stage", flat=True))
        )
        ranking = self.client.get(f"/api/recruitment/screening-results/?job={self.job.pk}")
        self.assertTrue(all("reason" not in row["hr_decision"] for row in ranking.data["results"]))

        conflict = self.client.post(
            "/api/recruitment/screening-decisions/bulk/",
            {**payload, "decision": "pass"},
            format="json",
        )
        self.assertEqual(conflict.status_code, 409)
        self.assertEqual(ScreeningDecisionBatch.objects.count(), 1)

    def test_bulk_decision_rejects_mixed_job_scope_as_a_whole(self):
        application = self._application(30)
        other_job = RecruitmentJob.objects.create(
            boss_account=self.account,
            external_id="other-job",
            title="另一个岗位",
            owner=self.hr,
        )
        other_candidate = Candidate.objects.create(identity_key="other-job-candidate", name="其他候选人")
        other_application = JobApplication.objects.create(
            candidate=other_candidate,
            job=other_job,
            source="boss",
        )

        response = self.client.post(
            "/api/recruitment/screening-decisions/bulk/",
            {
                "request_id": str(uuid.uuid4()),
                "job": self.job.pk,
                "application_ids": [application.pk, other_application.pk],
                "decision": "pass",
                "reason": "通过初筛",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(ScreeningDecisionBatch.objects.count(), 0)
        self.assertEqual(ApplicationScreeningDecision.objects.count(), 0)

    def test_bulk_decision_revalidates_locked_job_after_stale_view_snapshot(self):
        application = self._application(31)
        stale_job = self.job
        RecruitmentJob.objects.filter(pk=self.job.pk).update(archived_at=timezone.now())

        with self.assertRaisesMessage(ValidationError, "所选岗位已归档"):
            create_screening_decisions(
                request_id=uuid.uuid4(),
                job=stale_job,
                application_ids=[application.pk],
                decision=ApplicationScreeningDecision.Decision.PASS,
                reason="通过初筛",
                actor=self.hr,
            )

        self.assertEqual(ScreeningDecisionBatch.objects.count(), 0)
        self.assertEqual(ApplicationScreeningDecision.objects.count(), 0)

    def test_viewer_cannot_create_decisions(self):
        application = self._application(40)
        viewer = User.objects.create_user("screening-viewer")
        AccountProfile.objects.create(user=viewer, role=AccountProfile.Role.VIEWER)
        self.account.authorized_users.add(viewer)
        self.client.force_login(viewer)
        response = self.client.post(
            "/api/recruitment/screening-decisions/bulk/",
            {
                "request_id": str(uuid.uuid4()),
                "job": self.job.pk,
                "application_ids": [application.pk],
                "decision": "pass",
                "reason": "通过初筛",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 403)
