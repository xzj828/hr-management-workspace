import json

from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError

from attendance.permissions import is_hr_user
from recruitment.models import (
    AutomationApproval,
    BossAccount,
    RecruitmentAuditLog,
    RecruitmentAutomationPlan,
)
from recruitment.services.sqlite_lifecycle import serialize_sqlite_lifecycle


def _ensure_authorized(approval, actor):
    account = approval.boss_account
    if actor.is_superuser:
        return
    if not is_hr_user(actor) or not account.authorized_users.filter(pk=actor.pk).exists():
        raise PermissionDenied("无权确认该 BOSS 账号的自动化操作")


@serialize_sqlite_lifecycle
def approve(*, approval, actor):
    expired = False
    with transaction.atomic():
        snapshot = AutomationApproval.objects.filter(pk=approval.pk).values(
            "action", "boss_account_id", "automation_plan_revision_id"
        ).first()
        if snapshot is None:
            raise ValidationError("该确认项不存在")
        BossAccount.objects.select_for_update().get(pk=snapshot["boss_account_id"])
        if snapshot["action"] == AutomationApproval.Action.REJECTION_NOTICE:
            from recruitment.services.screening import lock_rejection_approval_domain

            lock_rejection_approval_domain(approval=approval)
        if snapshot["automation_plan_revision_id"] is not None:
            RecruitmentAutomationPlan.objects.select_for_update().get(
                revisions__pk=snapshot["automation_plan_revision_id"]
            )
        locked = (
            AutomationApproval.objects.select_for_update()
            .select_related("boss_account")
            .get(pk=approval.pk)
        )
        _ensure_authorized(locked, actor)
        if locked.automation_plan_revision_id:
            from recruitment.services.automation_plans import assert_plan_fence_current

            assert_plan_fence_current(
                revision_id=locked.automation_plan_revision_id,
                generation=locked.automation_generation,
                message="招聘自动化方案已暂停、停止或被修改，该确认快照已失效",
            )
        if locked.status != AutomationApproval.Status.DRAFT:
            raise ValidationError("该确认项已处理")
        if locked.expires_at and locked.expires_at <= timezone.now():
            locked.status = AutomationApproval.Status.EXPIRED
            locked.save(update_fields=["status"])
            if locked.action == AutomationApproval.Action.REJECTION_NOTICE:
                from recruitment.services.screening import cancel_rejection_draft_actions_for_approval

                cancel_rejection_draft_actions_for_approval(
                    approval=locked,
                    actor=actor,
                    reason="approval_expired",
                )
            expired = True
        else:
            locked.payload = json.loads(json.dumps(locked.payload, ensure_ascii=False))
            locked.status = AutomationApproval.Status.APPROVED
            locked.approved_by = actor
            locked.approved_at = timezone.now()
            locked.save(update_fields=["payload", "status", "approved_by", "approved_at"])
    if expired:
        raise ValidationError("该确认项已过期")
    return locked


@serialize_sqlite_lifecycle
@transaction.atomic
def reject(*, approval, actor, note=""):
    snapshot = AutomationApproval.objects.filter(pk=approval.pk).values(
        "action", "boss_account_id", "automation_plan_revision_id"
    ).first()
    if snapshot is None:
        raise ValidationError("该确认项不存在")
    BossAccount.objects.select_for_update().get(pk=snapshot["boss_account_id"])
    if snapshot["action"] == AutomationApproval.Action.REJECTION_NOTICE:
        from recruitment.services.screening import lock_rejection_approval_domain

        lock_rejection_approval_domain(approval=approval)
    if snapshot["automation_plan_revision_id"] is not None:
        RecruitmentAutomationPlan.objects.select_for_update().get(
            revisions__pk=snapshot["automation_plan_revision_id"]
        )
    locked = (
        AutomationApproval.objects.select_for_update()
        .select_related("boss_account")
        .get(pk=approval.pk)
    )
    _ensure_authorized(locked, actor)
    if locked.status != AutomationApproval.Status.DRAFT:
        raise ValidationError("该确认项已处理")
    locked.payload = json.loads(json.dumps(locked.payload, ensure_ascii=False))
    locked.status = AutomationApproval.Status.REJECTED
    locked.approved_by = actor
    locked.approved_at = timezone.now()
    locked.save(update_fields=["payload", "status", "approved_by", "approved_at"])
    if locked.action == AutomationApproval.Action.REJECTION_NOTICE:
        from recruitment.services.screening import cancel_rejection_draft_actions_for_approval

        cancel_rejection_draft_actions_for_approval(
            approval=locked,
            actor=actor,
            reason="approval_rejected",
        )
    RecruitmentAuditLog.objects.create(
        actor=actor,
        boss_account=locked.boss_account,
        action="automation_approval_rejected",
        target_id=str(locked.pk),
        detail={
            "approval_action": locked.action,
            **(
                {
                    "note_present": bool(str(note or "")),
                    "note_length": len(str(note or "")),
                }
                if locked.action == AutomationApproval.Action.REJECTION_NOTICE
                else {"note": str(note or "")[:500]}
            ),
        },
    )
    return locked
