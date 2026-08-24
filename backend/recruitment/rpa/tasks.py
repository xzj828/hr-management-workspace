from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError

from attendance.permissions import is_hr_user
from recruitment.models import (
    AutomationApproval,
    BossAccount,
    RecruitmentAuditLog,
    RpaTask,
    RpaTaskEvent,
)
from recruitment.rpa.capabilities import REGISTRY


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
def create_task(
    *,
    account,
    action,
    actor,
    request_payload=None,
    approval=None,
    execution_batch=None,
    idempotency_key="",
    return_created=False,
):
    locked = BossAccount.objects.select_for_update().get(pk=account.pk)
    _ensure_authorized(locked, actor)
    if not locked.active:
        raise ValidationError("该 BOSS 账号已停用")
    capability = REGISTRY.get(action)
    if capability is None or action not in RpaTask.Action.values:
        raise ValidationError("不支持的自动化动作")
    if not capability.enabled:
        raise ValidationError("该自动化动作尚未开放")

    normalized_key = str(idempotency_key or "").strip()
    if normalized_key:
        existing = RpaTask.objects.filter(idempotency_key=normalized_key).first()
        if existing:
            if existing.boss_account_id != locked.pk or existing.created_by_id != actor.pk:
                raise ValidationError("幂等请求标识已被其他任务使用")
            return (existing, False) if return_created else existing

    locked_approval = None
    if capability.requires_approval:
        if approval is None:
            raise ValidationError("该自动化动作需要 HR 确认")
        locked_approval = AutomationApproval.objects.select_for_update().filter(pk=approval.pk).first()
        if (
            locked_approval is None
            or locked_approval.boss_account_id != locked.pk
            or locked_approval.action != action
            or locked_approval.status != AutomationApproval.Status.APPROVED
        ):
            raise ValidationError("自动化确认记录无效")
        if locked_approval.expires_at and locked_approval.expires_at <= timezone.now():
            raise ValidationError("自动化确认记录已过期")

    if locked.rpa_tasks.filter(status__in=[RpaTask.Status.PENDING, RpaTask.Status.LEASED, RpaTask.Status.RUNNING]).exists():
        raise ValidationError("该账号已有任务正在执行")

    task = RpaTask.objects.create(
        boss_account=locked,
        action=action,
        created_by=actor,
        approval=locked_approval,
        execution_batch=execution_batch,
        idempotency_key=normalized_key or None,
        request_payload=request_payload or {},
    )
    append_event(task=task, event="created", message="任务已创建")
    RecruitmentAuditLog.objects.create(
        actor=actor,
        boss_account=locked,
        action="task_created",
        target_id=str(task.pk),
        detail={
            "task_action": action,
            "adapter": capability.adapter,
            "approval_id": str(locked_approval.pk) if locked_approval else "",
            "idempotency_key": normalized_key,
        },
    )
    return (task, True) if return_created else task


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

