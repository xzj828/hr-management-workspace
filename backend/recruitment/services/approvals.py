import json

from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError

from attendance.permissions import is_hr_user
from recruitment.models import AutomationApproval


def _ensure_authorized(approval, actor):
    account = approval.boss_account
    if not is_hr_user(actor) or not account.authorized_users.filter(pk=actor.pk).exists():
        raise PermissionDenied("无权确认该 BOSS 账号的自动化操作")


def approve(*, approval, actor):
    expired = False
    with transaction.atomic():
        locked = (
            AutomationApproval.objects.select_for_update()
            .select_related("boss_account")
            .get(pk=approval.pk)
        )
        _ensure_authorized(locked, actor)
        if locked.status != AutomationApproval.Status.DRAFT:
            raise ValidationError("该确认项已处理")
        if locked.expires_at and locked.expires_at <= timezone.now():
            locked.status = AutomationApproval.Status.EXPIRED
            locked.save(update_fields=["status"])
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
