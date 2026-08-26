from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from attendance.models import AccountProfile
from recruitment.models import MessageSyncPolicy, RpaTask
from recruitment.rpa.tasks import RpaRuntimeUnavailable, create_task


@transaction.atomic
def schedule_due_conversation_syncs(*, now=None):
    current = now or timezone.now()
    scheduled = []
    policies = MessageSyncPolicy.objects.select_for_update().select_related("boss_account").filter(
        enabled=True, boss_account__active=True,
    )
    for policy in policies:
        due_at = (policy.last_scheduled_at or policy.created_at) + timedelta(minutes=policy.interval_minutes)
        if due_at > current:
            continue
        if policy.boss_account.rpa_tasks.filter(
            action=RpaTask.Action.SYNC_CONVERSATIONS,
            status__in=[RpaTask.Status.PENDING, RpaTask.Status.LEASED, RpaTask.Status.RUNNING],
        ).exists():
            continue
        actor = policy.boss_account.authorized_users.filter(
            account_profile__role__in=[AccountProfile.Role.HR, AccountProfile.Role.ADMIN],
        ).order_by("id").first()
        if actor is None:
            continue
        try:
            task = create_task(
                account=policy.boss_account, action=RpaTask.Action.SYNC_CONVERSATIONS, actor=actor,
                request_payload={"scheduled": True, "policy_id": policy.pk},
                idempotency_key=f"message-sync-policy:{policy.pk}:{int(current.timestamp() // 60)}",
            )
        except RpaRuntimeUnavailable:
            continue
        policy.last_scheduled_at = current
        policy.save(update_fields=["last_scheduled_at", "updated_at"])
        scheduled.append(task)
    return scheduled
