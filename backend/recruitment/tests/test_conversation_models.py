from django.contrib.auth.models import User
from django.db import IntegrityError, transaction
from django.test import TestCase

from recruitment.models import (
    ApplicationStageHistory,
    BossAccount,
    Candidate,
    ConversationAction,
    ConversationSyncState,
    InterviewInvitation,
    JobApplication,
    RecruitmentJob,
    Resume,
    WorkflowEdge,
    WorkflowNode,
    WorkflowTemplate,
    WorkflowVersion,
)


class ConversationDomainModelTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("hr-models")
        self.account = BossAccount.objects.create(
            name="主账号", browser_profile="model-profile", cdp_port=53521
        )
        self.account.authorized_users.add(self.user)
        self.job = RecruitmentJob.objects.create(
            boss_account=self.account,
            external_id="job-models",
            title="测试工程师",
            owner=self.user,
        )
        self.candidate = Candidate.objects.create(identity_key="model-candidate", name="林然")
        self.application = JobApplication.objects.create(
            candidate=self.candidate, job=self.job, source="boss", owner=self.user
        )

    def test_conversation_action_keeps_message_and_target_snapshots(self):
        action = ConversationAction.objects.create(
            application=self.application,
            boss_account=self.account,
            action=ConversationAction.Action.GREET,
            message_snapshot="你好，想和你聊聊测试岗位。",
            target_snapshot={"name": "林然", "fingerprint": "fp-1"},
            idempotency_key="greet:model-candidate:1",
            created_by=self.user,
        )
        self.assertEqual(action.status, ConversationAction.Status.DRAFT)
        self.assertEqual(action.target_snapshot["fingerprint"], "fp-1")
        with self.assertRaises(IntegrityError), transaction.atomic():
            ConversationAction.objects.create(
                application=self.application,
                boss_account=self.account,
                action=ConversationAction.Action.GREET,
                message_snapshot="重复",
                idempotency_key="greet:model-candidate:1",
                created_by=self.user,
            )

    def test_interview_invitation_is_structured(self):
        action = ConversationAction.objects.create(
            application=self.application,
            boss_account=self.account,
            action=ConversationAction.Action.SEND_INTERVIEW,
            message_snapshot="面试邀请",
            idempotency_key="interview:model-candidate:1",
            created_by=self.user,
        )
        invitation = InterviewInvitation.objects.create(
            action=action,
            interview_at="2026-08-28T02:00:00Z",
            mode=InterviewInvitation.Mode.ONLINE,
            location="https://meeting.example/room",
            contact_name="HR 小周",
            note="请提前五分钟进入",
        )
        self.assertEqual(invitation.mode, "online")

    def test_resume_hash_and_version_are_unique_per_candidate(self):
        Resume.objects.create(
            candidate=self.candidate,
            application=self.application,
            original_name="resume-v1.pdf",
            file="recruitment/resumes/resume-v1.pdf",
            sha256="a" * 64,
            version=1,
        )
        with self.assertRaises(IntegrityError), transaction.atomic():
            Resume.objects.create(
                candidate=self.candidate,
                application=self.application,
                original_name="same.pdf",
                file="recruitment/resumes/same.pdf",
                sha256="a" * 64,
                version=2,
            )

    def test_sync_stage_history_and_workflow_versions_are_persisted(self):
        state = ConversationSyncState.objects.create(
            application=self.application,
            boss_account=self.account,
            cursor="cursor-1",
            last_message_preview="已发送简历",
            has_candidate_reply=True,
        )
        history = ApplicationStageHistory.objects.create(
            application=self.application,
            from_stage=JobApplication.Stage.NEW,
            to_stage=JobApplication.Stage.COMMUNICATING,
            source=ApplicationStageHistory.Source.AUTOMATION,
            reason="检测到候选人回复",
            actor=self.user,
        )
        template = WorkflowTemplate.objects.create(name="标准招聘", created_by=self.user)
        version = WorkflowVersion.objects.create(template=template, version=1, created_by=self.user)
        source = WorkflowNode.objects.create(
            version=version, node_key="source", node_type="search", position={"x": 30, "y": 50}
        )
        approval = WorkflowNode.objects.create(
            version=version, node_key="approve", node_type="human_approval", position={"x": 240, "y": 50}
        )
        WorkflowEdge.objects.create(version=version, source=source, target=approval)
        self.assertTrue(state.has_candidate_reply)
        self.assertEqual(history.to_stage, JobApplication.Stage.COMMUNICATING)
        self.assertEqual(version.nodes.count(), 2)

