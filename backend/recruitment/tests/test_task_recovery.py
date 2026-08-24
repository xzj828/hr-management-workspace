from datetime import timedelta

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone

from recruitment.models import BossAccount, RpaTask, RpaWorker
from recruitment.services.task_recovery import recover_stale_tasks


class TaskRecoveryTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(username="recovery-owner")
        self.account = BossAccount.objects.create(
            name="失联任务账号",
            browser_profile="recovery-profile",
            cdp_port=53520,
            login_status=BossAccount.LoginStatus.READY,
            status=BossAccount.Status.RUNNING,
        )
        self.worker = RpaWorker.objects.create(key="lost-worker", hostname="LOST")

    def test_expired_running_task_fails_and_account_returns_to_login_state(self):
        task = RpaTask.objects.create(
            boss_account=self.account,
            action=RpaTask.Action.CHECK_STATUS,
            status=RpaTask.Status.RUNNING,
            created_by=self.owner,
            worker=self.worker,
            lease_expires_at=timezone.now() - timedelta(seconds=1),
            started_at=timezone.now() - timedelta(minutes=10),
        )

        result = recover_stale_tasks()

        task.refresh_from_db()
        self.account.refresh_from_db()
        self.assertEqual(result.failed_running, 1)
        self.assertEqual(task.status, RpaTask.Status.FAILED)
        self.assertEqual(task.error_code, "worker_lease_expired")
        self.assertIsNotNone(task.completed_at)
        self.assertIsNone(task.worker)
        self.assertIsNone(task.lease_expires_at)
        self.assertEqual(self.account.status, BossAccount.Status.READY)
        self.assertTrue(task.events.filter(event="worker_lease_expired").exists())

    def test_expired_lease_is_requeued_without_losing_audit_history(self):
        task = RpaTask.objects.create(
            boss_account=self.account,
            action=RpaTask.Action.CHECK_STATUS,
            status=RpaTask.Status.LEASED,
            created_by=self.owner,
            worker=self.worker,
            lease_expires_at=timezone.now() - timedelta(seconds=1),
        )

        result = recover_stale_tasks()

        task.refresh_from_db()
        self.account.refresh_from_db()
        self.assertEqual(result.requeued_leases, 1)
        self.assertEqual(task.status, RpaTask.Status.PENDING)
        self.assertIsNone(task.worker)
        self.assertIsNone(task.lease_expires_at)
        self.assertEqual(self.account.status, BossAccount.Status.READY)
        self.assertTrue(task.events.filter(event="lease_expired").exists())
