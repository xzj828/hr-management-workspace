from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import APIException, ValidationError

from recruitment.models import (
    BossAccount, Candidate, JobApplication, RecruitmentAuditLog, RecruitmentJob, Resume, RpaTask,
    WorkflowTemplate, WorkflowVersion,
)


class LifecycleConflict(APIException):
    status_code = 409
    default_code = "lifecycle_conflict"


ACTIVE_TASK_STATUSES = {RpaTask.Status.PENDING, RpaTask.Status.LEASED, RpaTask.Status.RUNNING}


def _account_for(instance):
    if isinstance(instance, BossAccount):
        return instance
    if isinstance(instance, RecruitmentJob):
        return instance.boss_account
    if isinstance(instance, JobApplication):
        return instance.job.boss_account
    if isinstance(instance, RpaTask):
        return instance.boss_account
    if isinstance(instance, Resume) and instance.application_id:
        return instance.application.job.boss_account
    return None


@transaction.atomic
def archive_object(*, instance, actor):
    locked = type(instance).objects.select_for_update().get(pk=instance.pk)
    if locked.archived_at:
        return locked
    if isinstance(locked, BossAccount):
        if locked.rpa_tasks.filter(status__in=ACTIVE_TASK_STATUSES).exists():
            raise LifecycleConflict("该账号还有任务正在执行，请先取消或等待任务结束")
        locked.active = False
        locked.status = BossAccount.Status.OFFLINE
        update_fields = ["active", "status", "archived_at", "updated_at"]
    elif isinstance(locked, RecruitmentJob):
        locked.status = RecruitmentJob.Status.CLOSED
        update_fields = ["status", "archived_at", "updated_at"]
    elif isinstance(locked, RpaTask):
        if locked.status in ACTIVE_TASK_STATUSES:
            raise LifecycleConflict("运行中的任务不能归档，请先取消或等待任务结束")
        update_fields = ["archived_at", "updated_at"]
    elif isinstance(locked, WorkflowTemplate):
        locked.versions.filter(status=WorkflowVersion.Status.ENABLED).update(status=WorkflowVersion.Status.DISABLED)
        locked.active_version = None
        update_fields = ["active_version", "archived_at", "updated_at"]
    elif isinstance(locked, (Candidate, JobApplication, Resume)):
        update_fields = ["archived_at", "updated_at"]
    else:
        raise ValidationError("该对象不支持归档")
    locked.archived_at = timezone.now()
    locked.save(update_fields=update_fields)
    RecruitmentAuditLog.objects.create(
        actor=actor,
        boss_account=_account_for(locked),
        action="recruitment_object_archived",
        target_id=str(locked.pk),
        detail={"object_type": locked._meta.model_name},
    )
    return locked


@transaction.atomic
def restore_object(*, instance, actor):
    locked = type(instance).objects.select_for_update().get(pk=instance.pk)
    if not locked.archived_at:
        return locked
    locked.archived_at = None
    update_fields = ["archived_at", "updated_at"]
    if isinstance(locked, BossAccount):
        locked.active = True
        locked.status = BossAccount.Status.OFFLINE
        update_fields.extend(["active", "status"])
    locked.save(update_fields=update_fields)
    RecruitmentAuditLog.objects.create(
        actor=actor,
        boss_account=_account_for(locked),
        action="recruitment_object_restored",
        target_id=str(locked.pk),
        detail={"object_type": locked._meta.model_name},
    )
    return locked
