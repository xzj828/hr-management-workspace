from dataclasses import dataclass

from django.db import transaction
from django.utils import timezone

from recruitment.models import BossAccount, RecruitmentAuditLog, RpaTask, RpaTaskEvent


@dataclass(frozen=True)
class TaskRecoveryResult:
    requeued_leases: int = 0
    failed_running: int = 0


def _account_idle_status(account):
    if account.verification_status in {"token_invalid", "risk_control"}:
        return BossAccount.Status.RISK
    if account.login_status == BossAccount.LoginStatus.READY:
        return BossAccount.Status.READY
    if account.login_status == BossAccount.LoginStatus.WAITING_HUMAN:
        return BossAccount.Status.PAUSED
    return BossAccount.Status.OFFLINE


@transaction.atomic
def recover_stale_tasks(*, now=None):
    observed_at = now or timezone.now()
    expired = list(
        RpaTask.objects.select_for_update()
        .select_related("boss_account")
        .filter(
            status__in=[RpaTask.Status.LEASED, RpaTask.Status.RUNNING],
            lease_expires_at__lt=observed_at,
        )
        .order_by("created_at")
    )
    requeued = 0
    failed = 0
    for task in expired:
        account = task.boss_account
        if task.status == RpaTask.Status.LEASED:
            task.status = RpaTask.Status.PENDING
            task.worker = None
            task.lease_expires_at = None
            task.save(update_fields=["status", "worker", "lease_expires_at", "updated_at"])
            RpaTaskEvent.objects.create(
                task=task,
                level="warning",
                event="lease_expired",
                message="Worker 未及时开始任务，任务已重新排队",
            )
            requeued += 1
        else:
            task.status = RpaTask.Status.FAILED
            task.worker = None
            task.lease_expires_at = None
            task.completed_at = observed_at
            task.error_code = "worker_lease_expired"
            task.error_message = "Worker 失联或任务长时间没有进度，系统已结束本次执行"
            task.save(
                update_fields=[
                    "status", "worker", "lease_expires_at", "completed_at",
                    "error_code", "error_message", "updated_at",
                ]
            )
            RpaTaskEvent.objects.create(
                task=task,
                level="error",
                event="worker_lease_expired",
                message="Worker 失联，任务已自动结束，可由 HR 重新执行",
            )
            RecruitmentAuditLog.objects.create(
                boss_account=account,
                action="task_recovered_after_worker_timeout",
                target_id=str(task.pk),
                detail={"previous_status": RpaTask.Status.RUNNING, "error_code": task.error_code},
            )
            failed += 1

        account.status = _account_idle_status(account)
        account.save(update_fields=["status", "updated_at"])

    return TaskRecoveryResult(requeued_leases=requeued, failed_running=failed)
