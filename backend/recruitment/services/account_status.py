from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from recruitment.models import BossAccount, RecruitmentAuditLog


def _operational_status(login_status, verification_status):
    if verification_status in {"token_invalid", "risk_control"}:
        return BossAccount.Status.RISK
    if login_status == BossAccount.LoginStatus.READY:
        return BossAccount.Status.READY
    if login_status == BossAccount.LoginStatus.WAITING_HUMAN:
        return BossAccount.Status.PAUSED
    return BossAccount.Status.OFFLINE


@transaction.atomic
def apply_account_observation(*, account, login_status, verification_status="", detail="", observed_at=None):
    if login_status not in BossAccount.LoginStatus.values:
        raise ValidationError("登录状态无效")
    locked = BossAccount.objects.select_for_update().get(pk=account.pk)
    verification = str(verification_status or "")[:40]
    previous = (locked.login_status, locked.verification_status, locked.status)
    locked.login_status = login_status
    locked.verification_status = verification
    locked.status = _operational_status(login_status, verification)
    locked.last_checked_at = observed_at or timezone.now()
    locked.save(
        update_fields=["login_status", "verification_status", "status", "last_checked_at", "updated_at"]
    )
    current = (locked.login_status, locked.verification_status, locked.status)
    if current != previous:
        RecruitmentAuditLog.objects.create(
            boss_account=locked,
            action="boss_login_status_changed",
            target_id=str(locked.pk),
            detail={
                "from": {"login_status": previous[0], "verification_status": previous[1], "status": previous[2]},
                "to": {"login_status": current[0], "verification_status": current[1], "status": current[2]},
                "observation_detail": str(detail or "")[:500],
            },
        )
    return locked
