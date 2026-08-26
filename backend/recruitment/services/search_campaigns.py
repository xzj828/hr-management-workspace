import hashlib
import json
from datetime import timedelta

from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError

from attendance.permissions import is_hr_user
from recruitment.models import (
    AutomationApproval,
    AutomationEvidence,
    AutomationUsage,
    RecruitmentAuditLog,
    RpaTask,
    SearchCampaign,
    WorkflowNodeRun,
)
from recruitment.rpa.tasks import append_event, create_task
from recruitment.services.usage import consume


def _campaign_snapshot(campaign, *, workflow_node_run_id=None):
    return {
        "campaign_id": campaign.pk,
        "boss_account_id": campaign.boss_account_id,
        "job": campaign.job_id,
        "job_title": campaign.job.title,
        "source": campaign.source,
        "criteria": json.loads(json.dumps(campaign.criteria or {}, ensure_ascii=False)),
        "target_resume_count": campaign.target_resume_count,
        "max_scan_count": campaign.max_scan_count,
        "resume_view_budget": campaign.max_scan_count,
        "estimated_consumption": {
            AutomationUsage.Metric.SEARCH: 1,
            AutomationUsage.Metric.RESUME_VIEW: campaign.max_scan_count,
        },
        **({"workflow_node_run_id": workflow_node_run_id} if workflow_node_run_id else {}),
    }


def _ensure_authorized(campaign, actor):
    if actor.is_superuser:
        return
    if not is_hr_user(actor) or not campaign.boss_account.authorized_users.filter(pk=actor.pk).exists():
        raise PermissionDenied("无权操作该 BOSS 账号")


@transaction.atomic
def prepare_search_campaign(*, campaign, actor, workflow_node_run=None):
    locked = (
        SearchCampaign.objects.select_for_update()
        .select_related("boss_account", "job")
        .get(pk=campaign.pk)
    )
    _ensure_authorized(locked, actor)
    if locked.status == SearchCampaign.Status.PAUSED:
        raise ValidationError("暂停中的主动寻访当前不支持恢复，请新建任务")
    if locked.status not in {
        SearchCampaign.Status.DRAFT,
        SearchCampaign.Status.FAILED,
    }:
        raise ValidationError("当前主动寻访任务不能生成确认")
    if locked.max_scan_count < locked.target_resume_count:
        raise ValidationError("最大扫描人数不能小于目标简历数")
    if workflow_node_run is not None:
        if locked.workflow_run_id is None or workflow_node_run.run_id != locked.workflow_run_id:
            raise ValidationError("主动寻访任务与流程节点不匹配")
        workflow_node_run_id = workflow_node_run.pk
    else:
        workflow_node_run_id = None
    payload = _campaign_snapshot(locked, workflow_node_run_id=workflow_node_run_id)
    digest = hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()[:24]
    approval, _ = AutomationApproval.objects.get_or_create(
        idempotency_key=f"search-pull:{locked.pk}:{actor.pk}:{digest}",
        defaults={
            "action": AutomationApproval.Action.SEARCH_AND_PULL_RESUMES,
            "boss_account": locked.boss_account,
            "created_by": actor,
            "payload": payload,
            "item_count": payload["resume_view_budget"],
            "expires_at": timezone.now() + timedelta(minutes=30),
        },
    )
    return approval


def _workflow_node_from_snapshot(campaign, payload):
    node_id = payload.get("workflow_node_run_id")
    if not node_id:
        return None
    node = WorkflowNodeRun.objects.select_related("run").filter(pk=node_id).first()
    if node is None or campaign.workflow_run_id is None or node.run_id != campaign.workflow_run_id:
        raise ValidationError("已确认的流程节点范围无效")
    return node


@transaction.atomic
def start_search_campaign(*, campaign, actor, approval, idempotency_key=""):
    locked = (
        SearchCampaign.objects.select_for_update()
        .select_related("boss_account", "job")
        .get(pk=campaign.pk)
    )
    _ensure_authorized(locked, actor)
    approved = AutomationApproval.objects.select_for_update().filter(pk=approval.pk).first()
    if (
        approved is None
        or approved.action != AutomationApproval.Action.SEARCH_AND_PULL_RESUMES
        or approved.boss_account_id != locked.boss_account_id
        or approved.status != AutomationApproval.Status.APPROVED
        or approved.approved_by_id != actor.pk
    ):
        raise ValidationError("主动寻访确认记录无效")
    if approved.expires_at and approved.expires_at <= timezone.now():
        raise ValidationError("主动寻访确认记录已过期")
    payload = approved.payload if isinstance(approved.payload, dict) else {}
    workflow_node_run = _workflow_node_from_snapshot(locked, payload)
    if payload != _campaign_snapshot(
        locked,
        workflow_node_run_id=workflow_node_run.pk if workflow_node_run else None,
    ):
        raise ValidationError("主动寻访配置已变化，请重新确认")
    if approved.item_count != payload.get("resume_view_budget"):
        raise ValidationError("主动寻访查看额度快照无效")
    if locked.status == SearchCampaign.Status.PAUSED:
        raise ValidationError("暂停中的主动寻访当前不支持恢复，请新建任务")

    task_key = idempotency_key or f"search-campaign:{locked.pk}:approval:{approved.pk}"
    existing = RpaTask.objects.filter(idempotency_key=task_key).first()
    if existing is not None:
        if existing.approval_id != approved.pk or existing.boss_account_id != locked.boss_account_id:
            raise ValidationError("主动寻访任务幂等标识冲突")
        return existing
    if locked.status not in {
        SearchCampaign.Status.DRAFT,
        SearchCampaign.Status.FAILED,
    }:
        raise ValidationError("当前主动寻访任务不能启动")

    # Reserve the whole approved budget atomically. The worker may not open more
    # resumes than this value, including failed preview attempts.
    consume(account=locked.boss_account, metric=AutomationUsage.Metric.SEARCH, amount=1)
    consume(
        account=locked.boss_account,
        metric=AutomationUsage.Metric.RESUME_VIEW,
        amount=payload["resume_view_budget"],
    )
    task = create_task(
        account=locked.boss_account,
        action=RpaTask.Action.SEARCH_AND_PULL_RESUMES,
        actor=actor,
        approval=approved,
        workflow_node_run=workflow_node_run,
        request_payload=payload,
        idempotency_key=task_key,
        creation_path="search_campaign",
    )
    locked.status = SearchCampaign.Status.QUEUED
    locked.stop_reason = SearchCampaign.StopReason.NONE
    locked.error_message = ""
    locked.save(update_fields=["status", "stop_reason", "error_message", "updated_at"])
    return task


@transaction.atomic
def stop_search_campaign(*, campaign):
    locked = SearchCampaign.objects.select_for_update().get(pk=campaign.pk)
    if locked.status in {SearchCampaign.Status.SUCCEEDED, SearchCampaign.Status.CANCELLED}:
        return locked
    tasks = RpaTask.objects.select_for_update().filter(
        request_payload__campaign_id=locked.pk,
    )
    active_tasks = list(
        tasks.filter(status__in=[RpaTask.Status.LEASED, RpaTask.Status.RUNNING])
    )
    for task in active_tasks:
        if task.status == RpaTask.Status.CANCEL_REQUESTED:
            continue
        task.status = RpaTask.Status.CANCEL_REQUESTED
        task.save(update_fields=["status", "updated_at"])
        append_event(
            task=task,
            event="cancel_requested",
            message="用户停止主动寻访，已通知本机 Worker 中断当前任务",
            data={"status": task.status},
        )
    now = timezone.now()
    workflow_tasks = {}
    for task in tasks.filter(status=RpaTask.Status.PENDING):
        try:
            reserved = int(task.request_payload.get("resume_view_budget", 0) or 0)
        except (TypeError, ValueError):
            reserved = 0
        usage = {
            "metric": AutomationUsage.Metric.RESUME_VIEW,
            "search_reserved": 1,
            "reserved": reserved,
            "actual_known": True,
            "actual_unknown": False,
            "actual": 0,
            "unused": reserved,
            "unused_disposition": "retained_no_refund",
            "final_status": RpaTask.Status.CANCELLED,
            "campaign_id": locked.pk,
            "failure_code": "cancelled_by_user",
            "evidence_untrusted": False,
        }
        AutomationEvidence.objects.update_or_create(
            task=task,
            kind="resume_preview_attempts",
            defaults={
                "summary": "任务在执行前取消，无在线简历查看尝试",
                "metadata": {
                    "campaign_id": locked.pk,
                    "final_status": RpaTask.Status.CANCELLED,
                    "failure_code": "cancelled_by_user",
                    "attempts": [],
                    "actual_preview_attempts": 0,
                    "actual_known": True,
                    "actual_unknown": False,
                    "evidence_untrusted": False,
                },
            },
        )
        AutomationEvidence.objects.update_or_create(
            task=task,
            kind="resume_view_usage",
            defaults={"summary": "主动寻访取消后的在线简历查看额度对账", "metadata": usage},
        )
        task.status = RpaTask.Status.CANCELLED
        task.result = {"campaign_id": locked.pk, "resume_view_usage": usage}
        task.error_code = "cancelled_by_user"
        task.error_message = "主动寻访由用户在执行前停止"
        task.completed_at = now
        task.lease_expires_at = None
        task.save(update_fields=[
            "status", "result", "error_code", "error_message", "completed_at",
            "lease_expires_at", "updated_at",
        ])
        append_event(
            task=task,
            event="cancelled",
            message="主动寻访在执行前停止，预留额度不退款并已完成对账",
            data={"status": task.status, "unused_disposition": "retained_no_refund"},
        )
        if task.workflow_node_run_id:
            workflow_tasks[task.workflow_node_run_id] = task.pk
    if active_tasks:
        # 运行中任务已请求取消，等待 Worker 回执后再收敛 campaign 状态。
        return locked
    locked.status = SearchCampaign.Status.CANCELLED
    locked.stop_reason = SearchCampaign.StopReason.USER_STOPPED
    locked.completed_at = now
    locked.save(update_fields=["status", "stop_reason", "completed_at", "updated_at"])
    for task_id in workflow_tasks.values():
        def resume_workflow(completed_task_id=task_id):
            from recruitment.services.workflow_nodes import resume_workflow_for_task
            resume_workflow_for_task(RpaTask.objects.get(pk=completed_task_id))

        transaction.on_commit(resume_workflow)
    return locked


@transaction.atomic
def fail_stale_search_campaign_task(*, task, observed_at, account_status):
    """Fail a stale search/pull task and all of its domain state atomically."""
    locked_task = (
        RpaTask.objects.select_for_update()
        .select_related("boss_account", "approval")
        .get(pk=task.pk)
    )
    if (
        locked_task.action != RpaTask.Action.SEARCH_AND_PULL_RESUMES
        or locked_task.status not in {RpaTask.Status.LEASED, RpaTask.Status.RUNNING}
    ):
        return False

    payload = locked_task.request_payload if isinstance(locked_task.request_payload, dict) else {}
    campaign = SearchCampaign.objects.select_for_update().filter(
        pk=payload.get("campaign_id"),
        boss_account=locked_task.boss_account,
    ).first()
    approval = locked_task.approval
    if (
        approval is not None
        and approval.action == AutomationApproval.Action.SEARCH_AND_PULL_RESUMES
        and approval.boss_account_id == locked_task.boss_account_id
    ):
        reserved = approval.item_count
    else:
        try:
            reserved = int(payload.get("resume_view_budget", 0) or 0)
        except (TypeError, ValueError):
            reserved = 0
    reserved = max(0, reserved)
    campaign_id = campaign.pk if campaign is not None else payload.get("campaign_id")
    common = {
        "campaign_id": campaign_id,
        "final_status": RpaTask.Status.FAILED,
        "failure_code": "worker_lease_expired",
        "actual_known": False,
        "actual_unknown": True,
        "evidence_untrusted": True,
    }
    AutomationEvidence.objects.update_or_create(
        task=locked_task,
        kind="resume_preview_attempts",
        defaults={
            "summary": "Worker 租约过期，未采信任何在线简历查看回执",
            "metadata": {
                **common,
                "attempts": [],
                "scanned_count": None,
                "actual_preview_attempts": None,
            },
        },
    )
    usage = {
        **common,
        "metric": AutomationUsage.Metric.RESUME_VIEW,
        "search_reserved": 1,
        "reserved": reserved,
        "actual": None,
        "unused": None,
        "unused_disposition": "retained_no_refund",
    }
    AutomationEvidence.objects.update_or_create(
        task=locked_task,
        kind="resume_view_usage",
        defaults={
            "summary": "主动寻访 Worker 租约过期后的在线简历查看额度对账",
            "metadata": usage,
        },
    )

    if campaign is not None:
        campaign.status = SearchCampaign.Status.FAILED
        campaign.stop_reason = SearchCampaign.StopReason.ERROR
        campaign.error_message = "Worker 租约过期，主动寻访已安全终止"
        campaign.completed_at = observed_at
        campaign.save(update_fields=[
            "status", "stop_reason", "error_message", "completed_at", "updated_at",
        ])

    previous_status = locked_task.status
    locked_task.status = RpaTask.Status.FAILED
    locked_task.worker = None
    locked_task.lease_expires_at = None
    locked_task.completed_at = observed_at
    locked_task.error_code = "worker_lease_expired"
    locked_task.error_message = "Worker 失联或任务长时间没有进度，主动寻访已安全终止"
    locked_task.result = {
        "campaign_id": campaign_id,
        "resume_view_usage": {
            "reserved": reserved,
            "actual_known": False,
            "actual": None,
            "unused": None,
            "unused_disposition": "retained_no_refund",
        },
    }
    locked_task.save(update_fields=[
        "status", "worker", "lease_expires_at", "completed_at", "error_code",
        "error_message", "result", "updated_at",
    ])
    append_event(
        task=locked_task,
        level="error",
        event="worker_lease_expired",
        message="Worker 租约过期，主动寻访任务与额度账本已安全终结",
        data={"status": locked_task.status, "failure_code": locked_task.error_code},
    )
    RecruitmentAuditLog.objects.create(
        boss_account=locked_task.boss_account,
        action="task_recovered_after_worker_timeout",
        target_id=str(locked_task.pk),
        detail={"previous_status": previous_status, "error_code": locked_task.error_code},
    )
    account = locked_task.boss_account
    account.status = account_status
    account.save(update_fields=["status", "updated_at"])

    if locked_task.workflow_node_run_id:
        task_id = locked_task.pk

        def resume_workflow():
            from recruitment.services.workflow_nodes import resume_workflow_for_task
            resume_workflow_for_task(RpaTask.objects.get(pk=task_id))

        transaction.on_commit(resume_workflow)
    return True
