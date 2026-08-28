from django.contrib.auth.models import User
from django.test import TestCase

from recruitment.models import (
    BossAccount,
    Candidate,
    ConversationAction,
    ConversationMessage,
    HumanAttention,
    JobApplication,
    RecruitmentJob,
)
from recruitment.services.conversation_ingestion import ingest_conversation, process_pending_messages
from recruitment.services.message_intent import MessageIntent


class ConversationIngestionTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("message-ingestion")
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
        candidate = Candidate.objects.create(identity_key="message-candidate", name="林然")
        self.application = JobApplication.objects.create(candidate=candidate, job=self.job, source="boss")

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

    def test_unread_reply_after_synced_hr_greeting_creates_manual_attention(self):
        ingest_conversation(
            application=self.application,
            account=self.account,
            messages=[
                {"external_id": "h1", "direction": "hr", "content": "您好，想和您聊聊", "sent_at": "2026-08-25T09:00:00+08:00"},
                {"external_id": "m1", "direction": "candidate", "content": "你好", "sent_at": "2026-08-25T09:01:00+08:00"},
            ],
        )

        decision = process_pending_messages(
            application=self.application,
            account=self.account,
            actor=self.user,
            schedule_actions=True,
        )

        self.assertEqual(decision.intent, MessageIntent.IGNORE)
        attention = self.application.human_attentions.get()
        self.assertEqual(attention.attention_type, HumanAttention.Type.OTHER)
        self.assertEqual(attention.detail["message_id"], decision.message.pk)
        self.assertFalse(self.application.conversation_actions.exists())

    def test_unread_reply_after_verified_greet_action_creates_manual_attention(self):
        ConversationAction.objects.create(
            application=self.application,
            boss_account=self.account,
            action=ConversationAction.Action.GREET,
            status=ConversationAction.Status.SUCCEEDED,
            message_snapshot="您好，想和您聊聊",
            target_snapshot={},
            idempotency_key="verified-greeting",
            created_by=self.user,
        )
        ingest_conversation(
            application=self.application,
            account=self.account,
            messages=[
                {"external_id": "m1", "direction": "candidate", "content": "你好", "sent_at": "2026-08-25T09:01:00+08:00"},
            ],
        )

        decision = process_pending_messages(application=self.application, account=self.account)

        self.assertEqual(decision.intent, MessageIntent.IGNORE)
        self.assertEqual(self.application.human_attentions.get().attention_type, HumanAttention.Type.OTHER)
