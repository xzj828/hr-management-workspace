from datetime import timedelta

from django.contrib.auth.models import User
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APITestCase

from recruitment.models import BossAccount, RecruitmentJob, RpaTask, RpaWorker


@override_settings(RPA_WORKER_TOKEN="test-worker-secret")
class WorkerApiTests(APITestCase):
    token_header = {"HTTP_X_RPA_WORKER_TOKEN": "test-worker-secret"}

    def setUp(self):
        self.hr = User.objects.create_user(username="worker-task-owner")
        self.account = BossAccount.objects.create(
            name="Worker 测试账号",
            browser_profile="boss-worker-test",
            browser_type="edge",
            browser_executable="C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe",
            user_data_dir="C:/hr/profiles/boss-worker-test",
            cdp_port=53470,
        )
        self.task = RpaTask.objects.create(
            boss_account=self.account,
            action=RpaTask.Action.CHECK_STATUS,
            created_by=self.hr,
            request_payload={"open_login": True},
        )

    def heartbeat(self):
        return self.client.post(
            "/api/recruitment/worker/heartbeat/",
            {"worker_key": "local-worker", "hostname": "WIN-HR", "version": "0.6.6", "capabilities": {"boss_cli": True}},
            format="json",
            **self.token_header,
        )

    def test_worker_endpoint_rejects_missing_token(self):
        response = self.client.post("/api/recruitment/worker/heartbeat/", {}, format="json")

        self.assertEqual(response.status_code, 403)

    def test_heartbeat_upserts_worker(self):
        response = self.heartbeat()

        self.assertEqual(response.status_code, 200, response.data)
        worker = RpaWorker.objects.get(key="local-worker")
        self.assertEqual(worker.status, RpaWorker.Status.ONLINE)
        self.assertTrue(worker.capabilities["boss_cli"])

    def test_worker_leases_oldest_pending_task(self):
        self.heartbeat()

        response = self.client.post(
            "/api/recruitment/worker/tasks/lease/",
            {"worker_key": "local-worker"},
            format="json",
            **self.token_header,
        )

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["task"]["id"], str(self.task.id))
        self.assertEqual(response.data["task"]["browser"]["type"], "edge")
        self.task.refresh_from_db()
        self.assertEqual(self.task.status, RpaTask.Status.LEASED)

    def test_expired_lease_can_be_reclaimed(self):
        worker = RpaWorker.objects.create(key="old-worker", hostname="OLD")
        self.task.status = RpaTask.Status.LEASED
        self.task.worker = worker
        self.task.lease_expires_at = timezone.now() - timedelta(seconds=1)
        self.task.save()
        self.heartbeat()

        response = self.client.post(
            "/api/recruitment/worker/tasks/lease/",
            {"worker_key": "local-worker"},
            format="json",
            **self.token_header,
        )

        self.assertEqual(response.status_code, 200, response.data)
        self.task.refresh_from_db()
        self.assertEqual(self.task.worker.key, "local-worker")

    def test_worker_can_append_event_and_complete(self):
        self.heartbeat()
        lease = self.client.post(
            "/api/recruitment/worker/tasks/lease/",
            {"worker_key": "local-worker"}, format="json", **self.token_header,
        )
        task_id = lease.data["task"]["id"]

        event = self.client.post(
            f"/api/recruitment/worker/tasks/{task_id}/event/",
            {"worker_key": "local-worker", "event": "browser_checked", "message": "浏览器状态已检查"},
            format="json", **self.token_header,
        )
        complete = self.client.post(
            f"/api/recruitment/worker/tasks/{task_id}/complete/",
            {"worker_key": "local-worker", "status": "waiting_human", "result": {"login_status": "token_invalid"}},
            format="json", **self.token_header,
        )

        self.assertEqual(event.status_code, 201, event.data)
        self.assertEqual(complete.status_code, 200, complete.data)
        self.task.refresh_from_db()
        self.account.refresh_from_db()
        self.assertEqual(self.task.status, RpaTask.Status.WAITING_HUMAN)
        self.assertEqual(self.account.verification_status, "token_invalid")

    def test_successful_position_task_persists_only_normalized_jobs(self):
        self.task.action = RpaTask.Action.SYNC_POSITIONS
        self.task.save(update_fields=["action"])
        self.heartbeat()
        lease = self.client.post(
            "/api/recruitment/worker/tasks/lease/",
            {"worker_key": "local-worker"}, format="json", **self.token_header,
        )

        response = self.client.post(
            f"/api/recruitment/worker/tasks/{lease.data['task']['id']}/complete/",
            {
                "worker_key": "local-worker",
                "status": "succeeded",
                "result": {"positions": [{
                    "external_id": "job-201", "title": "测试工程师", "status": "open", "raw": "原始 CLI 行"
                }]},
            },
            format="json", **self.token_header,
        )

        self.assertEqual(response.status_code, 200, response.data)
        self.assertTrue(RecruitmentJob.objects.filter(boss_account=self.account, external_id="job-201").exists())
        self.task.refresh_from_db()
        self.assertEqual(self.task.result["sync"]["created"], 1)
        self.assertNotIn("positions", self.task.result)
