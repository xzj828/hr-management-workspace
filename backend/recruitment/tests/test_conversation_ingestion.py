from datetime import timedelta

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone

from recruitment.models import (
    AutomationApproval,
    BossAccount,
    Candidate,
    ConversationAction,
    ConversationMessage,
    HumanAttention,
    JobApplication,
    RecruitmentJob,
    Resume,
)
from recruitment.services.conversation_ingestion import ingest_conversation, process_pending_messages
from recruitment.services.message_intent import MessageIntent


class ConversationIngestionTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_superuser("message-ingestion")
        self.account = BossAccount.objects.create(
            name="Message ingestion",
            browser_profile="message-ingestion",
            cdp_port=53996,
        )
        self.job = RecruitmentJob.objects.create(
            boss_account=self.account,
            external_id="message-job",
            title="后端工程师",
            owner=self.user,
        )
        candidate = Candidate.objects.create(
            identity_key="message-candidate",
            external_id="boss-message-candidate",
            name="林然",
        )
        self.application = JobApplication.objects.create(candidate=candidate, job=self.job, source="boss")

    def _request_action(self, *, status, application=None, approval_status=None, suffix="existing"):
        application = application or self.application
        approval = AutomationApproval.objects.create(
            idempotency_key=f"approval-{suffix}",
            action=AutomationApproval.Action.REQUEST_RESUME,
            boss_account=self.account,
            created_by=self.user,
            status=approval_status or (
                AutomationApproval.Status.DRAFT
                if status == ConversationAction.Status.DRAFT
                else AutomationApproval.Status.APPROVED
            ),
            expires_at=timezone.now() + timedelta(minutes=30),
        )
        return ConversationAction.objects.create(
            application=application,
            boss_account=self.account,
            action=ConversationAction.Action.REQUEST_RESUME,
            status=status,
            message_snapshot="您好，方便发送一份简历吗？",
            target_snapshot={"external_id": application.candidate.external_id},
            idempotency_key=f"request-{suffix}",
            approval=approval,
            created_by=self.user,
        )

    def _process_with_callbacks(self, *, application=None, create_attentions=True):
        with self.captureOnCommitCallbacks(execute=True):
            return process_pending_messages(
                application=application or self.application,
                account=self.account,
                actor=self.user,
                schedule_actions=True,
                create_attentions=create_attentions,
            )

    def test_first_import_saves_every_message_and_older_resume_attachment(self):
        result = ingest_conversation(
            application=self.application,
            account=self.account,
            cursor="cursor-3",
            messages=[
                {"external_id": "m1", "direction": "candidate", "content": "你好", "sent_at": "2026-08-25T09:00:00+08:00"},
                {
                    "external_id": "m2",
                    "direction": "candidate",
                    "content": "这是我的简历",
                    "sent_at": "2026-08-25T09:01:00+08:00",
                    "attachments": [{"external_id": "a1", "filename": "林然简历.pdf", "content_type": "application/pdf"}],
                },
                {"external_id": "m3", "direction": "hr", "content": "已收到", "sent_at": "2026-08-25T09:02:00+08:00"},
            ],
        )

        self.assertEqual(result.created_messages, 3)
        self.assertEqual(result.created_attachments, 1)
        state = self.application.conversation_state
        self.assertEqual(state.cursor, "cursor-3")
        self.assertEqual(state.messages.count(), 3)
        self.assertEqual(state.messages.get(external_id="m2").attachments.get().original_name, "林然简历.pdf")

    def test_incremental_import_deduplicates_existing_messages(self):
        first = [
            {"external_id": "m1", "direction": "candidate", "content": "你好", "sent_at": "2026-08-25T09:00:00+08:00"},
        ]
        ingest_conversation(application=self.application, account=self.account, cursor="m1", messages=first)
        result = ingest_conversation(
            application=self.application,
            account=self.account,
            cursor="m2",
            messages=first + [
                {"external_id": "m2", "direction": "candidate", "content": "还在吗", "sent_at": "2026-08-25T09:03:00+08:00"},
            ],
        )

        self.assertEqual(result.created_messages, 1)
        self.assertEqual(ConversationMessage.objects.count(), 2)
        self.assertEqual(self.application.conversation_state.cursor, "m2")

    def test_processes_latest_candidate_intent_and_creates_observation_attention(self):
        ingest_conversation(
            application=self.application,
            account=self.account,
            messages=[
                {"external_id": "m1", "direction": "candidate", "content": "你好", "sent_at": "2026-08-25T09:00:00+08:00"},
                {"external_id": "m2", "direction": "candidate", "content": "我想先了解一下公司", "sent_at": "2026-08-25T09:01:00+08:00"},
            ],
        )

        decision = process_pending_messages(application=self.application, account=self.account)

        self.assertEqual(decision.intent, MessageIntent.OBSERVING)
        self.assertIsNotNone(decision.attention)
        self.assertEqual(self.application.human_attentions.count(), 1)
        self.assertFalse(ConversationMessage.objects.filter(processed_at__isnull=True).exists())

    def test_resume_attachment_suppresses_request_resume_decision(self):
        ingest_conversation(
            application=self.application,
            account=self.account,
            messages=[
                {
                    "external_id": "m1",
                    "direction": "candidate",
                    "content": "这是我的简历",
                    "sent_at": "2026-08-25T09:00:00+08:00",
                    "attachments": [{"filename": "resume.pdf", "content_type": "application/pdf"}],
                }
            ],
        )

        decision = process_pending_messages(application=self.application, account=self.account)

        self.assertEqual(decision.intent, MessageIntent.RESUME_RECEIVED)

    def test_first_candidate_greeting_creates_one_first_contact_request(self):
        ingest_conversation(
            application=self.application,
            account=self.account,
            messages=[
                {"external_id": "m1", "direction": "candidate", "content": "你好", "sent_at": "2026-08-25T09:01:00+08:00"},
            ],
        )

        decision = self._process_with_callbacks()

        self.assertEqual(decision.intent, MessageIntent.REQUEST_RESUME)
        action = self.application.conversation_actions.get(action=ConversationAction.Action.REQUEST_RESUME)
        self.assertTrue(action.approval.payload["items"][0]["first_contact"])
        self.assertEqual(self.application.conversation_actions.count(), 1)

    def test_existing_hr_greeting_still_creates_native_only_request(self):
        ingest_conversation(
            application=self.application,
            account=self.account,
            messages=[
                {"external_id": "h1", "direction": "hr", "content": "您好，想和您聊聊", "sent_at": "2026-08-25T09:00:00+08:00"},
                {"external_id": "m1", "direction": "candidate", "content": "你好", "sent_at": "2026-08-25T09:01:00+08:00"},
            ],
        )

        decision = self._process_with_callbacks()

        self.assertEqual(decision.intent, MessageIntent.REQUEST_RESUME)
        action = self.application.conversation_actions.get(action=ConversationAction.Action.REQUEST_RESUME)
        self.assertFalse(action.approval.payload["items"][0]["first_contact"])
        self.assertFalse(self.application.human_attentions.exists())

    def test_successful_greet_action_makes_first_resume_request_native_only(self):
        ConversationAction.objects.create(
            application=self.application,
            boss_account=self.account,
            action=ConversationAction.Action.GREET,
            status=ConversationAction.Status.SUCCEEDED,
            message_snapshot="您好，想和您聊聊",
            target_snapshot={"external_id": self.application.candidate.external_id},
            idempotency_key="verified-greeting",
            created_by=self.user,
        )
        ingest_conversation(
            application=self.application,
            account=self.account,
            messages=[{"external_id": "m1", "direction": "candidate", "content": "你好"}],
        )

        self._process_with_callbacks()

        request_action = self.application.conversation_actions.get(
            action=ConversationAction.Action.REQUEST_RESUME
        )
        self.assertFalse(request_action.approval.payload["items"][0]["first_contact"])

    def test_same_message_reprocessing_does_not_duplicate_request_or_attention(self):
        message = {"external_id": "m1", "direction": "candidate", "content": "你好"}
        ingest_conversation(application=self.application, account=self.account, messages=[message])
        self._process_with_callbacks()

        duplicate = ingest_conversation(
            application=self.application,
            account=self.account,
            messages=[message],
        )
        self._process_with_callbacks()

        self.assertEqual(duplicate.created_messages, 0)
        self.assertEqual(
            self.application.conversation_actions.filter(
                action=ConversationAction.Action.REQUEST_RESUME
            ).count(),
            1,
        )
        self.assertFalse(self.application.human_attentions.exists())

    def test_new_message_does_not_duplicate_existing_request_resume_attempt(self):
        for index, status in enumerate([
            ConversationAction.Status.DRAFT,
            ConversationAction.Status.APPROVED,
            ConversationAction.Status.PENDING,
            ConversationAction.Status.RUNNING,
            ConversationAction.Status.FAILED,
            ConversationAction.Status.CANCELLED,
        ]):
            with self.subTest(status=status):
                candidate = Candidate.objects.create(
                    identity_key=f"active-candidate-{index}",
                    external_id=f"boss-active-{index}",
                    name=f"候选人{index}",
                )
                application = JobApplication.objects.create(
                    candidate=candidate,
                    job=self.job,
                    source="boss",
                )
                self._request_action(status=status, application=application, suffix=f"active-{index}")
                ingest_conversation(
                    application=application,
                    account=self.account,
                    messages=[{"external_id": f"m-{index}", "direction": "candidate", "content": "你好"}],
                )

                self._process_with_callbacks(application=application)

                self.assertEqual(application.conversation_actions.count(), 1)
                self.assertFalse(application.human_attentions.exists())

    def test_succeeded_request_follow_up_creates_one_idempotent_attention(self):
        action = self._request_action(status=ConversationAction.Status.SUCCEEDED)
        ingest_conversation(
            application=self.application,
            account=self.account,
            messages=[{"external_id": "m1", "direction": "candidate", "content": "你好"}],
        )
        first = self._process_with_callbacks()
        ingest_conversation(
            application=self.application,
            account=self.account,
            messages=[{"external_id": "m2", "direction": "candidate", "content": "还在吗"}],
        )
        second = self._process_with_callbacks()

        self.assertEqual(first.intent, MessageIntent.IGNORE)
        self.assertEqual(second.intent, MessageIntent.IGNORE)
        attention = self.application.human_attentions.get()
        self.assertEqual(attention.attention_type, HumanAttention.Type.OTHER)
        self.assertIn("已求过简历", attention.title)
        self.assertEqual(attention.detail["conversation_action_id"], str(action.pk))
        self.assertEqual(self.application.conversation_actions.count(), 1)

    def test_waiting_human_request_is_not_retried_and_keeps_existing_attention(self):
        action = self._request_action(status=ConversationAction.Status.WAITING_HUMAN)
        HumanAttention.objects.create(
            attention_type=HumanAttention.Type.OTHER,
            title="BOSS 沟通发送结果待人工核查",
            idempotency_key=f"communication-result-uncertain:{action.pk}",
            application=self.application,
            boss_account=self.account,
            job=self.job,
        )
        ingest_conversation(
            application=self.application,
            account=self.account,
            messages=[{"external_id": "m1", "direction": "candidate", "content": "你好"}],
        )

        self._process_with_callbacks()

        self.assertEqual(self.application.conversation_actions.count(), 1)
        self.assertEqual(self.application.human_attentions.count(), 1)

    def test_create_attentions_false_never_creates_hidden_attention(self):
        self._request_action(status=ConversationAction.Status.SUCCEEDED)
        ingest_conversation(
            application=self.application,
            account=self.account,
            messages=[{"external_id": "m1", "direction": "candidate", "content": "你好"}],
        )

        self._process_with_callbacks(create_attentions=False)

        self.assertFalse(self.application.human_attentions.exists())
        self.assertEqual(self.application.conversation_actions.count(), 1)

    def test_existing_resume_prevents_request_resume_action(self):
        Resume.objects.create(
            candidate=self.application.candidate,
            application=self.application,
            original_name="resume.pdf",
            file="recruitment/resumes/test-resume.pdf",
            file_size=12,
            sha256="a" * 64,
            version=1,
        )
        ingest_conversation(
            application=self.application,
            account=self.account,
            messages=[{"external_id": "m1", "direction": "candidate", "content": "你好"}],
        )

        decision = self._process_with_callbacks()

        self.assertEqual(decision.intent, MessageIntent.RESUME_RECEIVED)
        self.assertFalse(self.application.conversation_actions.exists())
