from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import override_settings
from rest_framework.test import APITestCase

from attendance.models import AccountProfile
from recruitment.models import BossAccount
from recruitment.rpa.status import BossBrowserStatus


@override_settings(RPA_WORKER_TOKEN="status-worker-secret")
class AccountStatusApiTests(APITestCase):
    worker_headers = {"HTTP_X_RPA_WORKER_TOKEN": "status-worker-secret"}

    def setUp(self):
        self.hr = User.objects.create_user(username="status-hr")
        AccountProfile.objects.create(user=self.hr, role=AccountProfile.Role.HR)
        self.account = BossAccount.objects.create(
            name="状态检测账号",
            browser_profile="status-profile",
            browser_type=BossAccount.BrowserType.EDGE,
            browser_executable="C:/Edge/msedge.exe",
            user_data_dir="C:/profiles/status-profile",
            cdp_port=53530,
        )
        self.account.authorized_users.add(self.hr)

    def test_worker_status_targets_require_token_and_only_include_active_accounts(self):
        BossAccount.objects.create(
            name="已停用账号", browser_profile="inactive-profile", cdp_port=53531, active=False,
        )

        denied = self.client.get("/api/recruitment/worker/status-targets/")
        response = self.client.get(
            "/api/recruitment/worker/status-targets/", **self.worker_headers,
        )

        self.assertEqual(denied.status_code, 403)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(len(response.data["accounts"]), 1)
        self.assertEqual(response.data["accounts"][0]["id"], self.account.id)
        self.assertEqual(response.data["accounts"][0]["browser"]["cdp_port"], 53530)

    def test_worker_batch_observation_updates_login_and_risk_state(self):
        response = self.client.post(
            "/api/recruitment/worker/status-observations/",
            {"observations": [{
                "account_id": self.account.id,
                "login_status": "waiting_human",
                "verification_status": "token_invalid",
                "detail": "二维码失效",
            }]},
            format="json",
            **self.worker_headers,
        )

        self.assertEqual(response.status_code, 200, response.data)
        self.account.refresh_from_db()
        self.assertEqual(self.account.login_status, BossAccount.LoginStatus.WAITING_HUMAN)
        self.assertEqual(self.account.verification_status, "token_invalid")
        self.assertEqual(self.account.status, BossAccount.Status.RISK)
        self.assertIsNotNone(self.account.last_checked_at)

    @patch("recruitment.views.inspect_boss_status")
    def test_authorized_hr_can_check_status_immediately_without_queueing_task(self, inspect):
        inspect.return_value = BossBrowserStatus("ready", detail="已登录")
        self.client.force_login(self.hr)

        response = self.client.post(
            f"/api/recruitment/boss-accounts/{self.account.id}/check-status/",
            format="json",
        )

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["login_status"], "ready")
        self.assertEqual(response.data["status"], "ready")
        self.assertEqual(self.account.rpa_tasks.count(), 0)

    @patch("recruitment.views.inspect_boss_status")
    def test_unassigned_hr_cannot_inspect_another_account(self, inspect):
        other = User.objects.create_user(username="other-status-hr")
        AccountProfile.objects.create(user=other, role=AccountProfile.Role.HR)
        self.client.force_login(other)

        response = self.client.post(
            f"/api/recruitment/boss-accounts/{self.account.id}/check-status/",
            format="json",
        )

        self.assertEqual(response.status_code, 404)
        inspect.assert_not_called()
