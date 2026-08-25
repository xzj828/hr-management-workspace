from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.utils import timezone

from recruitment.models import (
    BossAccount,
    ConversationMessage,
    ConversationSyncState,
    HumanAttention,
    JobApplication,
    JobRequirementDocument,
    JobRequirementDocumentVersion,
    MessageSyncPolicy,
    RecruitmentJob,
    SearchCampaign,
    Candidate,
)


class RecruitmentAutomationPhaseModelTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="phase-owner", password="secret")
        self.account = BossAccount.objects.create(
            name="Phase account",
            browser_profile="phase-account",
            cdp_port=53991,
        )
        self.account.authorized_users.add(self.user)
        self.job = RecruitmentJob.objects.create(
            boss_account=self.account,
            external_id="job-phase-1",
            title="产品经理",
            owner=self.user,
        )
        candidate = Candidate.objects.create(identity_key="phase-candidate", name="林然")
        self.application = JobApplication.objects.create(
            candidate=candidate,
            job=self.job,
            source="boss",
        )

    def test_job_document_keeps_ordered_versions_and_current_version(self):
        document = JobRequirementDocument.objects.create(
            job=self.job,
            category=JobRequirementDocument.Category.PERSONA,
            title="产品经理画像",
            created_by=self.user,
        )
        first = JobRequirementDocumentVersion.objects.create(
            document=document,
            version=1,
            original_name="画像-v1.docx",
            file="recruitment/job-documents/v1.docx",
            file_size=12,
            sha256="a" * 64,
            uploaded_by=self.user,
        )
        second = JobRequirementDocumentVersion.objects.create(
            document=document,
            version=2,
            original_name="画像-v2.docx",
            file="recruitment/job-documents/v2.docx",
            file_size=15,
            sha256="b" * 64,
            uploaded_by=self.user,
        )
        document.current_version = second
        document.save(update_fields=["current_version"])

        self.assertEqual(list(document.versions.values_list("version", flat=True)), [2, 1])
        self.assertEqual(document.current_version, second)
        self.assertNotEqual(document.current_version, first)

    def test_message_sync_policy_rejects_intervals_outside_one_day(self):
        for interval in (0, 1441):
            policy = MessageSyncPolicy(boss_account=self.account, interval_minutes=interval)
            with self.assertRaises(ValidationError):
                policy.full_clean()

        for interval in (1, 1440):
            policy = MessageSyncPolicy(boss_account=self.account, interval_minutes=interval)
            policy.full_clean()

    def test_conversation_message_deduplicates_external_message_key(self):
        state = ConversationSyncState.objects.create(
            application=self.application,
            boss_account=self.account,
        )
        values = {
            "conversation_state": state,
            "external_id": "message-1",
            "fingerprint": "f" * 64,
            "direction": ConversationMessage.Direction.CANDIDATE,
            "content": "你好",
            "sent_at": timezone.now(),
        }
        ConversationMessage.objects.create(**values)

        with self.assertRaises(IntegrityError), transaction.atomic():
            ConversationMessage.objects.create(**{**values, "fingerprint": "e" * 64})

    def test_human_attention_and_search_campaign_store_business_progress(self):
        attention = HumanAttention.objects.create(
            attention_type=HumanAttention.Type.OBSERVING_CANDIDATE,
            title="候选人希望了解公司",
            idempotency_key="observe:application:1",
            job=self.job,
            application=self.application,
        )
        campaign = SearchCampaign.objects.create(
            name="产品经理主动搜索",
            boss_account=self.account,
            job=self.job,
            source=SearchCampaign.Source.SEARCH,
            target_resume_count=3,
            max_scan_count=20,
            criteria={"keyword": "产品经理"},
            created_by=self.user,
        )
        campaign.scanned_count = 7
        campaign.pulled_resume_count = 3
        campaign.status = SearchCampaign.Status.SUCCEEDED
        campaign.stop_reason = SearchCampaign.StopReason.TARGET_REACHED
        campaign.save()

        self.assertEqual(attention.status, HumanAttention.Status.OPEN)
        self.assertEqual(campaign.pulled_resume_count, campaign.target_resume_count)
        self.assertEqual(campaign.stop_reason, SearchCampaign.StopReason.TARGET_REACHED)
