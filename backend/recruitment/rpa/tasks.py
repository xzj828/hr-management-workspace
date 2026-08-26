from datetime import timedelta
from functools import wraps
import threading

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import APIException, PermissionDenied, ValidationError

from attendance.permissions import is_hr_user
from recruitment.models import (
    AutomationApproval,
    BossAccount,
    ConversationAction,
    RecruitmentAuditLog,
    RpaTask,
    RpaTaskEvent,
    RpaWorker,
    SearchCampaign,
    WorkflowNodeRun,
    WorkflowRun,
)
from recruitment.rpa.capabilities import REGISTRY
from recruitment.services.usage import consume


COMMUNICATION_ACTIONS = {
    RpaTask.Action.GREET,
    RpaTask.Action.REQUEST_RESUME,
    RpaTask.Action.SEND_INTERVIEW,
}
IDENTITY_SNAPSHOT_FIELDS = {
    "boss_account_id",
    "candidate_id",
    "application_id",
    "name",
    "external_id",
    "fingerprint",
    "job_id",
    "job_title",
    "verification",
}
GENERIC_CREATE_ACTIONS = frozenset({
    RpaTask.Action.CHECK_STATUS,
    RpaTask.Action.SYNC_POSITIONS,
    RpaTask.Action.SYNC_CONVERSATIONS,
})
APPROVAL_CREATION_PATHS = {
    RpaTask.Action.GREET: "communication_batch",
    RpaTask.Action.REQUEST_RESUME: "communication_batch",
    RpaTask.Action.SEND_INTERVIEW: "communication_batch",
    RpaTask.Action.VIEW_ONLINE_RESUME: "view_online_resume_approval",
    RpaTask.Action.DEEP_MATCH: "deep_match_approval",
    RpaTask.Action.SEARCH_AND_PULL_RESUMES: "search_campaign",
}
_creation_locks = {}
_creation_locks_guard = threading.Lock()


def _serialize_account_task_creation(function):
    @wraps(function)
    def wrapped(*args, **kwargs):
        account = kwargs.get("account")
        account_id = getattr(account, "pk", None)
        with _creation_locks_guard:
            lock = _creation_locks.setdefault(account_id, threading.Lock())
        with lock:
            return function(*args, **kwargs)

    return wrapped


class RpaRuntimeUnavailable(APIException):
    status_code = 409
    default_code = "rpa_runtime_unavailable"
    default_detail = "本机自动化运行时不可用"


def latest_rpa_worker():
    worker = RpaWorker.objects.filter(last_seen_at__isnull=False).order_by("-last_seen_at").first()
    return worker or RpaWorker.objects.order_by("-updated_at").first()


def rpa_worker_is_online(worker, *, now=None):
    if worker is None or worker.status != RpaWorker.Status.ONLINE or worker.last_seen_at is None:
        return False
    ttl_seconds = max(int(getattr(settings, "RPA_WORKER_HEARTBEAT_TTL_SECONDS", 45)), 1)
    return worker.last_seen_at >= (now or timezone.now()) - timedelta(seconds=ttl_seconds)


def _require_open_login_runtime():
    worker = latest_rpa_worker()
    if not rpa_worker_is_online(worker):
        raise RpaRuntimeUnavailable("本机 RPA Worker 未连接或心跳已过期，请先启动 Worker")
    capabilities = worker.capabilities if isinstance(worker.capabilities, dict) else {}
    if capabilities.get("boss_cli") is not True:
        message = "BOSS CLI 不可用，请检查 Worker 安装与配置"
        cli_error = capabilities.get("boss_cli_error")
        if isinstance(cli_error, dict) and cli_error.get("message"):
            message = f"{message}：{str(cli_error['message'])[:300]}"
        raise RpaRuntimeUnavailable(message)


def append_event(*, task, event, message, data=None, level="info"):
    return RpaTaskEvent.objects.create(
        task=task,
        event=event,
        message=message,
        data=data or {},
        level=level,
    )


def _ensure_authorized(account, actor):
    if actor.is_superuser:
        return
    if not is_hr_user(actor) or not account.authorized_users.filter(pk=actor.pk).exists():
        raise PermissionDenied("无权操作该 BOSS 账号")


def _validate_approved_request(*, action, approval, request_payload):
    """Bind execution fields to the immutable payload the HR actually approved."""
    payload = request_payload if isinstance(request_payload, dict) else {}
    snapshot = approval.payload if isinstance(approval.payload, dict) else {}
    if action in COMMUNICATION_ACTIONS:
        if snapshot.get("action") != action or payload.get("message") != snapshot.get("message"):
            raise ValidationError("自动化任务与已确认沟通快照不一致")
        action_id = str(payload.get("conversation_action_id", ""))
        item = next(
            (
                value
                for value in snapshot.get("items", [])
                if isinstance(value, dict) and str(value.get("conversation_action_id", "")) == action_id
            ),
            None,
        )
        if item is None:
            raise ValidationError("自动化任务目标不在已确认范围内")
        expected_target = {key: item.get(key) for key in IDENTITY_SNAPSHOT_FIELDS if key in item}
        if payload.get("target") != expected_target:
            raise ValidationError("自动化任务目标与已确认身份快照不一致")
        if action == RpaTask.Action.REQUEST_RESUME and bool(payload.get("first_contact")) != bool(
            item.get("first_contact")
        ):
            raise ValidationError("求简历联系方式与已确认快照不一致")
    elif action == RpaTask.Action.VIEW_ONLINE_RESUME:
        if (
            payload.get("application_id") != snapshot.get("application_id")
            or payload.get("target") != snapshot.get("target")
        ):
            raise ValidationError("在线简历任务与已确认快照不一致")
    elif action == RpaTask.Action.SEARCH_AND_PULL_RESUMES:
        if payload != snapshot:
            raise ValidationError("主动寻访任务与已确认配置快照不一致")
    elif action == RpaTask.Action.DEEP_MATCH:
        if (
            payload.get("job") != snapshot.get("job")
            or payload.get("job_title") != snapshot.get("job_title")
            or payload.get("core", []) != snapshot.get("core", [])
            or payload.get("bonus", []) != snapshot.get("bonus", [])
        ):
            raise ValidationError("深度匹配任务与已确认配置快照不一致")


def _validate_canonical_approval_linkage(
    *, action, approval, payload, execution_batch, workflow_node_run, idempotency_key, creation_path
):
    expected_path = APPROVAL_CREATION_PATHS.get(action)
    if creation_path != expected_path:
        raise ValidationError("批准型自动化必须通过对应的专用编排服务创建")
    if not idempotency_key:
        raise ValidationError("批准型自动化必须提供服务端生成的幂等标识")
    if action in COMMUNICATION_ACTIONS:
        action_id = str(payload.get("conversation_action_id", ""))
        if (
            execution_batch is None
            or execution_batch.approval_id != approval.pk
            or idempotency_key != f"communication-task:{action_id}"
            or not ConversationAction.objects.filter(
                pk=action_id,
                approval=approval,
                batch=execution_batch,
                action=action,
            ).exists()
        ):
            raise ValidationError("沟通任务与批准批次的规范关联无效")
        if RpaTask.objects.filter(
            approval=approval,
            request_payload__conversation_action_id=action_id,
        ).exclude(idempotency_key=idempotency_key).exists():
            raise ValidationError("该沟通目标已生成执行任务")
        return
    if action == RpaTask.Action.VIEW_ONLINE_RESUME:
        expected_key = f"online-resume-task:{approval.pk}"
    elif action == RpaTask.Action.DEEP_MATCH:
        snapshot = approval.payload if isinstance(approval.payload, dict) else {}
        snapshot_node_id = snapshot.get("workflow_node_run_id")
        if snapshot_node_id:
            expected_job_id = (
                workflow_node_run.run.job_id or workflow_node_run.run.input_snapshot.get("job")
                if workflow_node_run is not None
                else None
            )
            if (
                workflow_node_run is None
                or workflow_node_run.pk != snapshot_node_id
                or workflow_node_run.node_type != "deep_search"
                or workflow_node_run.run.boss_account_id != approval.boss_account_id
                or workflow_node_run.run.actor_id != approval.created_by_id
                or expected_job_id != payload.get("job")
                or workflow_node_run.attempt != snapshot.get("workflow_node_attempt")
            ):
                raise ValidationError("深度匹配任务与已确认流程节点不一致")
        elif workflow_node_run is not None:
            raise ValidationError("非流程深度匹配确认不能绑定流程节点")
        expected_key = f"deep-match-task:{approval.pk}"
    else:
        campaign_id = payload.get("campaign_id")
        campaign = SearchCampaign.objects.select_for_update().filter(
            pk=campaign_id,
            boss_account_id=approval.boss_account_id,
            status__in=[
                SearchCampaign.Status.DRAFT,
                SearchCampaign.Status.FAILED,
            ],
        ).first()
        if campaign is None:
            raise ValidationError("主动寻访 campaign 状态或账号关联无效")
        snapshot_node_id = payload.get("workflow_node_run_id")
        if snapshot_node_id:
            expected_job_id = (
                workflow_node_run.run.job_id or workflow_node_run.run.input_snapshot.get("job")
                if workflow_node_run is not None
                else None
            )
            if (
                workflow_node_run is None
                or workflow_node_run.pk != snapshot_node_id
                or workflow_node_run.node_type != "search_and_pull_resumes"
                or workflow_node_run.run.boss_account_id != approval.boss_account_id
                or workflow_node_run.run.actor_id != approval.created_by_id
                or expected_job_id != payload.get("job")
                or campaign.workflow_run_id != workflow_node_run.run_id
            ):
                raise ValidationError("主动寻访任务与已确认流程节点不一致")
        elif workflow_node_run is not None:
            raise ValidationError("非流程主动寻访确认不能绑定流程节点")
        expected_key = f"search-campaign:{campaign.pk}:approval:{approval.pk}"
    if idempotency_key != expected_key:
        raise ValidationError("批准型自动化幂等标识不是专用服务生成的规范值")
    if RpaTask.objects.filter(approval=approval).exclude(idempotency_key=idempotency_key).exists():
        raise ValidationError("该确认记录已生成执行任务，不能重复使用")


@_serialize_account_task_creation
@transaction.atomic
def create_task(
    *,
    account,
    action,
    actor,
    request_payload=None,
    approval=None,
    execution_batch=None,
    workflow_node_run=None,
    idempotency_key="",
    creation_path="internal",
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
    if creation_path == "generic" and action not in GENERIC_CREATE_ACTIONS:
        raise ValidationError("该自动化动作必须通过专用业务入口创建")
    if capability.requires_approval and action not in APPROVAL_CREATION_PATHS:
        raise ValidationError("该批准型自动化尚未配置安全创建路径")

    payload = request_payload if isinstance(request_payload, dict) else {}

    if workflow_node_run is not None:
        locked_workflow_node = (
            WorkflowNodeRun.objects.select_for_update()
            .select_related("run")
            .filter(pk=workflow_node_run.pk)
            .first()
        )
        if (
            locked_workflow_node is None
            or locked_workflow_node.run.boss_account_id != locked.pk
            or locked_workflow_node.status in {
                WorkflowNodeRun.Status.SUCCEEDED,
                WorkflowNodeRun.Status.FAILED,
                WorkflowNodeRun.Status.SKIPPED,
                WorkflowNodeRun.Status.CANCELLED,
            }
            or locked_workflow_node.run.status in {
                WorkflowRun.Status.PAUSED,
                WorkflowRun.Status.SUCCEEDED,
                WorkflowRun.Status.FAILED,
                WorkflowRun.Status.CANCELLED,
            }
        ):
            raise ValidationError("已结束或暂停的流程节点不能创建新的自动化任务")
        workflow_node_run = locked_workflow_node

    normalized_key = str(idempotency_key or "").strip()

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
        _validate_approved_request(
            action=action,
            approval=locked_approval,
            request_payload=payload,
        )
        _validate_canonical_approval_linkage(
            action=action,
            approval=locked_approval,
            payload=payload,
            execution_batch=execution_batch,
            workflow_node_run=workflow_node_run,
            idempotency_key=normalized_key,
            creation_path=creation_path,
        )
    elif approval is not None:
        locked_approval = AutomationApproval.objects.select_for_update().filter(pk=approval.pk).first()
        if (
            locked_approval is None
            or locked_approval.boss_account_id != locked.pk
            or locked_approval.action != action
            or locked_approval.status != AutomationApproval.Status.APPROVED
        ):
            raise ValidationError("自动化确认记录无效")

    if normalized_key:
        existing = RpaTask.objects.filter(idempotency_key=normalized_key).first()
        if existing:
            if (
                existing.boss_account_id != locked.pk
                or existing.created_by_id != actor.pk
                or existing.action != action
                or existing.approval_id != (locked_approval.pk if locked_approval else None)
                or existing.execution_batch_id != (execution_batch.pk if execution_batch else None)
                or existing.workflow_node_run_id != (workflow_node_run.pk if workflow_node_run else None)
                or existing.request_payload != payload
            ):
                raise ValidationError("幂等请求标识已被不同范围的任务使用")
            return (existing, False) if return_created else existing

    if action == RpaTask.Action.CHECK_STATUS:
        existing = locked.rpa_tasks.filter(
            action=RpaTask.Action.CHECK_STATUS,
            status__in=[RpaTask.Status.PENDING, RpaTask.Status.LEASED, RpaTask.Status.RUNNING],
        ).order_by("created_at").first()
        if existing:
            return (existing, False) if return_created else existing
    if action in GENERIC_CREATE_ACTIONS:
        _require_open_login_runtime()

    if locked.rpa_tasks.filter(status__in=[RpaTask.Status.LEASED, RpaTask.Status.RUNNING]).exists():
        raise ValidationError("该账号已有任务正在执行")

    if capability.consumes:
        consume(account=locked, metric=capability.consumes)

    task = RpaTask.objects.create(
        boss_account=locked,
        action=action,
        created_by=actor,
        approval=locked_approval,
        execution_batch=execution_batch,
        workflow_node_run=workflow_node_run,
        idempotency_key=normalized_key or None,
        request_payload=payload,
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
    if (
        locked.action not in GENERIC_CREATE_ACTIONS
        or locked.approval_id
        or locked.execution_batch_id
        or locked.workflow_node_run_id
    ):
        raise ValidationError("领域编排任务不能通过通用取消入口处理")
    if locked.status in {RpaTask.Status.CANCEL_REQUESTED, RpaTask.Status.CANCELLED}:
        return locked
    if locked.status not in {
        RpaTask.Status.PENDING,
        RpaTask.Status.LEASED,
        RpaTask.Status.RUNNING,
    }:
        raise ValidationError("当前任务不能取消")

    if locked.status == RpaTask.Status.PENDING:
        locked.status = RpaTask.Status.CANCELLED
        locked.completed_at = timezone.now()
        event = "cancelled"
        message = "任务已取消"
        update_fields = ["status", "completed_at", "updated_at"]
    else:
        locked.status = RpaTask.Status.CANCEL_REQUESTED
        event = "cancel_requested"
        message = "已通知本机 Worker 停止当前任务"
        update_fields = ["status", "updated_at"]
    locked.save(update_fields=update_fields)
    append_event(task=locked, event=event, message=message)
    RecruitmentAuditLog.objects.create(
        actor=actor,
        boss_account=locked.boss_account,
        action="task_cancel_requested" if locked.status == RpaTask.Status.CANCEL_REQUESTED else "task_cancelled",
        target_id=str(locked.pk),
    )
    return locked


def retry_task(*, task, actor):
    if task.status != RpaTask.Status.FAILED:
        raise ValidationError("只有失败任务可以重试")
    capability = REGISTRY.get(task.action)
    if (
        capability is None
        or capability.requires_approval
        or task.action not in GENERIC_CREATE_ACTIONS
        or task.approval_id
        or task.execution_batch_id
        or task.workflow_node_run_id
    ):
        raise ValidationError("领域编排任务不能通过通用重试入口重建")
    retried = create_task(
        account=task.boss_account,
        action=task.action,
        actor=actor,
        request_payload=task.request_payload,
    )
    append_event(task=retried, event="retried", message="由失败任务重试", data={"source_task_id": str(task.pk)})
    return retried
