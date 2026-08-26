from datetime import timedelta

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone

from attendance.models import AccountProfile
from recruitment.models import BossAccount, MessageSyncPolicy, RpaTask, RpaWorker
from recruitment.services.message_scheduling import schedule_due_conversation_syncs


class MessageSchedulingTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("sync-scheduler")
        AccountProfile.objects.create(user=self.user, role=AccountProfile.Role.HR)
        self.account = BossAccount.objects.create(name="Sync account", browser_profile="sync-policy", cdp_port=53989)
        self.account.authorized_users.add(self.user)
        self.worker = RpaWorker.objects.create(
            key="message-scheduling-worker",
            hostname="localhost",
            status=RpaWorker.Status.ONLINE,
            last_seen_at=timezone.now(),
            capabilities={"boss_cli": True},
        )

    def test_due_policy_queues_once_and_respects_interval(self):
        now = timezone.now()
        policy = MessageSyncPolicy.objects.create(boss_account=self.account, interval_minutes=5)
        MessageSyncPolicy.objects.filter(pk=policy.pk).update(last_scheduled_at=now - timedelta(minutes=6))

        first = schedule_due_conversation_syncs(now=now)
        second = schedule_due_conversation_syncs(now=now + timedelta(minutes=1))

        self.assertEqual(len(first), 1)
        self.assertEqual(second, [])
        self.assertEqual(RpaTask.objects.get().action, RpaTask.Action.SYNC_CONVERSATIONS)
        self.assertTrue(RpaTask.objects.get().request_payload["scheduled"])

    def test_due_policy_is_left_due_when_runtime_is_offline(self):
        now = timezone.now()
        self.worker.delete()
        policy = MessageSyncPolicy.objects.create(boss_account=self.account, interval_minutes=5)
        MessageSyncPolicy.objects.filter(pk=policy.pk).update(last_scheduled_at=now - timedelta(minutes=6))

        scheduled = schedule_due_conversation_syncs(now=now)

        policy.refresh_from_db()
        self.assertEqual(scheduled, [])
        self.assertEqual(RpaTask.objects.count(), 0)
        self.assertEqual(policy.last_scheduled_at, now - timedelta(minutes=6))
