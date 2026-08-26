import uuid
from contextlib import nullcontext
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import SimpleTestCase, TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APITestCase

from attendance.models import AccountProfile
from recruitment.management.commands.run_rpa_worker import WorkerEngine, execute_rejection_notice
from recruitment.models import (
    ApplicationScreeningDecision,
    AutomationApproval,
    AutomationUsage,
    BossAccount,
    Candidate,
    ConversationAction,
    ExecutionBatch,
    HumanAttention,
    JobApplication,
    RecruitmentAuditLog,
    RecruitmentJob,
    RpaTask,
    RpaTaskEvent,
    RpaWorker,
    ScreeningDecisionBatch,
    StepExecution,
)
from recruitment.rpa.cli import CliAccountConfig
from recruitment.services.communications import complete_communication_task
from recruitment.services.approvals import reject as reject_approval
from recruitment.services.task_recovery import recover_stale_tasks


class RejectionNoticeApiTests(APITestCase):
    def setUp(self):
        self.hr = User.objects.create_user("rejection-hr")
        AccountProfile.objects.create(user=self.hr, role=AccountProfile.Role.HR)
        self.account = BossAccount.objects.create(
            name="Rejection account",
            browser_profile="rejection-account",
            cdp_port=54331,
            daily_message_limit=10,
        )
        self.account.authorized_users.add(self.hr)
        self.job = RecruitmentJob.objects.create(
            boss_account=self.account,
            external_id="rejection-job",
            title="数据分析师",
            owner=self.hr,
        )
        self.applications = []
        for index in range(2):
            candidate = Candidate.objects.create(
                identity_key=f"rejection-candidate-{index}",
                external_id=f"boss-rejection-{index}",
                name=f"候选人{index}",
            )
            self.applications.append(
                JobApplication.objects.create(
                    candidate=candidate,
                    job=self.job,
                    source="boss",
                    owner=self.hr,
                )
            )
        self.client.force_login(self.hr)

    def _fail_decision(self):
        response = self.client.post(
            "/api/recruitment/screening-decisions/bulk/",
            {
                "request_id": str(uuid.uuid4()),
                "job": self.job.pk,
                "application_ids": [application.pk for application in self.applications],
                "decision": "fail",
                "reason": "岗位匹配度不足",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.data)
        return response.data["decision_batch_id"]

    def _prepare(self, decision_batch_id, *, request_id=None):
        return self.client.post(
            "/api/recruitment/rejection-notices/prepare/",
            {
                "request_id": str(request_id or uuid.uuid4()),
                "decision_batch_id": decision_batch_id,
                "message": "您好，感谢您对数据分析师岗位的关注和时间。综合本次招聘安排，我们暂时无法继续推进后续流程，祝您求职顺利。",
            },
            format="json",
        )

    def test_prepare_rejects_non_template_or_sensitive_candidate_facing_copy(self):
        response = self.client.post(
            "/api/recruitment/rejection-notices/prepare/",
            {
                "request_id": str(uuid.uuid4()),
                "decision_batch_id": self._fail_decision(),
                "message": "AI 评分只有 42 分，内部判断经验不足，因此不予通过。",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 400, response.data)
        self.assertIn("中性模板", str(response.data))
        self.assertEqual(AutomationApproval.objects.count(), 0)
        self.assertEqual(ConversationAction.objects.count(), 0)

    def test_prepare_then_approve_reserves_whole_quota_and_materializes_all_tasks(self):
        decision_batch_id = self._fail_decision()
        prepared = self._prepare(decision_batch_id)
        self.assertEqual(prepared.status_code, 201, prepared.data)
        self.assertEqual(prepared.data["status"], AutomationApproval.Status.DRAFT)
        self.assertEqual(ExecutionBatch.objects.count(), 0)
        self.assertEqual(AutomationUsage.objects.count(), 0)

        approved = self.client.post(
            f"/api/recruitment/automation-approvals/{prepared.data['approval_id']}/approve/",
            {},
            format="json",
        )

        self.assertEqual(approved.status_code, 201, approved.data)
        batch = ExecutionBatch.objects.get(approval_id=prepared.data["approval_id"])
        self.assertEqual(batch.reserved_metric, AutomationUsage.Metric.MESSAGE)
        self.assertEqual(batch.reserved_amount, 2)
        self.assertEqual(batch.reserved_day, timezone.localdate())
        self.assertEqual(batch.steps.count(), 2)
        self.assertEqual(batch.rpa_tasks.count(), 2)
        self.assertEqual(batch.rpa_tasks.filter(status=RpaTask.Status.PENDING).count(), 2)
        self.assertEqual(
            AutomationUsage.objects.get(boss_account=self.account, metric=AutomationUsage.Metric.MESSAGE).used,
            2,
        )

        replayed = self.client.post(
            f"/api/recruitment/automation-approvals/{prepared.data['approval_id']}/approve/",
            {},
            format="json",
        )
        self.assertEqual(replayed.status_code, 200, replayed.data)
        self.assertEqual(batch.rpa_tasks.count(), 2)
        self.assertEqual(
            AutomationUsage.objects.get(boss_account=self.account, metric=AutomationUsage.Metric.MESSAGE).used,
            2,
        )

    def test_quota_shortage_rolls_back_approval_batch_steps_tasks_and_usage(self):
        self.account.daily_message_limit = 1
        self.account.save(update_fields=["daily_message_limit"])
        prepared = self._prepare(self._fail_decision())

        approved = self.client.post(
            f"/api/recruitment/automation-approvals/{prepared.data['approval_id']}/approve/",
            {},
            format="json",
        )

        self.assertEqual(approved.status_code, 400)
        approval = AutomationApproval.objects.get(pk=prepared.data["approval_id"])
        self.assertEqual(approval.status, AutomationApproval.Status.DRAFT)
        self.assertEqual(ExecutionBatch.objects.count(), 0)
        self.assertEqual(RpaTask.objects.count(), 0)
        self.assertEqual(AutomationUsage.objects.count(), 0)

    def test_prepare_is_idempotent_and_payload_conflict_is_409(self):
        decision_batch_id = self._fail_decision()
        request_id = uuid.uuid4()
        first = self._prepare(decision_batch_id, request_id=request_id)
        replay = self._prepare(decision_batch_id, request_id=request_id)
        conflict = self.client.post(
            "/api/recruitment/rejection-notices/prepare/",
            {
                "request_id": str(request_id),
                "decision_batch_id": decision_batch_id,
                "message": "另一份不同的通知文案",
            },
            format="json",
        )
        self.assertEqual(first.status_code, 201, first.data)
        self.assertEqual(replay.status_code, 200, replay.data)
        self.assertEqual(first.data["approval_id"], replay.data["approval_id"])
        self.assertEqual(conflict.status_code, 409)
        self.assertEqual(AutomationApproval.objects.count(), 1)

    def test_rejection_approval_response_redacts_platform_identity_snapshots(self):
        prepared = self._prepare(self._fail_decision())
        response = self.client.get(
            f"/api/recruitment/automation-approvals/{prepared.data['approval_id']}/"
        )
        self.assertEqual(response.status_code, 200)
        approved = self.client.post(
            f"/api/recruitment/automation-approvals/{prepared.data['approval_id']}/approve/",
            {},
            format="json",
        )
        self.assertEqual(approved.status_code, 201)
        action = ConversationAction.objects.filter(approval_id=prepared.data["approval_id"]).first()
        action.error_code = "worker_error"
        action.error_message = "RAW_EXCEPTION_SECRET external_id=boss-rejection-0"
        action.result = {"expected_external_id": "boss-rejection-0"}
        action.save(update_fields=["error_code", "error_message", "result"])
        action.step.error_code = "worker_error"
        action.step.error_message = "RAW_EXCEPTION_SECRET"
        action.step.result = {"observed_external_id": "boss-rejection-0"}
        action.step.save(update_fields=["error_code", "error_message", "result"])
        task = RpaTask.objects.get(request_payload__conversation_action_id=str(action.pk))
        task.error_code = "worker_error"
        task.error_message = "RAW_EXCEPTION_SECRET"
        task.result = {"observed_external_id": "boss-rejection-0"}
        task.save(update_fields=["error_code", "error_message", "result"])
        RpaTaskEvent.objects.create(
            task=task,
            level="error",
            event="worker_error",
            message="RAW_EXCEPTION_SECRET external_id=boss-rejection-0",
            data={"fingerprint": "RAW_FINGERPRINT_SECRET"},
        )
        serialized = [
            response.data,
            self.client.get(f"/api/recruitment/communication-actions/{action.pk}/").data,
            self.client.get(f"/api/recruitment/rpa-tasks/{task.pk}/").data,
            self.client.get(f"/api/recruitment/execution-batches/{action.batch_id}/").data,
            self.client.get(f"/api/recruitment/screening-results/?job={self.job.pk}").data,
        ]
        encoded = str(serialized)
        self.assertNotIn("external_id", encoded)
        self.assertNotIn("fingerprint", encoded)
        self.assertNotIn("boss-rejection-0", encoded)
        self.assertNotIn("RAW_EXCEPTION_SECRET", encoded)
        self.assertNotIn("综合本次招聘安排", encoded)

    def test_prepare_rejects_stale_fail_decision_and_late_stage(self):
        fail_batch_id = self._fail_decision()
        pass_response = self.client.post(
            "/api/recruitment/screening-decisions/bulk/",
            {
                "request_id": str(uuid.uuid4()),
                "job": self.job.pk,
                "application_ids": [application.pk for application in self.applications],
                "decision": "pass",
                "reason": "复核后通过",
            },
            format="json",
        )
        self.assertEqual(pass_response.status_code, 201)
        stale = self._prepare(fail_batch_id)
        self.assertEqual(stale.status_code, 400)

        current_fail_id = self._fail_decision()
        self.applications[0].stage = JobApplication.Stage.TO_INTERVIEW
        self.applications[0].save(update_fields=["stage"])
        late = self._prepare(current_fail_id)
        self.assertEqual(late.status_code, 400)

    def test_decision_changed_after_prepare_blocks_approval_without_quota_or_tasks(self):
        prepared = self._prepare(self._fail_decision())
        changed = self.client.post(
            "/api/recruitment/screening-decisions/bulk/",
            {
                "request_id": str(uuid.uuid4()),
                "job": self.job.pk,
                "application_ids": [application.pk for application in self.applications],
                "decision": "pass",
                "reason": "人工复核后通过",
            },
            format="json",
        )
        self.assertEqual(changed.status_code, 201)

        approved = self.client.post(
            f"/api/recruitment/automation-approvals/{prepared.data['approval_id']}/approve/",
            {},
            format="json",
        )

        self.assertEqual(approved.status_code, 400)
        approval = AutomationApproval.objects.get(pk=prepared.data["approval_id"])
        self.assertEqual(approval.status, AutomationApproval.Status.DRAFT)
        self.assertEqual(ExecutionBatch.objects.count(), 0)
        self.assertEqual(RpaTask.objects.count(), 0)
        self.assertEqual(AutomationUsage.objects.count(), 0)

    def test_active_or_succeeded_notice_blocks_new_fail_batch_from_recreating_it(self):
        first_decision_batch = self._fail_decision()
        first_prepared = self._prepare(first_decision_batch)
        self.assertEqual(first_prepared.status_code, 201)
        blocked_active = self._prepare(first_decision_batch)
        self.assertEqual(blocked_active.status_code, 400)

        ConversationAction.objects.filter(
            approval_id=first_prepared.data["approval_id"]
        ).update(status=ConversationAction.Status.SUCCEEDED)
        for application in self.applications:
            ConversationAction.objects.create(
                application=application,
                boss_account=self.account,
                action=ConversationAction.Action.REJECTION_NOTICE,
                status=ConversationAction.Status.CANCELLED,
                message_snapshot="已取消的较新草稿",
                target_snapshot={"application_id": application.pk},
                idempotency_key=f"cancelled-after-succeeded-{application.pk}",
                created_by=self.hr,
                completed_at=timezone.now(),
            )
        results = self.client.get(f"/api/recruitment/screening-results/?job={self.job.pk}")
        self.assertTrue(all(
            row["notification"]["status"] == ConversationAction.Status.SUCCEEDED
            for row in results.data["results"]
        ))
        third_fail = self._fail_decision()
        blocked_succeeded = self._prepare(third_fail)
        self.assertEqual(blocked_succeeded.status_code, 400)
        self.assertEqual(AutomationApproval.objects.count(), 1)

    def test_expired_draft_is_cancelled_and_new_prepare_is_allowed(self):
        decision_batch_id = self._fail_decision()
        first = self._prepare(decision_batch_id)
        self.assertEqual(first.status_code, 201, first.data)
        approval = AutomationApproval.objects.get(pk=first.data["approval_id"])
        approval.expires_at = timezone.now() - timedelta(seconds=1)
        approval.save(update_fields=["expires_at"])

        result = self.client.get(f"/api/recruitment/screening-results/?job={self.job.pk}")
        self.assertEqual(result.status_code, 200, result.data)
        self.assertTrue(all(
            row["notification"]["status"] == "not_requested"
            for row in result.data["results"]
        ))

        replacement = self._prepare(decision_batch_id)

        self.assertEqual(replacement.status_code, 201, replacement.data)
        self.assertNotEqual(replacement.data["approval_id"], first.data["approval_id"])
        approval.refresh_from_db()
        self.assertEqual(approval.status, AutomationApproval.Status.EXPIRED)
        self.assertFalse(
            ConversationAction.objects.filter(
                approval=approval,
                status=ConversationAction.Status.DRAFT,
            ).exists()
        )

    def test_rejected_draft_is_cancelled_and_new_prepare_is_allowed(self):
        decision_batch_id = self._fail_decision()
        first = self._prepare(decision_batch_id)
        self.assertEqual(first.status_code, 201, first.data)
        approval = AutomationApproval.objects.get(pk=first.data["approval_id"])
        reject_approval(
            approval=approval,
            actor=self.hr,
            note="RAW_REJECTION_NOTE external_id=boss-rejection-0",
        )
        approval.refresh_from_db()
        self.assertEqual(approval.status, AutomationApproval.Status.REJECTED)
        rejection_audit = RecruitmentAuditLog.objects.get(
            action="automation_approval_rejected",
            target_id=str(approval.pk),
        )
        self.assertNotIn("RAW_REJECTION_NOTE", str(rejection_audit.detail))
        self.assertNotIn("boss-rejection-0", str(rejection_audit.detail))
        self.assertFalse(
            ConversationAction.objects.filter(
                approval=approval,
                status=ConversationAction.Status.DRAFT,
            ).exists()
        )

        result = self.client.get(f"/api/recruitment/screening-results/?job={self.job.pk}")
        self.assertEqual(result.status_code, 200, result.data)
        self.assertTrue(all(
            row["notification"]["status"] == ConversationAction.Status.CANCELLED
            for row in result.data["results"]
        ))

        replacement = self._prepare(decision_batch_id)

        self.assertEqual(replacement.status_code, 201, replacement.data)
        self.assertNotEqual(replacement.data["approval_id"], first.data["approval_id"])
        self.assertFalse(
            ConversationAction.objects.filter(
                approval=approval,
                status=ConversationAction.Status.DRAFT,
            ).exists()
        )

    def test_approve_expired_rejection_persists_expired_and_cancels_drafts(self):
        prepared = self._prepare(self._fail_decision())
        approval = AutomationApproval.objects.get(pk=prepared.data["approval_id"])
        approval.expires_at = timezone.now() - timedelta(seconds=1)
        approval.save(update_fields=["expires_at"])

        response = self.client.post(
            f"/api/recruitment/automation-approvals/{approval.pk}/approve/",
            {},
            format="json",
        )

        self.assertEqual(response.status_code, 400, response.data)
        approval.refresh_from_db()
        self.assertEqual(approval.status, AutomationApproval.Status.EXPIRED)
        self.assertFalse(
            ConversationAction.objects.filter(
                approval=approval,
                status=ConversationAction.Status.DRAFT,
            ).exists()
        )
        self.assertEqual(ExecutionBatch.objects.count(), 0)
        self.assertEqual(AutomationUsage.objects.count(), 0)

    def _approved_batch(self):
        prepared = self._prepare(self._fail_decision())
        self.assertEqual(prepared.status_code, 201, prepared.data)
        approved = self.client.post(
            f"/api/recruitment/automation-approvals/{prepared.data['approval_id']}/approve/",
            {},
            format="json",
        )
        self.assertEqual(approved.status_code, 201, approved.data)
        return ExecutionBatch.objects.get(approval_id=prepared.data["approval_id"])

    def test_new_pass_cancels_pending_rejection_for_that_application(self):
        batch = self._approved_batch()
        application = self.applications[0]
        action = ConversationAction.objects.get(
            batch=batch,
            application=application,
            action=ConversationAction.Action.REJECTION_NOTICE,
        )
        task = RpaTask.objects.get(request_payload__conversation_action_id=str(action.pk))

        response = self.client.post(
            "/api/recruitment/screening-decisions/bulk/",
            {
                "request_id": str(uuid.uuid4()),
                "job": self.job.pk,
                "application_ids": [application.pk],
                "decision": "pass",
                "reason": "人工复核后通过",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 201, response.data)
        task.refresh_from_db()
        action.refresh_from_db()
        action.step.refresh_from_db()
        application.refresh_from_db()
        self.assertEqual(task.status, RpaTask.Status.CANCELLED)
        self.assertEqual(action.status, ConversationAction.Status.CANCELLED)
        self.assertEqual(action.step.status, StepExecution.Status.CANCELLED)
        self.assertEqual(application.stage, JobApplication.Stage.NEW)
        self.assertEqual(
            batch.rpa_tasks.filter(status=RpaTask.Status.PENDING).count(),
            1,
        )

    def test_new_decision_is_409_once_rejection_task_is_leased(self):
        batch = self._approved_batch()
        application = self.applications[0]
        action = ConversationAction.objects.get(batch=batch, application=application)
        task = RpaTask.objects.get(request_payload__conversation_action_id=str(action.pk))
        task.status = RpaTask.Status.LEASED
        task.lease_expires_at = timezone.now() + timedelta(minutes=1)
        task.save(update_fields=["status", "lease_expires_at"])
        before_batches = ScreeningDecisionBatch.objects.count()

        response = self.client.post(
            "/api/recruitment/screening-decisions/bulk/",
            {
                "request_id": str(uuid.uuid4()),
                "job": self.job.pk,
                "application_ids": [application.pk],
                "decision": "pass",
                "reason": "人工复核后通过",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 409, response.data)
        self.assertEqual(ScreeningDecisionBatch.objects.count(), before_batches)
        latest = application.screening_decisions.order_by("-version", "-id").first()
        self.assertEqual(latest.decision, ApplicationScreeningDecision.Decision.FAIL)
        task.refresh_from_db()
        self.assertEqual(task.status, RpaTask.Status.LEASED)

    def test_forbidden_stage_cancels_pending_rejection_before_stage_change(self):
        batch = self._approved_batch()
        application = self.applications[0]
        action = ConversationAction.objects.get(batch=batch, application=application)
        task = RpaTask.objects.get(request_payload__conversation_action_id=str(action.pk))

        response = self.client.patch(
            f"/api/recruitment/applications/{application.pk}/",
            {"stage": JobApplication.Stage.TO_INTERVIEW, "stage_reason": "人工确认进入面试"},
            format="json",
        )

        self.assertEqual(response.status_code, 200, response.data)
        application.refresh_from_db()
        task.refresh_from_db()
        action.refresh_from_db()
        action.step.refresh_from_db()
        self.assertEqual(application.stage, JobApplication.Stage.TO_INTERVIEW)
        self.assertEqual(task.status, RpaTask.Status.CANCELLED)
        self.assertEqual(action.status, ConversationAction.Status.CANCELLED)
        self.assertEqual(action.step.status, StepExecution.Status.CANCELLED)

    def test_forbidden_stage_is_409_once_rejection_task_is_leased(self):
        batch = self._approved_batch()
        application = self.applications[0]
        action = ConversationAction.objects.get(batch=batch, application=application)
        task = RpaTask.objects.get(request_payload__conversation_action_id=str(action.pk))
        task.status = RpaTask.Status.LEASED
        task.lease_expires_at = timezone.now() + timedelta(minutes=1)
        task.save(update_fields=["status", "lease_expires_at"])

        response = self.client.patch(
            f"/api/recruitment/applications/{application.pk}/",
            {"stage": JobApplication.Stage.TO_INTERVIEW, "stage_reason": "人工确认进入面试"},
            format="json",
        )

        self.assertEqual(response.status_code, 409, response.data)
        application.refresh_from_db()
        task.refresh_from_db()
        self.assertEqual(application.stage, JobApplication.Stage.NEW)
        self.assertEqual(task.status, RpaTask.Status.LEASED)

    def test_archiving_application_cancels_pending_rejection_before_archive(self):
        batch = self._approved_batch()
        application = self.applications[0]
        action = ConversationAction.objects.get(batch=batch, application=application)
        task = RpaTask.objects.get(request_payload__conversation_action_id=str(action.pk))

        response = self.client.post(
            f"/api/recruitment/applications/{application.pk}/archive/",
            {},
            format="json",
        )

        self.assertEqual(response.status_code, 200, response.data)
        application.refresh_from_db()
        task.refresh_from_db()
        action.refresh_from_db()
        self.assertIsNotNone(application.archived_at)
        self.assertEqual(task.status, RpaTask.Status.CANCELLED)
        self.assertEqual(action.status, ConversationAction.Status.CANCELLED)

    def test_archiving_application_is_409_once_rejection_is_leased(self):
        batch = self._approved_batch()
        application = self.applications[0]
        action = ConversationAction.objects.get(batch=batch, application=application)
        task = RpaTask.objects.get(request_payload__conversation_action_id=str(action.pk))
        task.status = RpaTask.Status.LEASED
        task.lease_expires_at = timezone.now() + timedelta(minutes=1)
        task.save(update_fields=["status", "lease_expires_at"])

        response = self.client.post(
            f"/api/recruitment/applications/{application.pk}/archive/",
            {},
            format="json",
        )

        self.assertEqual(response.status_code, 409, response.data)
        application.refresh_from_db()
        task.refresh_from_db()
        self.assertIsNone(application.archived_at)
        self.assertEqual(task.status, RpaTask.Status.LEASED)

    def test_archiving_job_cancels_all_pending_rejection_tasks(self):
        batch = self._approved_batch()

        response = self.client.post(
            f"/api/recruitment/jobs/{self.job.pk}/archive/",
            {},
            format="json",
        )

        self.assertEqual(response.status_code, 200, response.data)
        self.job.refresh_from_db()
        self.assertIsNotNone(self.job.archived_at)
        self.assertEqual(self.job.status, RecruitmentJob.Status.CLOSED)
        self.assertEqual(
            batch.rpa_tasks.filter(status=RpaTask.Status.CANCELLED).count(),
            2,
        )

    def test_closing_job_cancels_all_pending_rejection_tasks(self):
        batch = self._approved_batch()

        response = self.client.patch(
            f"/api/recruitment/jobs/{self.job.pk}/",
            {"status": RecruitmentJob.Status.CLOSED},
            format="json",
        )

        self.assertEqual(response.status_code, 200, response.data)
        self.job.refresh_from_db()
        self.assertEqual(self.job.status, RecruitmentJob.Status.CLOSED)
        self.assertEqual(
            batch.rpa_tasks.filter(status=RpaTask.Status.CANCELLED).count(),
            2,
        )

    def test_closing_job_is_409_once_rejection_is_leased(self):
        batch = self._approved_batch()
        task = batch.rpa_tasks.order_by("created_at").first()
        task.status = RpaTask.Status.LEASED
        task.lease_expires_at = timezone.now() + timedelta(minutes=1)
        task.save(update_fields=["status", "lease_expires_at"])

        response = self.client.patch(
            f"/api/recruitment/jobs/{self.job.pk}/",
            {"status": RecruitmentJob.Status.CLOSED},
            format="json",
        )

        self.assertEqual(response.status_code, 409, response.data)
        self.job.refresh_from_db()
        task.refresh_from_db()
        self.assertEqual(self.job.status, RecruitmentJob.Status.OPEN)
        self.assertEqual(task.status, RpaTask.Status.LEASED)

    def test_archiving_candidate_cancels_its_pending_rejection_task(self):
        batch = self._approved_batch()
        application = self.applications[0]
        action = ConversationAction.objects.get(batch=batch, application=application)
        task = RpaTask.objects.get(request_payload__conversation_action_id=str(action.pk))

        response = self.client.post(
            f"/api/recruitment/candidates/{application.candidate_id}/archive/",
            {},
            format="json",
        )

        self.assertEqual(response.status_code, 200, response.data)
        application.candidate.refresh_from_db()
        task.refresh_from_db()
        self.assertIsNotNone(application.candidate.archived_at)
        self.assertEqual(task.status, RpaTask.Status.CANCELLED)

    @override_settings(RPA_WORKER_TOKEN="rejection-worker-secret")
    def test_worker_lease_cancels_stale_rejection_snapshot_before_dispatch(self):
        batch = self._approved_batch()
        application = self.applications[0]
        action = ConversationAction.objects.get(batch=batch, application=application)
        stale_task = RpaTask.objects.get(request_payload__conversation_action_id=str(action.pk))
        old_decision = application.screening_decisions.order_by("-version", "-id").first()
        new_batch = ScreeningDecisionBatch.objects.create(
            request_id=uuid.uuid4(),
            job=self.job,
            decision=ApplicationScreeningDecision.Decision.PASS,
            reason="数据库并发后的新结论",
            payload_hash="b" * 64,
            created_by=self.hr,
        )
        ApplicationScreeningDecision.objects.create(
            batch=new_batch,
            application=application,
            resume=old_decision.resume,
            assessment=old_decision.assessment,
            decision=ApplicationScreeningDecision.Decision.PASS,
            reason="数据库并发后的新结论",
            version=old_decision.version + 1,
            decided_by=self.hr,
        )
        worker = RpaWorker.objects.create(
            key="rejection-lease-worker",
            hostname="TEST",
            status=RpaWorker.Status.ONLINE,
            last_seen_at=timezone.now(),
        )

        response = self.client.post(
            "/api/recruitment/worker/tasks/lease/",
            {"worker_key": worker.key},
            format="json",
            HTTP_X_RPA_WORKER_TOKEN="rejection-worker-secret",
        )

        self.assertEqual(response.status_code, 200, response.data)
        stale_task.refresh_from_db()
        action.refresh_from_db()
        self.assertEqual(stale_task.status, RpaTask.Status.CANCELLED)
        self.assertEqual(stale_task.error_code, "rejection_snapshot_stale")
        self.assertEqual(action.status, ConversationAction.Status.CANCELLED)
        if response.data["task"] is not None:
            self.assertNotEqual(response.data["task"]["id"], str(stale_task.pk))

    @override_settings(RPA_WORKER_TOKEN="rejection-worker-secret")
    def test_worker_started_event_marks_action_step_batch_and_screening_result_running(self):
        batch = self._approved_batch()
        worker = RpaWorker.objects.create(
            key="rejection-running-worker",
            hostname="TEST",
            status=RpaWorker.Status.ONLINE,
            last_seen_at=timezone.now(),
        )
        leased = self.client.post(
            "/api/recruitment/worker/tasks/lease/",
            {"worker_key": worker.key},
            format="json",
            HTTP_X_RPA_WORKER_TOKEN="rejection-worker-secret",
        )
        self.assertEqual(leased.status_code, 200, leased.data)
        task = RpaTask.objects.get(pk=leased.data["task"]["id"])
        action = ConversationAction.objects.get(
            pk=task.request_payload["conversation_action_id"]
        )

        event = self.client.post(
            f"/api/recruitment/worker/tasks/{task.pk}/event/",
            {
                "worker_key": worker.key,
                "lease_token": leased.data["task"]["lease_token"],
                "lease_generation": leased.data["task"]["lease_generation"],
                "event": "started",
                "message": "开始发送",
            },
            format="json",
            HTTP_X_RPA_WORKER_TOKEN="rejection-worker-secret",
        )

        self.assertEqual(event.status_code, 201, event.data)
        task.refresh_from_db()
        action.refresh_from_db()
        action.step.refresh_from_db()
        batch.refresh_from_db()
        self.assertEqual(task.status, RpaTask.Status.RUNNING)
        self.assertEqual(action.status, ConversationAction.Status.RUNNING)
        self.assertEqual(action.step.status, StepExecution.Status.RUNNING)
        self.assertEqual(batch.status, ExecutionBatch.Status.RUNNING)
        results = self.client.get(f"/api/recruitment/screening-results/?job={self.job.pk}")
        row = next(
            item for item in results.data["results"]
            if item["application"]["id"] == action.application_id
        )
        self.assertEqual(row["notification"]["status"], ConversationAction.Status.RUNNING)


class RejectionNoticeCompletionTests(TestCase):
    def setUp(self):
        self.hr = User.objects.create_user("rejection-completion-hr")
        AccountProfile.objects.create(user=self.hr, role=AccountProfile.Role.HR)
        self.account = BossAccount.objects.create(
            name="Rejection completion",
            browser_profile="rejection-completion",
            cdp_port=54332,
        )
        self.account.authorized_users.add(self.hr)
        self.job = RecruitmentJob.objects.create(
            boss_account=self.account,
            external_id="rejection-completion-job",
            title="测试工程师",
            owner=self.hr,
        )
        self.applications = []
        for index in range(2):
            candidate = Candidate.objects.create(
                identity_key=f"completion-candidate-{index}",
                external_id=f"completion-external-{index}",
                name=f"候选人{index}",
            )
            self.applications.append(JobApplication.objects.create(candidate=candidate, job=self.job, source="boss"))
        decision_batch = ScreeningDecisionBatch.objects.create(
            request_id=uuid.uuid4(),
            job=self.job,
            decision=ApplicationScreeningDecision.Decision.FAIL,
            reason="不匹配",
            payload_hash="a" * 64,
            created_by=self.hr,
        )
        self.decisions = [
            ApplicationScreeningDecision.objects.create(
                batch=decision_batch,
                application=application,
                decision=ApplicationScreeningDecision.Decision.FAIL,
                reason="不匹配",
                version=1,
                decided_by=self.hr,
            )
            for application in self.applications
        ]
        self.approval = AutomationApproval.objects.create(
            action=AutomationApproval.Action.REJECTION_NOTICE,
            boss_account=self.account,
            created_by=self.hr,
            approved_by=self.hr,
            approved_at=timezone.now(),
            status=AutomationApproval.Status.APPROVED,
            item_count=2,
            payload={"action": "rejection_notice", "message": "感谢关注", "items": []},
        )
        self.batch = ExecutionBatch.objects.create(
            approval=self.approval,
            boss_account=self.account,
            action=ConversationAction.Action.REJECTION_NOTICE,
            idempotency_key=f"communication-batch:{self.approval.pk}",
            created_by=self.hr,
            total_items=2,
            reserved_metric=AutomationUsage.Metric.MESSAGE,
            reserved_amount=2,
            reserved_day=timezone.localdate(),
            quota_reserved_at=timezone.now(),
        )
        self.tasks = []
        items = []
        for application, decision in zip(self.applications, self.decisions):
            target = {
                "boss_account_id": self.account.pk,
                "candidate_id": application.candidate_id,
                "application_id": application.pk,
                "name": application.candidate.name,
                "external_id": application.candidate.external_id,
                "fingerprint": "",
                "job_id": self.job.pk,
                "job_title": self.job.title,
                "screening_decision_id": decision.pk,
            }
            action = ConversationAction.objects.create(
                application=application,
                boss_account=self.account,
                action=ConversationAction.Action.REJECTION_NOTICE,
                status=ConversationAction.Status.PENDING,
                message_snapshot="感谢关注",
                target_snapshot=target,
                idempotency_key=f"completion-action-{application.pk}",
                approval=self.approval,
                batch=self.batch,
                created_by=self.hr,
            )
            step = StepExecution.objects.create(batch=self.batch, target_key=str(action.pk), target_payload=target)
            action.step = step
            action.save(update_fields=["step"])
            item = {"conversation_action_id": str(action.pk), **target}
            items.append(item)
            self.tasks.append(RpaTask.objects.create(
                boss_account=self.account,
                action=RpaTask.Action.REJECTION_NOTICE,
                created_by=self.hr,
                approval=self.approval,
                execution_batch=self.batch,
                idempotency_key=f"communication-task:{action.pk}",
                request_payload={
                    "step_id": step.pk,
                    "conversation_action_id": str(action.pk),
                    "message": "感谢关注",
                    "target": target,
                },
            ))
        self.approval.payload["items"] = items
        self.approval.save(update_fields=["payload"])
        self.client.force_login(self.hr)

    def test_item_identity_waiting_human_does_not_cancel_other_pending_items(self):
        complete_communication_task(
            task=self.tasks[0],
            status=RpaTask.Status.WAITING_HUMAN,
            result={},
            error_code="stable_identity_action_unavailable",
            error_message="需要人工发送",
        )
        self.tasks[1].refresh_from_db()
        self.assertEqual(self.tasks[1].status, RpaTask.Status.PENDING)
        self.assertEqual(self.tasks[1].request_payload["message"], "感谢关注")

    def test_uncertain_account_result_cancels_every_remaining_item(self):
        complete_communication_task(
            task=self.tasks[0],
            status=RpaTask.Status.WAITING_HUMAN,
            result={},
            error_code="browser_identity_check",
            error_message="浏览器身份不确定",
        )
        self.tasks[1].refresh_from_db()
        second_action = ConversationAction.objects.get(
            pk=self.tasks[1].request_payload["conversation_action_id"]
        )
        self.assertEqual(self.tasks[1].status, RpaTask.Status.CANCELLED)
        self.assertEqual(second_action.status, ConversationAction.Status.CANCELLED)
        self.assertEqual(second_action.step.status, StepExecution.Status.CANCELLED)

    def test_successful_rejection_notice_does_not_change_application_stage(self):
        external_id = self.tasks[0].request_payload["target"]["external_id"]
        complete_communication_task(
            task=self.tasks[0],
            status=RpaTask.Status.SUCCEEDED,
            result={
                "verified": True,
                "expected_external_id": external_id,
                "observed_external_id": external_id,
            },
            error_code="",
            error_message="",
        )
        self.applications[0].refresh_from_db()
        self.assertEqual(self.applications[0].stage, JobApplication.Stage.NEW)

    def test_running_worker_timeout_is_uncertain_and_stops_remaining_items(self):
        self.tasks[0].status = RpaTask.Status.RUNNING
        self.tasks[0].lease_expires_at = timezone.now() - timedelta(seconds=1)
        self.tasks[0].save(update_fields=["status", "lease_expires_at"])

        result = recover_stale_tasks(now=timezone.now())

        self.tasks[0].refresh_from_db()
        self.tasks[1].refresh_from_db()
        first_action = ConversationAction.objects.get(
            pk=self.tasks[0].request_payload["conversation_action_id"]
        )
        self.assertEqual(result.failed_running, 1)
        self.assertEqual(self.tasks[0].status, RpaTask.Status.WAITING_HUMAN)
        self.assertEqual(self.tasks[0].error_code, "external_result_uncertain")
        self.assertEqual(first_action.status, ConversationAction.Status.WAITING_HUMAN)
        self.assertEqual(first_action.error_code, "external_result_uncertain")
        self.assertEqual(self.tasks[1].status, RpaTask.Status.CANCELLED)
        attention = HumanAttention.objects.get(
            idempotency_key=f"rejection-notice-result-uncertain:{self.tasks[0].pk}"
        )
        self.assertEqual(attention.status, HumanAttention.Status.OPEN)
        self.assertEqual(attention.boss_account, self.account)
        self.assertEqual(attention.job, self.job)
        self.assertEqual(attention.application, self.applications[0])
        self.assertEqual(attention.detail["error_code"], "external_result_uncertain")
        self.assertNotIn(self.applications[0].candidate.external_id, str(attention.detail))

    def test_unverified_success_is_external_uncertain_and_stops_remaining_items(self):
        complete_communication_task(
            task=self.tasks[0],
            status=RpaTask.Status.SUCCEEDED,
            result={"verified": False},
            error_code="",
            error_message="",
        )

        self.tasks[0].refresh_from_db()
        self.tasks[1].refresh_from_db()
        first_action = ConversationAction.objects.get(
            pk=self.tasks[0].request_payload["conversation_action_id"]
        )
        self.assertEqual(self.tasks[0].status, RpaTask.Status.WAITING_HUMAN)
        self.assertEqual(self.tasks[0].error_code, "external_result_uncertain")
        self.assertEqual(first_action.error_code, "external_result_uncertain")
        self.assertEqual(self.tasks[1].status, RpaTask.Status.CANCELLED)

    def test_uncertain_attention_is_idempotent_and_resolution_does_not_change_execution(self):
        for _ in range(2):
            complete_communication_task(
                task=self.tasks[0],
                status=RpaTask.Status.WAITING_HUMAN,
                result={},
                error_code="external_result_uncertain",
                error_message="发送结果待人工核查，禁止自动重试",
            )

        self.assertEqual(HumanAttention.objects.count(), 1)
        attention = HumanAttention.objects.get()
        response = self.client.post(
            f"/api/recruitment/human-attentions/{attention.pk}/resolve/",
            data={"note": "已在平台人工核查"},
            content_type="application/json",
        )

        attention.refresh_from_db()
        self.tasks[0].refresh_from_db()
        action = ConversationAction.objects.get(
            pk=self.tasks[0].request_payload["conversation_action_id"]
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(attention.status, HumanAttention.Status.RESOLVED)
        self.assertEqual(self.tasks[0].status, RpaTask.Status.WAITING_HUMAN)
        self.assertEqual(self.tasks[0].error_code, "external_result_uncertain")
        self.assertEqual(action.status, ConversationAction.Status.WAITING_HUMAN)
        self.assertEqual(action.error_code, "external_result_uncertain")
        self.assertEqual(self.applications[0].stage, JobApplication.Stage.NEW)


class RejectionNoticeWorkerTests(SimpleTestCase):
    def test_name_based_adapter_is_never_used(self):
        class NameOnlyRunner:
            def __init__(self):
                self.calls = []

            def conversations(self, account):
                return "1. 候选人｜测试工程师｜external_id:stable-1"

            def send_text(self, account, name, message):
                self.calls.append((name, message))

        runner = NameOnlyRunner()
        outcome = execute_rejection_notice(
            {
                "request_payload": {
                    "message": "感谢关注",
                    "target": {"name": "候选人", "external_id": "stable-1"},
                }
            },
            CliAccountConfig("edge.exe", "profile", 53470),
            runner,
        )
        self.assertEqual(outcome["status"], "waiting_human")
        self.assertEqual(outcome["error_code"], "stable_identity_action_unavailable")
        self.assertEqual(runner.calls, [])

    def test_adapter_exception_after_send_boundary_is_external_result_uncertain(self):
        class UncertainRunner:
            def __init__(self):
                self.sent = []

            def conversations(self, account):
                return "1. 候选人｜测试工程师｜external_id:stable-1"

            def send_text_by_external_id(self, account, external_id, message):
                self.sent.append((external_id, message))
                raise RuntimeError("response lost after platform accepted message")

        runner = UncertainRunner()
        outcome = execute_rejection_notice(
            {
                "request_payload": {
                    "message": "感谢关注",
                    "target": {"name": "候选人", "external_id": "stable-1"},
                }
            },
            CliAccountConfig("edge.exe", "profile", 53470),
            runner,
        )

        self.assertEqual(runner.sent, [("stable-1", "感谢关注")])
        self.assertEqual(outcome["status"], "waiting_human")
        self.assertEqual(outcome["error_code"], "external_result_uncertain")
        self.assertEqual(outcome["error_message"], "平台可能已接收通知，发送结果待人工核查，禁止自动重试")

    def test_negative_or_unknown_adapter_receipt_is_never_succeeded(self):
        class ReceiptRunner:
            def __init__(self, receipt):
                self.receipt = receipt

            def conversations(self, account):
                return "1. 候选人｜测试工程师｜external_id:stable-1"

            def send_text_by_external_id(self, account, external_id, message):
                return self.receipt

        for receipt in [False, None, {"sent": False}, {"sent": True}, {
            "sent": True,
            "verified": True,
            "observed_external_id": "another-candidate",
        }]:
            with self.subTest(receipt=receipt):
                outcome = execute_rejection_notice(
                    {
                        "request_payload": {
                            "message": "感谢关注",
                            "target": {"name": "候选人", "external_id": "stable-1"},
                        }
                    },
                    CliAccountConfig("edge.exe", "profile", 53470),
                    ReceiptRunner(receipt),
                )
                self.assertEqual(outcome["status"], "waiting_human")
                self.assertEqual(outcome["error_code"], "external_result_uncertain")

    def test_explicit_atomic_adapter_receipt_is_succeeded(self):
        class ReceiptRunner:
            def conversations(self, account):
                return "1. 候选人｜测试工程师｜external_id:stable-1"

            def send_text_by_external_id(self, account, external_id, message):
                return {
                    "sent": True,
                    "verified": True,
                    "observed_external_id": external_id,
                }

        outcome = execute_rejection_notice(
            {
                "request_payload": {
                    "message": "感谢关注",
                    "target": {"name": "候选人", "external_id": "stable-1"},
                }
            },
            CliAccountConfig("edge.exe", "profile", 53470),
            ReceiptRunner(),
        )

        self.assertEqual(outcome["status"], "succeeded")
        self.assertTrue(outcome["result"]["verified"])

    @patch("recruitment.management.commands.run_rpa_worker.ProfileLock", side_effect=lambda *_: nullcontext())
    @patch("recruitment.management.commands.run_rpa_worker.managed_cdp_matches", return_value=True)
    @patch(
        "recruitment.management.commands.run_rpa_worker.inspect_boss_status",
        return_value=SimpleNamespace(login_status="ready"),
    )
    def test_worker_engine_never_persists_raw_rejection_exception(self, _status, _managed, _lock):
        class FailingRunner:
            def conversations(self, account):
                raise RuntimeError("RAW_EXCEPTION_SECRET candidate=stable-1")

        class RecordingApi:
            def __init__(self):
                self.completed = None

            def event(self, task_id, payload):
                return None

            def complete(self, task_id, outcome):
                self.completed = outcome

        api = RecordingApi()
        task = {
            "id": str(uuid.uuid4()),
            "action": "rejection_notice",
            "lease_token": str(uuid.uuid4()),
            "lease_generation": 1,
            "request_payload": {
                "message": "感谢关注",
                "target": {"name": "候选人", "external_id": "stable-1"},
            },
            "browser": {
                "executable": "edge.exe",
                "user_data_dir": "profile",
                "cdp_port": 53470,
            },
        }

        outcome = WorkerEngine(api, FailingRunner(), "worker-test").execute_task(task)

        self.assertEqual(outcome["status"], "waiting_human")
        self.assertEqual(outcome["error_code"], "external_result_uncertain")
        self.assertNotIn("RAW_EXCEPTION_SECRET", str(outcome))
        self.assertNotIn("stable-1", str(api.completed))
