from datetime import timedelta
import hashlib
import json

from django.db import transaction
from django.utils import timezone

from attendance.models import AccountProfile
from recruitment.models import BossAccount, MessageSyncPolicy, RpaTask
from recruitment.rpa.tasks import RpaRuntimeUnavailable, create_task


@transaction.atomic
def schedule_due_conversation_syncs(*, now=None):
    current = now or timezone.now()
    scheduled = []
    policy_snapshots = list(
        MessageSyncPolicy.objects.filter(enabled=True, boss_account__active=True)
        .order_by("boss_account_id")
        .values("pk", "boss_account_id")
    )
    for snapshot in policy_snapshots:
        account = BossAccount.objects.select_for_update().get(pk=snapshot["boss_account_id"])
        policy = (
            MessageSyncPolicy.objects.select_for_update()
            .select_related("boss_account")
            .filter(pk=snapshot["pk"], enabled=True, boss_account=account)
            .first()
        )
        if policy is None:
            continue
        from recruitment.services.automation_plans import message_sync_scopes_for_account

        plan_scopes = message_sync_scopes_for_account(account)
        if not plan_scopes:
            policy.enabled = False
            policy.save(update_fields=["enabled", "updated_at"])
            continue
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
            scope_digest = hashlib.sha256(
                json.dumps(plan_scopes, sort_keys=True, separators=(",", ":")).encode("utf-8")
            ).hexdigest()[:20]
            task = create_task(
                account=policy.boss_account, action=RpaTask.Action.SYNC_CONVERSATIONS, actor=actor,
                request_payload={
                    "scheduled": True,
                    "policy_id": policy.pk,
                    "passive_plan_scopes": plan_scopes,
                },
                idempotency_key=(
                    f"message-sync-policy:{policy.pk}:{int(current.timestamp() // 60)}:{scope_digest}"
                ),
            )
        except RpaRuntimeUnavailable:
            continue
        policy.last_scheduled_at = current
        policy.save(update_fields=["last_scheduled_at", "updated_at"])
        scheduled.append(task)
    return scheduled
