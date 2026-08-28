from django.contrib.auth.models import User
from rest_framework.test import APITestCase

from attendance.models import AccountProfile
from recruitment.models import (
    BossAccount,
    Candidate,
    HumanAttention,
    JobApplication,
    MessageSyncPolicy,
    RecruitmentJob,
)
from recruitment.services.human_attention import ensure_attention


class HumanAttentionApiTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="attention-hr")
        AccountProfile.objects.create(user=self.user, role=AccountProfile.Role.HR)
        self.account = BossAccount.objects.create(
            name="Attention account",
            browser_profile="attention-account",
            cdp_port=53993,
        )
        self.account.authorized_users.add(self.user)
        self.job = RecruitmentJob.objects.create(
            boss_account=self.account,
            external_id="attention-job",
            title="测试工程师",
            owner=self.user,
        )
        candidate = Candidate.objects.create(identity_key="attention-candidate", name="周一")
        self.application = JobApplication.objects.create(candidate=candidate, job=self.job, source="boss")
        self.client.force_login(self.user)

    def test_account_sync_policy_is_a_read_only_plan_projection(self):
        created = self.client.post(
            "/api/recruitment/message-sync-policies/",
            {"boss_account": self.account.pk, "enabled": True, "interval_minutes": 1},
            format="json",
        )
        self.assertEqual(created.status_code, 405, created.data)

        updated = self.client.patch(
            "/api/recruitment/message-sync-policies/1/",
            {"interval_minutes": 1440},
            format="json",
        )
        self.assertEqual(updated.status_code, 405, updated.data)

        invalid = self.client.patch(
            "/api/recruitment/message-sync-policies/1/",
            {"interval_minutes": 1441},
            format="json",
        )
        self.assertEqual(invalid.status_code, 405)
        self.assertFalse(MessageSyncPolicy.objects.exists())

    def test_attention_creation_is_idempotent_and_can_be_resolved(self):
        first, first_created = ensure_attention(
            attention_type=HumanAttention.Type.OBSERVING_CANDIDATE,
            title="候选人希望了解公司",
            idempotency_key="observe:attention-candidate:1",
            account=self.account,
            job=self.job,
            application=self.application,
            detail={"message": "我想先了解一下公司"},
        )
        second, second_created = ensure_attention(
            attention_type=HumanAttention.Type.OBSERVING_CANDIDATE,
            title="重复事件不会重复建待办",
            idempotency_key="observe:attention-candidate:1",
            account=self.account,
            job=self.job,
            application=self.application,
        )
        self.assertTrue(first_created)
        self.assertFalse(second_created)
        self.assertEqual(first.pk, second.pk)

        listed = self.client.get("/api/recruitment/human-attentions/?status=open")
        self.assertEqual(listed.status_code, 200)
        self.assertEqual(listed.data["count"], 1)
        resolved = self.client.post(
            f"/api/recruitment/human-attentions/{first.pk}/resolve/",
            {"note": "已经人工回复候选人"},
            format="json",
        )
        self.assertEqual(resolved.status_code, 200, resolved.data)
        self.assertEqual(resolved.data["status"], HumanAttention.Status.RESOLVED)
        self.assertEqual(resolved.data["resolved_by_name"], self.user.username)

    def test_hr_can_bulk_archive_visible_attention_items_without_resolving_them(self):
        open_attention, _ = ensure_attention(
            attention_type=HumanAttention.Type.OTHER,
            title="待人工判断",
            idempotency_key="bulk-open-attention",
            account=self.account,
            job=self.job,
        )
        resolved_attention, _ = ensure_attention(
            attention_type=HumanAttention.Type.OBSERVING_CANDIDATE,
            title="已经处理",
            idempotency_key="bulk-resolved-attention",
            account=self.account,
            job=self.job,
        )
        resolved_attention.status = HumanAttention.Status.RESOLVED
        resolved_attention.save(update_fields=["status", "updated_at"])

        response = self.client.post(
            "/api/recruitment/human-attentions/bulk-archive/",
            {"attention_ids": [open_attention.pk, resolved_attention.pk]},
            format="json",
        )

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["archived_count"], 2)
        open_attention.refresh_from_db()
        resolved_attention.refresh_from_db()
        self.assertEqual(open_attention.status, HumanAttention.Status.ARCHIVED)
        self.assertEqual(resolved_attention.status, HumanAttention.Status.ARCHIVED)
        self.assertIsNone(open_attention.resolved_at)

    def test_other_hr_cannot_see_account_policy_or_attention(self):
        ensure_attention(
            attention_type=HumanAttention.Type.OTHER,
            title="仅所属 HR 可见",
            idempotency_key="hidden-attention",
            account=self.account,
            job=self.job,
        )
        MessageSyncPolicy.objects.create(boss_account=self.account, interval_minutes=5)
        other = User.objects.create_user(username="other-attention-hr")
        AccountProfile.objects.create(user=other, role=AccountProfile.Role.HR)
        self.client.force_login(other)

        self.assertEqual(self.client.get("/api/recruitment/human-attentions/").data["count"], 0)
        self.assertEqual(self.client.get("/api/recruitment/message-sync-policies/").data["count"], 0)
