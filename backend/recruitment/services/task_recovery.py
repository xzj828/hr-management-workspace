from dataclasses import dataclass

from django.db import transaction
from django.utils import timezone

from recruitment.models import (
    BossAccount,
    JobApplication,
    RecruitmentAuditLog,
    RecruitmentAutomationPlan,
    RpaTask,
    RpaTaskEvent,
)
from recruitment.services.search_campaigns import fail_stale_search_campaign_task
from recruitment.services.sqlite_lifecycle import serialize_sqlite_lifecycle


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


@serialize_sqlite_lifecycle
@transaction.atomic
def recover_stale_tasks(*, now=None):
    observed_at = now or timezone.now()
    expired_snapshots = list(
        RpaTask.objects
        .filter(
            status__in=[RpaTask.Status.LEASED, RpaTask.Status.RUNNING],
            lease_expires_at__lt=observed_at,
        )
        .order_by("created_at")
        .values(
            "pk", "boss_account_id", "action", "request_payload",
            "automation_plan_revision_id",
        )
    )
    def is_scoped_sync(row):
        payload = row["request_payload"] if isinstance(row["request_payload"], dict) else {}
        return (
            row["action"] == RpaTask.Action.SYNC_CONVERSATIONS
            and isinstance(payload.get("passive_plan_scopes"), dict)
        )

    ordinary_ids = [
        row["pk"] for row in expired_snapshots
        if row["action"] != RpaTask.Action.REJECTION_NOTICE
        and row["automation_plan_revision_id"] is None
        and not is_scoped_sync(row)
    ]
    # Preserve the established task -> account order for ordinary automation.
    ordinary_tasks = list(
        RpaTask.objects.select_for_update()
        .filter(
            pk__in=ordinary_ids,
            status__in=[RpaTask.Status.LEASED, RpaTask.Status.RUNNING],
            lease_expires_at__lt=observed_at,
        )
        .order_by("created_at")
    )
    requeued = 0
    failed = 0
    for task in ordinary_tasks:
        account = BossAccount.objects.select_for_update().get(pk=task.boss_account_id)
        if task.action == RpaTask.Action.SEARCH_AND_PULL_RESUMES:
            if fail_stale_search_campaign_task(
                task=task,
                observed_at=observed_at,
                account_status=_account_idle_status(account),
            ):
                failed += 1
            continue

        if task.status == RpaTask.Status.LEASED:
            task.status = RpaTask.Status.PENDING
            task.worker = None
            task.lease_expires_at = None
            task.lease_token = None
            task.save(update_fields=["status", "worker", "lease_expires_at", "lease_token", "updated_at"])
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
            task.lease_token = None
            task.completed_at = observed_at
            task.error_code = "worker_lease_expired"
            task.error_message = "Worker 失联或任务长时间没有进度，系统已结束本次执行"
            task.save(
                update_fields=[
                    "status", "worker", "lease_expires_at", "lease_token", "completed_at",
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

    scoped_sync_snapshots = [
        row for row in expired_snapshots
        if row["automation_plan_revision_id"] is None and is_scoped_sync(row)
    ]
    for row in scoped_sync_snapshots:
        payload = row["request_payload"]
        scopes = payload.get("passive_plan_scopes") or {}
        job_ids = sorted({int(value) for value in scopes if str(value).isdigit()})
        account = BossAccount.objects.select_for_update().get(pk=row["boss_account_id"])
        list(
            RecruitmentAutomationPlan.objects.select_for_update()
            .filter(job_id__in=job_ids)
            .order_by("job_id")
        )
        task = (
            RpaTask.objects.select_for_update()
            .filter(
                pk=row["pk"],
                status__in=[RpaTask.Status.LEASED, RpaTask.Status.RUNNING],
                lease_expires_at__lt=observed_at,
            )
            .first()
        )
        if task is None:
            continue
        if task.status == RpaTask.Status.LEASED:
            task.status = RpaTask.Status.PENDING
            task.worker = None
            task.lease_expires_at = None
            task.lease_token = None
            task.save(update_fields=[
                "status", "worker", "lease_expires_at", "lease_token", "updated_at",
            ])
            RpaTaskEvent.objects.create(
                task=task,
                level="warning",
                event="lease_expired",
                message="Worker 未及时开始消息同步，任务已重新排队",
            )
            requeued += 1
        else:
            task.status = RpaTask.Status.FAILED
            task.worker = None
            task.lease_expires_at = None
            task.lease_token = None
            task.completed_at = observed_at
            task.error_code = "worker_lease_expired"
            task.error_message = "Worker 失联或消息同步长时间没有进度，系统已结束本次执行"
            task.save(update_fields=[
                "status", "worker", "lease_expires_at", "lease_token", "completed_at",
                "error_code", "error_message", "updated_at",
            ])
            RpaTaskEvent.objects.create(
                task=task,
                level="error",
                event="worker_lease_expired",
                message="Worker 失联，消息同步任务已自动结束",
            )
            failed += 1
        account.status = _account_idle_status(account)
        account.save(update_fields=["status", "updated_at"])

    plan_snapshots = [
        row for row in expired_snapshots
        if row["automation_plan_revision_id"] is not None
    ]
    for row in plan_snapshots:
        account = BossAccount.objects.select_for_update().get(pk=row["boss_account_id"])
        plan = RecruitmentAutomationPlan.objects.select_for_update().get(
            revisions__pk=row["automation_plan_revision_id"],
        )
        task = (
            RpaTask.objects.select_for_update()
            .filter(
                pk=row["pk"],
                status__in=[RpaTask.Status.LEASED, RpaTask.Status.RUNNING],
                lease_expires_at__lt=observed_at,
            )
            .first()
        )
        if task is None:
            continue
        from recruitment.services.automation_plans import plan_fence_is_current

        fence_current = plan_fence_is_current(
            revision_id=task.automation_plan_revision_id,
            generation=task.automation_generation,
        )
        if task.action == RpaTask.Action.SEARCH_AND_PULL_RESUMES:
            if fail_stale_search_campaign_task(
                task=task,
                observed_at=observed_at,
                account_status=_account_idle_status(account),
                user_stopped=not fence_current,
            ):
                failed += 1
            continue
        if task.status == RpaTask.Status.LEASED:
            task.status = RpaTask.Status.PENDING if fence_current else RpaTask.Status.CANCELLED
            task.worker = None
            task.lease_expires_at = None
            task.lease_token = None
            if not fence_current:
                task.completed_at = observed_at
                task.error_code = "automation_plan_stopped"
                task.error_message = "招聘自动化方案已停止，过期租约不会重新排队"
            task.save(update_fields=[
                "status", "worker", "lease_expires_at", "lease_token", "completed_at",
                "error_code", "error_message", "updated_at",
            ])
            RpaTaskEvent.objects.create(
                task=task,
                level="warning",
                event="lease_expired" if fence_current else "automation_plan_stopped",
                message=(
                    "Worker 未及时开始任务，任务已重新排队"
                    if fence_current
                    else "招聘自动化方案已停止，过期租约已取消"
                ),
            )
            if fence_current:
                requeued += 1
        elif task.action in {
            RpaTask.Action.GREET,
            RpaTask.Action.REQUEST_RESUME,
            RpaTask.Action.SEND_INTERVIEW,
        }:
            from recruitment.services.communications import complete_communication_task

            complete_communication_task(
                task=task,
                status=RpaTask.Status.WAITING_HUMAN,
                result={},
                error_code="external_result_uncertain",
                error_message="Worker 在外部动作执行期间失联，发送结果不确定，剩余动作已停止",
            )
            task.worker = None
            task.lease_token = None
            task.save(update_fields=["worker", "lease_token", "updated_at"])
            account.status = BossAccount.Status.PAUSED
            account.save(update_fields=["status", "updated_at"])
            RecruitmentAuditLog.objects.create(
                boss_account=account,
                action="communication_stopped_after_worker_timeout",
                target_id=str(task.pk),
                detail={
                    "error_code": "external_result_uncertain",
                    "cause": "worker_lease_expired",
                    "automation_plan_id": plan.pk,
                },
            )
            failed += 1
            continue
        else:
            task.status = RpaTask.Status.FAILED
            task.worker = None
            task.lease_expires_at = None
            task.lease_token = None
            task.completed_at = observed_at
            task.error_code = "worker_lease_expired"
            task.error_message = "Worker 失联或任务长时间没有进度，系统已结束本次执行"
            task.save(update_fields=[
                "status", "worker", "lease_expires_at", "lease_token", "completed_at",
                "error_code", "error_message", "updated_at",
            ])
            RpaTaskEvent.objects.create(
                task=task,
                level="error",
                event="worker_lease_expired",
                message="Worker 失联，任务已自动结束，可由 HR 重新执行",
            )
            failed += 1
        account.status = _account_idle_status(account)
        account.save(update_fields=["status", "updated_at"])

    rejection_snapshots = [
        row for row in expired_snapshots
        if row["action"] == RpaTask.Action.REJECTION_NOTICE
        and row["automation_plan_revision_id"] is None
    ]
    # Rejection decisions and stage changes use account -> application -> task.
    rejection_account_ids = sorted({row["boss_account_id"] for row in rejection_snapshots})
    locked_accounts = {
        account.pk: account
        for account in BossAccount.objects.select_for_update()
        .filter(pk__in=rejection_account_ids)
        .order_by("pk")
    }
    rejection_application_ids = []
    for row in rejection_snapshots:
        payload = row["request_payload"] if isinstance(row["request_payload"], dict) else {}
        target = payload.get("target") if isinstance(payload.get("target"), dict) else {}
        application_id = target.get("application_id")
        if str(application_id).isdigit():
            rejection_application_ids.append(int(application_id))
    list(
        JobApplication.objects.select_for_update()
        .filter(pk__in=sorted(set(rejection_application_ids)))
        .order_by("pk")
    )
    rejection_tasks = list(
        RpaTask.objects.select_for_update()
        .filter(
            pk__in=[row["pk"] for row in rejection_snapshots],
            status__in=[RpaTask.Status.LEASED, RpaTask.Status.RUNNING],
            lease_expires_at__lt=observed_at,
        )
        .order_by("created_at")
    )
    for task in rejection_tasks:
        account = locked_accounts[task.boss_account_id]
        if task.status == RpaTask.Status.RUNNING:
            from recruitment.services.communications import complete_communication_task

            complete_communication_task(
                task=task,
                status=RpaTask.Status.WAITING_HUMAN,
                result={},
                error_code="external_result_uncertain",
                error_message="Worker 在外部动作执行期间失联，发送结果不确定，剩余通知已停止",
            )
            account.status = BossAccount.Status.PAUSED
            account.save(update_fields=["status", "updated_at"])
            RecruitmentAuditLog.objects.create(
                boss_account=account,
                action="rejection_notice_stopped_after_worker_timeout",
                target_id=str(task.pk),
                detail={
                    "error_code": "external_result_uncertain",
                    "cause": "worker_lease_expired",
                },
            )
            failed += 1
            continue
        if task.status == RpaTask.Status.LEASED:
            task.status = RpaTask.Status.PENDING
            task.worker = None
            task.lease_expires_at = None
            task.lease_token = None
            task.save(update_fields=["status", "worker", "lease_expires_at", "lease_token", "updated_at"])
            RpaTaskEvent.objects.create(
                task=task,
                level="warning",
                event="lease_expired",
                message="Worker 未及时开始任务，任务已重新排队",
            )
            requeued += 1

        account.status = _account_idle_status(account)
        account.save(update_fields=["status", "updated_at"])

    return TaskRecoveryResult(requeued_leases=requeued, failed_running=failed)
