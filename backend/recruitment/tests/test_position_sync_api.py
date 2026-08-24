from django.contrib.auth.models import User
from rest_framework.test import APITestCase

from attendance.models import AccountProfile
from recruitment.models import BossAccount, RpaTask


class PositionSyncApiTests(APITestCase):
    def setUp(self):
        self.hr = User.objects.create_user(username="sync-api-hr")
        AccountProfile.objects.create(user=self.hr, role=AccountProfile.Role.HR)
        self.account = BossAccount.objects.create(
            name="sync-api",
            browser_profile="sync-api",
            cdp_port=53482,
        )
        self.account.authorized_users.add(self.hr)
        self.client.force_login(self.hr)

    def test_one_click_sync_creates_an_idempotent_task(self):
        request_id = "11111111-1111-4111-8111-111111111111"

        response = self.client.post(
            "/api/recruitment/jobs/sync/",
            {"boss_account": self.account.id, "request_id": request_id},
            format="json",
        )

        self.assertEqual(response.status_code, 201, response.data)
        task = RpaTask.objects.get(pk=response.data["task_id"])
        self.assertEqual(task.action, RpaTask.Action.SYNC_POSITIONS)
        self.assertEqual(task.idempotency_key, f"position-sync:{self.account.id}:{request_id}")

        repeated = self.client.post(
            "/api/recruitment/jobs/sync/",
            {"boss_account": self.account.id, "request_id": request_id},
            format="json",
        )
        self.assertEqual(repeated.status_code, 200, repeated.data)
        self.assertEqual(repeated.data["task_id"], response.data["task_id"])

    def test_unassigned_account_is_rejected(self):
        other = BossAccount.objects.create(
            name="other-sync",
            browser_profile="other-sync",
            cdp_port=53483,
        )

        response = self.client.post(
            "/api/recruitment/jobs/sync/",
            {
                "boss_account": other.id,
                "request_id": "22222222-2222-4222-8222-222222222222",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 403)

    def test_request_id_must_be_a_uuid(self):
        response = self.client.post(
            "/api/recruitment/jobs/sync/",
            {"boss_account": self.account.id, "request_id": "not-a-uuid"},
            format="json",
        )

        self.assertEqual(response.status_code, 400)
