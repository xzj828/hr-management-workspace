from datetime import timedelta
import uuid

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone

from attendance.models import AccountProfile
from recruitment.models import (
    BossAccount,
    Candidate,
    CandidateDiscovery,
    CandidateExternalIdentity,
    JobApplication,
    MessageSyncPolicy,
    RecruitmentAutomationPlan,
    RecruitmentAutomationPlanRevision,
    RecruitmentJob,
    RpaTask,
    RpaWorker,
    WorkflowTemplate,
    WorkflowVersion,
)
from recruitment.services.message_scheduling import schedule_due_conversation_syncs


class MessageSchedulingTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("sync-scheduler")
        AccountProfile.objects.create(user=self.user, role=AccountProfile.Role.HR)
        self.account = BossAccount.objects.create(name="Sync account", browser_profile="sync-policy", cdp_port=53989)
        self.account.authorized_users.add(self.user)
        self.worker = RpaWorker.objects.create(
            key="message-scheduling-worker",
            hostname="localhost",
            status=RpaWorker.Status.ONLINE,
            last_seen_at=timezone.now(),
            capabilities={"boss_cli": True},
        )

    def create_running_passive_plan(self):
        job = RecruitmentJob.objects.create(
            boss_account=self.account,
            external_id=f"scheduler-job-{uuid.uuid4()}",
            title="消息同步职位",
            owner=self.user,
        )
        template = WorkflowTemplate.objects.create(name="scheduler-plan", created_by=self.user)
        version = WorkflowVersion.objects.create(
            template=template,
            version=1,
            status=WorkflowVersion.Status.ENABLED,
            boss_account=self.account,
            created_by=self.user,
        )
        plan = RecruitmentAutomationPlan.objects.create(
            job=job,
            kind=RecruitmentAutomationPlan.Kind.PASSIVE_RESUME,
            desired_state=RecruitmentAutomationPlan.DesiredState.RUNNING,
            control_generation=1,
            control_version=1,
            created_by=self.user,
        )
        revision = RecruitmentAutomationPlanRevision.objects.create(
            plan=plan,
            revision=1,
            kind=plan.kind,
            request_id=uuid.uuid4(),
            request_hash="a" * 64,
            config_snapshot={"interval_minutes": 5},
            workflow_version=version,
            created_by=self.user,
        )
        plan.current_revision = revision
        plan.save(update_fields=["current_revision", "updated_at"])
        return plan

    def test_due_policy_queues_once_and_respects_interval(self):
        now = timezone.now()
        self.create_running_passive_plan()
        policy = MessageSyncPolicy.objects.create(boss_account=self.account, interval_minutes=5)
        MessageSyncPolicy.objects.filter(pk=policy.pk).update(last_scheduled_at=now - timedelta(minutes=6))

        first = schedule_due_conversation_syncs(now=now)
        second = schedule_due_conversation_syncs(now=now + timedelta(minutes=1))

        self.assertEqual(len(first), 1)
        self.assertEqual(second, [])
        self.assertEqual(RpaTask.objects.get().action, RpaTask.Action.SYNC_CONVERSATIONS)
        self.assertTrue(RpaTask.objects.get().request_payload["scheduled"])

    def test_due_policy_rechecks_stable_waiting_resume_application(self):
        now = timezone.now()
        plan = self.create_running_passive_plan()
        candidate = Candidate.objects.create(identity_key="waiting-resume", name="同名候选人")
        JobApplication.objects.create(
            candidate=candidate,
            job=plan.job,
            source="boss",
            stage=JobApplication.Stage.WAITING_RESUME,
        )
        CandidateExternalIdentity.objects.create(
            boss_account=self.account,
            candidate=candidate,
            external_id="stable-waiting-resume",
            fingerprint="f" * 64,
            identity_quality=CandidateDiscovery.IdentityQuality.PLATFORM,
        )
        policy = MessageSyncPolicy.objects.create(boss_account=self.account, interval_minutes=5)
        MessageSyncPolicy.objects.filter(pk=policy.pk).update(last_scheduled_at=now - timedelta(minutes=6))

        [task] = schedule_due_conversation_syncs(now=now)

        scope = task.request_payload["passive_plan_scopes"][str(plan.job_id)]
        self.assertEqual(scope["recheck_external_ids"], ["stable-waiting-resume"])

    def test_due_policy_is_left_due_when_runtime_is_offline(self):
        now = timezone.now()
        self.worker.delete()
        self.create_running_passive_plan()
        policy = MessageSyncPolicy.objects.create(boss_account=self.account, interval_minutes=5)
        MessageSyncPolicy.objects.filter(pk=policy.pk).update(last_scheduled_at=now - timedelta(minutes=6))

        scheduled = schedule_due_conversation_syncs(now=now)

        policy.refresh_from_db()
        self.assertEqual(scheduled, [])
        self.assertEqual(RpaTask.objects.count(), 0)
        self.assertEqual(policy.last_scheduled_at, now - timedelta(minutes=6))
