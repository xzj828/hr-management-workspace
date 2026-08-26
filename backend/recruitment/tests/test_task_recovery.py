from datetime import timedelta
import uuid

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone

from attendance.models import AccountProfile
from recruitment.models import (
    AutomationApproval,
    AutomationEvidence,
    BossAccount,
    Candidate,
    ConversationAction,
    ExecutionBatch,
    JobApplication,
    RecruitmentAutomationPlan,
    RecruitmentAutomationPlanRevision,
    RecruitmentJob,
    RpaTask,
    RpaWorker,
    SearchCampaign,
    WorkflowNodeRun,
    WorkflowRun,
    WorkflowTemplate,
    WorkflowVersion,
)
from recruitment.services.search_campaigns import _campaign_snapshot
from recruitment.services.task_recovery import recover_stale_tasks


class TaskRecoveryTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(username="recovery-owner")
        self.account = BossAccount.objects.create(
            name="失联任务账号",
            browser_profile="recovery-profile",
            cdp_port=53520,
            login_status=BossAccount.LoginStatus.READY,
            status=BossAccount.Status.RUNNING,
        )
        self.worker = RpaWorker.objects.create(key="lost-worker", hostname="LOST")

    def test_expired_running_task_fails_and_account_returns_to_login_state(self):
        task = RpaTask.objects.create(
            boss_account=self.account,
            action=RpaTask.Action.CHECK_STATUS,
            status=RpaTask.Status.RUNNING,
            created_by=self.owner,
            worker=self.worker,
            lease_expires_at=timezone.now() - timedelta(seconds=1),
            started_at=timezone.now() - timedelta(minutes=10),
        )

        result = recover_stale_tasks()

        task.refresh_from_db()
        self.account.refresh_from_db()
        self.assertEqual(result.failed_running, 1)
        self.assertEqual(task.status, RpaTask.Status.FAILED)
        self.assertEqual(task.error_code, "worker_lease_expired")
        self.assertIsNotNone(task.completed_at)
        self.assertIsNone(task.worker)
        self.assertIsNone(task.lease_expires_at)
        self.assertEqual(self.account.status, BossAccount.Status.READY)
        self.assertTrue(task.events.filter(event="worker_lease_expired").exists())

    def test_expired_lease_is_requeued_without_losing_audit_history(self):
        task = RpaTask.objects.create(
            boss_account=self.account,
            action=RpaTask.Action.CHECK_STATUS,
            status=RpaTask.Status.LEASED,
            created_by=self.owner,
            worker=self.worker,
            lease_expires_at=timezone.now() - timedelta(seconds=1),
        )

        result = recover_stale_tasks()

        task.refresh_from_db()
        self.account.refresh_from_db()
        self.assertEqual(result.requeued_leases, 1)
        self.assertEqual(task.status, RpaTask.Status.PENDING)
        self.assertIsNone(task.worker)
        self.assertIsNone(task.lease_expires_at)
        self.assertEqual(self.account.status, BossAccount.Status.READY)
        self.assertTrue(task.events.filter(event="lease_expired").exists())

    def test_expired_running_plan_communication_becomes_uncertain_and_stops_remaining_batch(self):
        AccountProfile.objects.create(user=self.owner, role=AccountProfile.Role.HR)
        self.account.authorized_users.add(self.owner)
        job = RecruitmentJob.objects.create(
            boss_account=self.account,
            external_id="stale-plan-communication",
            title="沟通恢复测试",
            owner=self.owner,
        )
        template = WorkflowTemplate.objects.create(name="plan communication", created_by=self.owner)
        version = WorkflowVersion.objects.create(
            template=template,
            version=1,
            boss_account=self.account,
            created_by=self.owner,
            status=WorkflowVersion.Status.ENABLED,
        )
        plan = RecruitmentAutomationPlan.objects.create(
            job=job,
            kind=RecruitmentAutomationPlan.Kind.PASSIVE_RESUME,
            desired_state=RecruitmentAutomationPlan.DesiredState.RUNNING,
            control_version=1,
            control_generation=1,
            created_by=self.owner,
        )
        revision = RecruitmentAutomationPlanRevision.objects.create(
            plan=plan,
            revision=1,
            kind=plan.kind,
            request_id=uuid.uuid4(),
            request_hash="a" * 64,
            config_snapshot={},
            workflow_version=version,
            created_by=self.owner,
        )
        plan.current_revision = revision
        plan.save(update_fields=["current_revision", "updated_at"])
        applications = []
        for index in range(2):
            candidate = Candidate.objects.create(
                identity_key=f"stale-plan-communication-{index}",
                name=f"沟通候选人{index}",
                external_id=f"boss-communication-{index}",
            )
            applications.append(JobApplication.objects.create(
                candidate=candidate, job=job, source="boss"
            ))
        from recruitment.services.approvals import approve
        from recruitment.services.communications import materialize_communication_batch, prepare_communication

        approval = prepare_communication(
            account=self.account,
            applications=applications,
            action=ConversationAction.Action.REQUEST_RESUME,
            message="方便发送一份简历吗？",
            actor=self.owner,
            request_id="stale-plan-communication",
            automation_plan_revision=revision,
            automation_generation=1,
        )
        approve(approval=approval, actor=self.owner)
        batch = materialize_communication_batch(approval=approval, actor=self.owner)
        task = batch.rpa_tasks.get()
        task.status = RpaTask.Status.RUNNING
        task.worker = self.worker
        task.lease_expires_at = timezone.now() - timedelta(seconds=1)
        task.started_at = timezone.now() - timedelta(minutes=5)
        task.save(update_fields=[
            "status", "worker", "lease_expires_at", "started_at", "updated_at",
        ])

        result = recover_stale_tasks()

        task.refresh_from_db()
        batch.refresh_from_db()
        current_action = batch.conversation_actions.get(
            pk=task.request_payload["conversation_action_id"]
        )
        remaining_action = batch.conversation_actions.exclude(pk=current_action.pk).get()
        self.assertEqual(result.failed_running, 1)
        self.assertEqual(task.status, RpaTask.Status.WAITING_HUMAN)
        self.assertEqual(task.error_code, "external_result_uncertain")
        self.assertEqual(current_action.status, ConversationAction.Status.WAITING_HUMAN)
        self.assertEqual(remaining_action.status, ConversationAction.Status.CANCELLED)
        self.assertEqual(batch.status, ExecutionBatch.Status.WAITING_HUMAN)
        self.assertFalse(batch.rpa_tasks.filter(status=RpaTask.Status.PENDING).exists())

    def _assert_stale_search_pull_is_closed(self, task_status):
        job = RecruitmentJob.objects.create(
            boss_account=self.account,
            external_id=f"stale-search-{task_status}",
            title="主动寻访恢复测试",
            owner=self.owner,
        )
        template = WorkflowTemplate.objects.create(name=f"stale-{task_status}", created_by=self.owner)
        version = WorkflowVersion.objects.create(
            template=template,
            version=1,
            boss_account=self.account,
            created_by=self.owner,
        )
        run = WorkflowRun.objects.create(
            version=version,
            boss_account=self.account,
            job=job,
            actor=self.owner,
            mode=WorkflowRun.Mode.FORMAL,
            status=WorkflowRun.Status.RUNNING,
            idempotency_key=f"stale-run-{task_status}",
            graph_snapshot={
                "nodes": [{"key": "search", "type": "search_and_pull_resumes", "config": {}}],
                "edges": [],
            },
        )
        node = WorkflowNodeRun.objects.create(
            run=run,
            node_key="search",
            node_type="search_and_pull_resumes",
            status=WorkflowNodeRun.Status.RUNNING,
            idempotency_key=f"stale-node-{task_status}",
        )
        campaign = SearchCampaign.objects.create(
            name=f"过期主动寻访-{task_status}",
            boss_account=self.account,
            job=job,
            workflow_run=run,
            source="search",
            status=SearchCampaign.Status.RUNNING,
            target_resume_count=1,
            max_scan_count=3,
            criteria={"keyword": "安全"},
            created_by=self.owner,
        )
        payload = _campaign_snapshot(campaign, workflow_node_run_id=node.pk)
        approval = AutomationApproval.objects.create(
            action=AutomationApproval.Action.SEARCH_AND_PULL_RESUMES,
            boss_account=self.account,
            created_by=self.owner,
            approved_by=self.owner,
            status=AutomationApproval.Status.APPROVED,
            payload=payload,
            item_count=payload["resume_view_budget"],
        )
        task = RpaTask.objects.create(
            boss_account=self.account,
            action=RpaTask.Action.SEARCH_AND_PULL_RESUMES,
            status=task_status,
            created_by=self.owner,
            worker=self.worker,
            approval=approval,
            workflow_node_run=node,
            request_payload=payload,
            idempotency_key=f"search-campaign:{campaign.pk}:approval:{approval.pk}",
            lease_expires_at=timezone.now() - timedelta(seconds=1),
            started_at=timezone.now() - timedelta(minutes=10),
        )

        with self.captureOnCommitCallbacks(execute=True):
            result = recover_stale_tasks()

        task.refresh_from_db()
        campaign.refresh_from_db()
        node.refresh_from_db()
        run.refresh_from_db()
        self.account.refresh_from_db()
        self.assertEqual(result.failed_running, 1)
        self.assertEqual(task.status, RpaTask.Status.FAILED)
        self.assertEqual(task.error_code, "worker_lease_expired")
        self.assertIsNone(task.worker)
        self.assertIsNone(task.lease_expires_at)
        self.assertEqual(campaign.status, SearchCampaign.Status.FAILED)
        self.assertEqual(campaign.stop_reason, SearchCampaign.StopReason.ERROR)
        self.assertEqual(node.status, WorkflowNodeRun.Status.FAILED)
        self.assertEqual(run.status, WorkflowRun.Status.FAILED)
        self.assertEqual(self.account.status, BossAccount.Status.READY)
        attempts = AutomationEvidence.objects.get(task=task, kind="resume_preview_attempts")
        usage = AutomationEvidence.objects.get(task=task, kind="resume_view_usage")
        self.assertEqual(attempts.metadata["attempts"], [])
        self.assertTrue(attempts.metadata["evidence_untrusted"])
        self.assertFalse(usage.metadata["actual_known"])
        self.assertIsNone(usage.metadata["actual"])
        self.assertIsNone(usage.metadata["unused"])
        self.assertEqual(usage.metadata["reserved"], 3)
        self.assertEqual(usage.metadata["unused_disposition"], "retained_no_refund")
        self.assertEqual(usage.metadata["failure_code"], "worker_lease_expired")

        event_count = task.events.count()
        evidence_count = AutomationEvidence.objects.filter(task=task).count()
        with self.captureOnCommitCallbacks(execute=True):
            replay = recover_stale_tasks()
        self.assertEqual(replay.failed_running, 0)
        self.assertEqual(task.events.count(), event_count)
        self.assertEqual(AutomationEvidence.objects.filter(task=task).count(), evidence_count)

    def test_expired_leased_search_pull_closes_domain_state_instead_of_requeueing(self):
        self._assert_stale_search_pull_is_closed(RpaTask.Status.LEASED)

    def test_expired_running_search_pull_closes_domain_state_and_workflow(self):
        self._assert_stale_search_pull_is_closed(RpaTask.Status.RUNNING)
