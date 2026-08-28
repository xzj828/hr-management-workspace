from datetime import timedelta

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError

from attendance.models import AccountProfile
from recruitment.models import AutomationApproval, AutomationUsage, BossAccount
from recruitment.services.approvals import approve
from recruitment.services.usage import consume


class ApprovalServiceTests(TestCase):
    def setUp(self):
        self.hr = User.objects.create_user(username="approval-hr")
        AccountProfile.objects.create(user=self.hr, role=AccountProfile.Role.HR)
        self.other_hr = User.objects.create_user(username="other-approval-hr")
        AccountProfile.objects.create(user=self.other_hr, role=AccountProfile.Role.HR)
        self.account = BossAccount.objects.create(
            name="approval-account",
            browser_profile="approval-profile",
            cdp_port=53481,
        )
        self.account.authorized_users.add(self.hr)

    def test_approve_keeps_an_immutable_payload_snapshot(self):
        source = {"text": "您好", "candidate_ids": [1, 2]}
        approval = AutomationApproval.objects.create(
            action=AutomationApproval.Action.GREET,
            boss_account=self.account,
            created_by=self.hr,
            payload=source,
            item_count=2,
        )

        approve(approval=approval, actor=self.hr)
        source["text"] = "changed"
        approval.refresh_from_db()

        self.assertEqual(approval.payload["text"], "您好")
        self.assertEqual(approval.status, AutomationApproval.Status.APPROVED)
        self.assertEqual(approval.approved_by, self.hr)
        self.assertIsNotNone(approval.approved_at)

    def test_expired_approval_cannot_be_approved(self):
        approval = AutomationApproval.objects.create(
            action=AutomationApproval.Action.GREET,
            boss_account=self.account,
            created_by=self.hr,
            payload={},
            expires_at=timezone.now() - timedelta(seconds=1),
        )

        with self.assertRaises(ValidationError):
            approve(approval=approval, actor=self.hr)

        approval.refresh_from_db()
        self.assertEqual(approval.status, AutomationApproval.Status.EXPIRED)

    def test_unassigned_hr_cannot_approve(self):
        approval = AutomationApproval.objects.create(
            action=AutomationApproval.Action.GREET,
            boss_account=self.account,
            created_by=self.hr,
            payload={},
        )

        with self.assertRaises(PermissionDenied):
            approve(approval=approval, actor=self.other_hr)

    def test_superuser_can_approve_without_explicit_account_assignment(self):
        admin = User.objects.create_superuser(username="approval-admin", email="admin@example.com")
        approval = AutomationApproval.objects.create(
            action=AutomationApproval.Action.GREET,
            boss_account=self.account,
            created_by=self.hr,
            payload={},
        )

        approved = approve(approval=approval, actor=admin)

        self.assertEqual(approved.status, AutomationApproval.Status.APPROVED)
        self.assertEqual(approved.approved_by, admin)

    def test_daily_limit_is_atomic(self):
        self.account.daily_message_limit = 2
        self.account.save(update_fields=["daily_message_limit"])

        usage = consume(account=self.account, metric=AutomationUsage.Metric.MESSAGE, amount=2)

        self.assertEqual(usage.used, 2)
        with self.assertRaises(ValidationError):
            consume(account=self.account, metric=AutomationUsage.Metric.MESSAGE, amount=1)
        usage.refresh_from_db()
        self.assertEqual(usage.used, 2)

    def test_zero_limit_records_usage_without_a_local_cap(self):
        self.account.daily_resume_view_limit = 0
        self.account.save(update_fields=["daily_resume_view_limit"])

        usage = consume(
            account=self.account,
            metric=AutomationUsage.Metric.RESUME_VIEW,
            amount=100,
        )

        self.assertEqual(usage.used, 100)

    def test_zero_amount_is_rejected(self):
        with self.assertRaises(ValidationError):
            consume(account=self.account, metric=AutomationUsage.Metric.SEARCH, amount=0)
