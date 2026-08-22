from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError

from attendance.permissions import is_hr_user
from recruitment.models import BossAccount, RecruitmentAuditLog, RpaTask, RpaTaskEvent


def append_event(*, task, event, message, data=None, level="info"):
    return RpaTaskEvent.objects.create(
        task=task,
        event=event,
        message=message,
        data=data or {},
        level=level,
    )


def _ensure_authorized(account, actor):
    if not is_hr_user(actor) or not account.authorized_users.filter(pk=actor.pk).exists():
        raise PermissionDenied("无权操作该 BOSS 账号")


@transaction.atomic
def create_task(*, account, action, actor, request_payload=None):
    locked = BossAccount.objects.select_for_update().get(pk=account.pk)
    _ensure_authorized(locked, actor)
    if not locked.active:
        raise ValidationError("该 BOSS 账号已停用")
    if action not in RpaTask.Action.values:
        raise ValidationError("不支持的自动化动作")
    if locked.rpa_tasks.filter(status__in=[RpaTask.Status.PENDING, RpaTask.Status.LEASED, RpaTask.Status.RUNNING]).exists():
        raise ValidationError("该账号已有任务正在执行")

    task = RpaTask.objects.create(
        boss_account=locked,
        action=action,
        created_by=actor,
        request_payload=request_payload or {},
    )
    append_event(task=task, event="created", message="任务已创建")
    RecruitmentAuditLog.objects.create(
        actor=actor,
        boss_account=locked,
        action="task_created",
        target_id=str(task.pk),
        detail={"task_action": action},
    )
    return task


@transaction.atomic
def cancel_task(*, task, actor):
    locked = RpaTask.objects.select_for_update().select_related("boss_account").get(pk=task.pk)
    _ensure_authorized(locked.boss_account, actor)
    if locked.status != RpaTask.Status.PENDING:
        raise ValidationError("当前任务不能取消")

    locked.status = RpaTask.Status.CANCELLED
    locked.completed_at = timezone.now()
    locked.save(update_fields=["status", "completed_at", "updated_at"])
    append_event(task=locked, event="cancelled", message="任务已取消")
    RecruitmentAuditLog.objects.create(
        actor=actor,
        boss_account=locked.boss_account,
        action="task_cancelled",
        target_id=str(locked.pk),
    )
    return locked


def retry_task(*, task, actor):
    if task.status != RpaTask.Status.FAILED:
        raise ValidationError("只有失败任务可以重试")
    retried = create_task(
        account=task.boss_account,
        action=task.action,
        actor=actor,
        request_payload=task.request_payload,
    )
    append_event(task=retried, event="retried", message="由失败任务重试", data={"source_task_id": str(task.pk)})
    return retried

