from django.contrib.auth.models import User
from django.utils import timezone
from rest_framework.test import APITestCase

from attendance.models import AccountProfile
from recruitment.models import BossAccount, RecruitmentAuditLog, RpaTask, RpaWorker


class RpaTaskApiTests(APITestCase):
    def setUp(self):
        self.hr = User.objects.create_user(username="task-hr")
        AccountProfile.objects.create(user=self.hr, role=AccountProfile.Role.HR)
        self.other_hr = User.objects.create_user(username="other-task-hr")
        AccountProfile.objects.create(user=self.other_hr, role=AccountProfile.Role.HR)
        self.viewer = User.objects.create_user(username="task-viewer")
        AccountProfile.objects.create(user=self.viewer, role=AccountProfile.Role.VIEWER)
        self.account = BossAccount.objects.create(
            name="任务测试账号",
            browser_profile="boss-task-test",
            cdp_port=53470,
            browser_executable="C:/Program Files/Google/Chrome/Application/chrome.exe",
            user_data_dir="C:/hr-test/profiles/boss-task-test",
        )
        self.account.authorized_users.add(self.hr)

    def create_task(self, action="check_status", payload=None):
        self.client.force_login(self.hr)
        body = {"boss_account": self.account.id, "action": action}
        if payload is not None:
            body["request_payload"] = payload
        return self.client.post("/api/recruitment/rpa-tasks/", body, format="json")

    def test_hr_can_create_check_status_task(self):
        response = self.create_task(payload={"open_login": True})

        self.assertEqual(response.status_code, 201, response.data)
        task = RpaTask.objects.get(pk=response.data["id"])
        self.assertEqual(task.created_by, self.hr)
        self.assertEqual(task.events.get().event, "created")
        self.assertTrue(RecruitmentAuditLog.objects.filter(target_id=str(task.pk), action="task_created").exists())

    def test_viewer_cannot_create_task(self):
        self.client.force_login(self.viewer)
        response = self.client.post(
            "/api/recruitment/rpa-tasks/",
            {"boss_account": self.account.id, "action": "sync_positions"},
            format="json",
        )

        self.assertEqual(response.status_code, 403)

    def test_unapproved_action_is_rejected(self):
        response = self.create_task(action="send_message")

        self.assertEqual(response.status_code, 400)

    def test_disabled_write_action_is_rejected_with_policy_message(self):
        response = self.create_task(action="greet", payload={"candidate_ids": [1]})

        self.assertEqual(response.status_code, 400)
        self.assertIn("尚未开放", str(response.data))

    def test_idempotency_key_returns_the_existing_task(self):
        self.client.force_login(self.hr)
        body = {
            "boss_account": self.account.id,
            "action": "sync_positions",
            "idempotency_key": "sync-click-1",
        }

        first = self.client.post("/api/recruitment/rpa-tasks/", body, format="json")
        second = self.client.post("/api/recruitment/rpa-tasks/", body, format="json")

        self.assertEqual(first.status_code, 201, first.data)
        self.assertEqual(second.status_code, 200, second.data)
        self.assertEqual(first.data["id"], second.data["id"])
        self.assertEqual(RpaTask.objects.count(), 1)

    def test_unassigned_hr_cannot_operate_account(self):
        self.client.force_login(self.other_hr)
        response = self.client.post(
            "/api/recruitment/rpa-tasks/",
            {"boss_account": self.account.id, "action": "check_status"},
            format="json",
        )

        self.assertEqual(response.status_code, 403)

    def test_second_active_task_is_rejected_cleanly(self):
        self.assertEqual(self.create_task().status_code, 201)

        response = self.create_task(action="sync_positions")

        self.assertEqual(response.status_code, 400)
        self.assertEqual(RpaTask.objects.count(), 1)

    def test_pending_task_can_be_cancelled(self):
        task_id = self.create_task().data["id"]

        response = self.client.post(f"/api/recruitment/rpa-tasks/{task_id}/cancel/")

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["status"], "cancelled")

    def test_failed_task_can_be_retried(self):
        old_task = RpaTask.objects.create(
            boss_account=self.account,
            action=RpaTask.Action.CHECK_STATUS,
            status=RpaTask.Status.FAILED,
            created_by=self.hr,
            completed_at=timezone.now(),
        )
        self.client.force_login(self.hr)

        response = self.client.post(f"/api/recruitment/rpa-tasks/{old_task.pk}/retry/")

        self.assertEqual(response.status_code, 201, response.data)
        self.assertNotEqual(response.data["id"], str(old_task.pk))

    def test_summary_reads_persisted_worker_state(self):
        RpaWorker.objects.create(
            key="local-worker",
            hostname="WIN-HR",
            version="0.6.6",
            status=RpaWorker.Status.ONLINE,
            capabilities={"boss_cli": True},
            last_seen_at=timezone.now(),
        )
        self.client.force_login(self.hr)

        response = self.client.get("/api/recruitment/automation/summary/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["worker"]["version"], "0.6.6")
        self.assertTrue(response.data["cli_available"])
