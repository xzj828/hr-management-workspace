from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from recruitment.models import ApplicationStageHistory, BossAccount, JobApplication, RecruitmentAuditLog


EVENT_STAGE = {
    "greet_succeeded": JobApplication.Stage.GREETED,
    "candidate_replied": JobApplication.Stage.COMMUNICATING,
    "resume_requested": JobApplication.Stage.WAITING_RESUME,
    "resume_archived": JobApplication.Stage.RESUME_RECEIVED,
    "interview_sent": JobApplication.Stage.TO_INTERVIEW,
}


@transaction.atomic
def _change(*, application, to_stage, source, reason, actor=None, task=None):
    account_id = JobApplication.objects.values_list("job__boss_account_id", flat=True).get(pk=application.pk)
    if account_id:
        BossAccount.objects.select_for_update().get(pk=account_id)
    locked = JobApplication.objects.select_for_update().select_related("job").get(pk=application.pk)
    if to_stage not in JobApplication.Stage.values:
        raise ValidationError("招聘阶段无效")
    if locked.stage == to_stage:
        return False
    from recruitment.services.screening import (
        FORBIDDEN_REJECTION_STAGES,
        invalidate_rejection_work_for_application,
    )

    if to_stage in FORBIDDEN_REJECTION_STAGES:
        invalidate_rejection_work_for_application(
            application=locked,
            actor=actor,
            trigger="application_stage_changed",
        )
    previous = locked.stage
    locked.stage = to_stage
    locked.last_interaction_at = timezone.now()
    locked.save(update_fields=["stage", "last_interaction_at", "updated_at"])
    ApplicationStageHistory.objects.create(
        application=locked,
        from_stage=previous,
        to_stage=to_stage,
        source=source,
        reason=reason,
        actor=actor,
        task=task,
    )
    RecruitmentAuditLog.objects.create(
        actor=actor,
        boss_account=locked.job.boss_account,
        action="application_stage_changed",
        target_id=str(locked.pk),
        detail={"from": previous, "to": to_stage, "source": source, "reason": reason},
    )
    return True


def advance_for_event(*, application, event, actor=None, task=None, verified=True):
    if not verified or event not in EVENT_STAGE:
        return False
    return _change(
        application=application,
        to_stage=EVENT_STAGE[event],
        source=ApplicationStageHistory.Source.AUTOMATION,
        reason={
            "greet_succeeded": "打招呼已核验成功",
            "candidate_replied": "检测到候选人回复",
            "resume_requested": "索要简历已核验成功",
            "resume_archived": "简历文件已归档",
            "interview_sent": "面试邀约已核验成功",
        }[event],
        actor=actor,
        task=task,
    )


def change_stage_manually(*, application, to_stage, actor, reason):
    normalized = str(reason or "").strip()
    if not normalized:
        raise ValidationError("人工调整阶段时必须填写原因")
    return _change(
        application=application,
        to_stage=to_stage,
        source=ApplicationStageHistory.Source.MANUAL,
        reason=normalized,
        actor=actor,
    )


def reject_for_hard_requirements(*, application, actor, failure_keys):
    keys = [str(key) for key in failure_keys if str(key)]
    if not keys:
        return False
    return _change(
        application=application,
        to_stage=JobApplication.Stage.REJECTED,
        source=ApplicationStageHistory.Source.AUTOMATION,
        reason=f"简历明确不满足已确认硬性指标：{', '.join(keys)}",
        actor=actor,
    )

