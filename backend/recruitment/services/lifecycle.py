import uuid

from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import APIException, ValidationError

from recruitment.models import (
    BossAccount, Candidate, JobApplication, RecruitmentAuditLog, RecruitmentJob, Resume, RpaTask,
    WorkflowTemplate, WorkflowVersion,
    RecruitmentAutomationPlan,
)
from recruitment.services.sqlite_lifecycle import serialize_sqlite_lifecycle


class LifecycleConflict(APIException):
    status_code = 409
    default_code = "lifecycle_conflict"


ACTIVE_TASK_STATUSES = {
    RpaTask.Status.PENDING,
    RpaTask.Status.LEASED,
    RpaTask.Status.RUNNING,
    RpaTask.Status.CANCEL_REQUESTED,
}


def _stop_plan_for_lifecycle(*, plan, actor):
    if plan.desired_state == RecruitmentAutomationPlan.DesiredState.STOPPED:
        return plan
    from recruitment.services.automation_plans import stop_plan

    return stop_plan(
        plan_id=plan.pk,
        actor=actor,
        request_id=uuid.uuid4(),
        expected_control_version=plan.control_version,
    ).plan


def _stop_job_plan_for_lifecycle(*, job_id, actor):
    plan = RecruitmentAutomationPlan.objects.filter(job_id=job_id).first()
    if plan is not None:
        _stop_plan_for_lifecycle(plan=plan, actor=actor)


def _account_for(instance):
    if isinstance(instance, BossAccount):
        return instance
    if isinstance(instance, RecruitmentJob):
        return instance.boss_account
    if isinstance(instance, RecruitmentAutomationPlan):
        return instance.job.boss_account
    if isinstance(instance, JobApplication):
        return instance.job.boss_account
    if isinstance(instance, RpaTask):
        return instance.boss_account
    if isinstance(instance, Resume) and instance.application_id:
        return instance.application.job.boss_account
    return None


@serialize_sqlite_lifecycle
@transaction.atomic
def change_job_status(*, job, to_status, actor):
    if to_status not in RecruitmentJob.Status.values:
        raise ValidationError("职位状态无效")
    account_id = RecruitmentJob.objects.filter(pk=job.pk).values_list(
        "boss_account_id", flat=True
    ).get()
    if account_id:
        BossAccount.objects.select_for_update().get(pk=account_id)
    if to_status != RecruitmentJob.Status.OPEN:
        _stop_job_plan_for_lifecycle(job_id=job.pk, actor=actor)
    locked = RecruitmentJob.objects.select_for_update().get(pk=job.pk)
    if locked.status == to_status:
        return locked
    if to_status != RecruitmentJob.Status.OPEN:
        applications = list(
            JobApplication.objects.select_for_update()
            .select_related("job__boss_account", "candidate")
            .filter(job=locked)
            .order_by("pk")
        )
        from recruitment.services.screening import invalidate_rejection_work_for_application

        for application in applications:
            invalidate_rejection_work_for_application(
                application=application,
                actor=actor,
                trigger="job_status_changed",
            )
    previous = locked.status
    locked.status = to_status
    locked.save(update_fields=["status", "updated_at"])
    RecruitmentAuditLog.objects.create(
        actor=actor,
        boss_account=locked.boss_account,
        action="recruitment_job_status_changed",
        target_id=str(locked.pk),
        detail={"from": previous, "to": to_status},
    )
    return locked


@serialize_sqlite_lifecycle
@transaction.atomic
def archive_object(*, instance, actor):
    if isinstance(instance, BossAccount):
        locked = BossAccount.objects.select_for_update().get(pk=instance.pk)
        plans = list(
            RecruitmentAutomationPlan.objects.filter(job__boss_account=locked).order_by("job_id")
        )
        for plan in plans:
            _stop_plan_for_lifecycle(plan=plan, actor=actor)
        locked = BossAccount.objects.select_for_update().get(pk=instance.pk)
    elif isinstance(instance, JobApplication):
        account_id = JobApplication.objects.filter(pk=instance.pk).values_list(
            "job__boss_account_id", flat=True
        ).get()
        if account_id:
            BossAccount.objects.select_for_update().get(pk=account_id)
        locked = (
            JobApplication.objects.select_for_update()
            .select_related("job__boss_account", "candidate")
            .get(pk=instance.pk)
        )
        if locked.archived_at is None:
            from recruitment.services.screening import invalidate_rejection_work_for_application

            invalidate_rejection_work_for_application(
                application=locked,
                actor=actor,
                trigger="application_archived",
            )
    elif isinstance(instance, RecruitmentJob):
        account_id = RecruitmentJob.objects.filter(pk=instance.pk).values_list(
            "boss_account_id", flat=True
        ).get()
        if account_id:
            BossAccount.objects.select_for_update().get(pk=account_id)
        _stop_job_plan_for_lifecycle(job_id=instance.pk, actor=actor)
        locked = RecruitmentJob.objects.select_for_update().get(pk=instance.pk)
        applications = list(
            JobApplication.objects.select_for_update()
            .select_related("job__boss_account", "candidate")
            .filter(job=locked)
            .order_by("pk")
        )
        if locked.archived_at is None:
            from recruitment.services.screening import invalidate_rejection_work_for_application

            for application in applications:
                invalidate_rejection_work_for_application(
                    application=application,
                    actor=actor,
                    trigger="job_archived",
                )
    elif isinstance(instance, Candidate):
        account_ids = sorted({
            value for value in Candidate.objects.filter(pk=instance.pk).values_list(
                "applications__job__boss_account_id", flat=True
            ) if value is not None
        })
        list(BossAccount.objects.select_for_update().filter(pk__in=account_ids).order_by("pk"))
        locked = Candidate.objects.select_for_update().get(pk=instance.pk)
        applications = list(
            JobApplication.objects.select_for_update()
            .select_related("job__boss_account", "candidate")
            .filter(candidate=locked)
            .order_by("pk")
        )
        if locked.archived_at is None:
            from recruitment.services.screening import invalidate_rejection_work_for_application

            for application in applications:
                invalidate_rejection_work_for_application(
                    application=application,
                    actor=actor,
                    trigger="candidate_archived",
                )
    else:
        locked = type(instance).objects.select_for_update().get(pk=instance.pk)
    if locked.archived_at:
        return locked
    if isinstance(locked, BossAccount):
        if locked.rpa_tasks.filter(
            status__in=ACTIVE_TASK_STATUSES,
            automation_plan_revision__isnull=True,
        ).exists():
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
    elif isinstance(locked, RecruitmentAutomationPlan):
        from recruitment.services.automation_plans import effective_plan_state

        current_state = effective_plan_state(locked)
        if current_state not in {"stopped", "failed", "completed", "cancelled"}:
            raise LifecycleConflict("任务仍在运行、暂停、等待人工或安全收尾，请先停止并等待结束")
        if RpaTask.objects.filter(
            automation_plan_revision__plan=locked,
            status__in=ACTIVE_TASK_STATUSES,
        ).exists():
            raise LifecycleConflict("任务仍有执行项正在处理，请等待安全收尾后再删除")
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


@serialize_sqlite_lifecycle
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
