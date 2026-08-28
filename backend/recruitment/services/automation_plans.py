import hashlib
import json
from dataclasses import dataclass

from django.db import transaction
from django.db.models import Max, Q
from django.utils import timezone
from rest_framework.exceptions import APIException, PermissionDenied, ValidationError

from attendance.permissions import is_hr_user
from recruitment.models import (
    AutomationApproval,
    BossAccount,
    ConversationAction,
    ExecutionBatch,
    HumanAttention,
    JobApplication,
    MessageSyncPolicy,
    RecruitmentAuditLog,
    RecruitmentAutomationPlan,
    RecruitmentAutomationPlanRevision,
    RecruitmentJob,
    RpaTask,
    SearchCampaign,
    StepExecution,
    WorkflowRun,
    WorkflowVersion,
)
from recruitment.rpa.tasks import append_event
from recruitment.services.standard_workflows import create_standard_workflow
from recruitment.services.job_standards import resolve_workbench_standard
from recruitment.services.sqlite_lifecycle import serialize_sqlite_lifecycle
from recruitment.services.workflow_nodes import execute_workflow_node
from recruitment.services.workflow_runtime import (
    RUN_TERMINAL_STATES,
    advance_run,
    cancel_run,
    create_run,
    pause_run,
    resume_run,
)
from recruitment.services.workflows import enable_version


class AutomationPlanConflict(APIException):
    status_code = 409
    default_code = "automation_plan_conflict"


@dataclass(frozen=True)
class PlanCommandResult:
    plan: RecruitmentAutomationPlan
    created: bool = False
    idempotent: bool = False


CANDIDATE_FILTER_ENUMS = {
    "activity": {"any", "just_active", "today", "within_3_days", "this_week", "this_month"},
    "gender": {"any", "male", "female"},
    "unseen_period": {"any", "within_14_days"},
    "colleague_resume_period": {"any", "within_30_days"},
    "school": {
        "any", "985", "211", "double_first_class", "overseas", "famous_global",
        "public_undergraduate",
    },
    "major": {
        "any", "journalism", "e_commerce", "business_admin", "public_admin",
        "management_science",
    },
    "job_stability": {"any", "fewer_than_3_in_5_years", "average_over_1_year"},
    "job_status": {
        "any", "left_immediately", "employed_not_considering", "employed_open",
        "employed_within_month",
    },
    "education": {
        "any", "junior_or_below", "technical", "high_school", "associate", "bachelor",
        "master", "doctorate",
    },
}
CANDIDATE_TALENT_KEYWORDS = {
    "data_analysis", "business_negotiation", "office_software", "kol", "new_media",
    "creator_resources", "business_cooperation", "social_media", "media_buying",
}


def normalize_candidate_filters(value):
    if value is None:
        value = {}
    if not isinstance(value, dict):
        raise ValidationError({"config": "主动寻访条件必须是对象"})
    age_min = value.get("age_min")
    age_max = value.get("age_max")
    if age_min is None and age_max is None:
        normalized_age_min = None
        normalized_age_max = None
    else:
        try:
            normalized_age_min = int(age_min)
            normalized_age_max = int(age_max)
        except (TypeError, ValueError) as exc:
            raise ValidationError({"config": "年龄范围必须同时填写整数最小值和最大值"}) from exc
        if (
            normalized_age_min < 18
            or normalized_age_max > 60
            or normalized_age_min > normalized_age_max
        ):
            raise ValidationError({"config": "年龄范围必须在 18 到 60 岁之间，且最小值不能大于最大值"})
    normalized = {
        "age_min": normalized_age_min,
        "age_max": normalized_age_max,
    }
    for key, allowed in CANDIDATE_FILTER_ENUMS.items():
        selected = str(value.get(key, "any")).strip()
        normalized[key] = selected if selected in allowed else "any"
    keywords = value.get("talent_keywords", [])
    if not isinstance(keywords, list):
        raise ValidationError({"config": "牛人关键词必须是数组"})
    normalized["talent_keywords"] = list(dict.fromkeys(
        str(item).strip() for item in keywords if str(item).strip() in CANDIDATE_TALENT_KEYWORDS
    ))[:len(CANDIDATE_TALENT_KEYWORDS)]
    return normalized


def _ensure_authorized(account, actor):
    if actor.is_superuser:
        return
    if not is_hr_user(actor) or not account.authorized_users.filter(pk=actor.pk).exists():
        raise PermissionDenied("无权操作该 BOSS 账号")


def _json_snapshot(value):
    try:
        return json.loads(json.dumps(value, ensure_ascii=False, sort_keys=True))
    except (TypeError, ValueError) as exc:
        raise ValidationError({"config": "执行方案必须是可序列化的 JSON 对象"}) from exc


def normalize_plan_config(kind, config):
    if not isinstance(config, dict):
        raise ValidationError({"config": "执行方案必须是对象"})
    raw = _json_snapshot(config)
    core = raw.get("core") if isinstance(raw.get("core"), list) else []
    bonus = raw.get("bonus") if isinstance(raw.get("bonus"), list) else []
    common = {
        "core": [str(item).strip()[:300] for item in core if str(item).strip()][:50],
        "bonus": [str(item).strip()[:300] for item in bonus if str(item).strip()][:50],
    }
    if kind == RecruitmentAutomationPlan.Kind.PASSIVE_RESUME:
        try:
            interval = int(raw.get("interval_minutes", 2))
        except (TypeError, ValueError) as exc:
            raise ValidationError({"config": "消息同步间隔必须是整数"}) from exc
        if interval < 1 or interval > 1440:
            raise ValidationError({"config": "消息同步间隔必须在 1 到 1440 分钟之间"})
        reply = str(raw.get("reply_message", "您好，这边是招聘岗位，方便发送一份简历进一步沟通吗？")).strip()
        if not reply or len(reply) > 1000:
            raise ValidationError({"config": "求简历话术必须为 1 到 1000 个字符"})
        return {**common, "interval_minutes": interval, "reply_message": reply}
    if kind != RecruitmentAutomationPlan.Kind.ACTIVE_RESUME_SEARCH:
        raise ValidationError({"kind": "不支持的招聘自动化方案"})
    try:
        target = int(raw.get("target_resume_count", 0))
        maximum = int(raw.get("max_scan_count", 0))
    except (TypeError, ValueError) as exc:
        raise ValidationError({"config": "目标合格简历数和 AI 最大分析份数必须是整数"}) from exc
    if target < 1 or maximum < target or maximum > 100:
        raise ValidationError({"config": "目标合格简历数至少为 1，AI 最大分析份数须不小于目标且不超过 100"})
    source = str(raw.get("source", "search")).strip()
    if source not in SearchCampaign.Source.values:
        raise ValidationError({"config": "主动寻访来源无效"})
    return {
        **common,
        "source": source,
        "keyword": str(raw.get("keyword", "")).strip()[:120],
        "candidate_filters": normalize_candidate_filters(raw.get("candidate_filters")),
        "target_resume_count": target,
        "max_scan_count": maximum,
    }


def _request_hash(*, job_id, kind, config, workflow_version_id):
    payload = {
        "job": job_id,
        "kind": kind,
        "config": config,
        "workflow_version": workflow_version_id,
    }
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _lock_job_and_account(job_id):
    snapshot = RecruitmentJob.objects.filter(pk=job_id).values("boss_account_id").first()
    if snapshot is None or snapshot["boss_account_id"] is None:
        raise ValidationError({"job": "职位不存在或尚未绑定 BOSS 账号"})
    account = BossAccount.objects.select_for_update().get(pk=snapshot["boss_account_id"])
    job = (
        RecruitmentJob.objects.select_for_update()
        .select_related("boss_account")
        .get(pk=job_id, boss_account=account)
    )
    return account, job


def refresh_message_sync_policy(*, account):
    """Project job-scoped passive subscriptions onto one technical account poller."""
    running = list(
        RecruitmentAutomationPlan.objects.filter(
            job__boss_account=account,
            job__archived_at__isnull=True,
            job__status=RecruitmentJob.Status.OPEN,
            kind=RecruitmentAutomationPlan.Kind.PASSIVE_RESUME,
            desired_state=RecruitmentAutomationPlan.DesiredState.RUNNING,
            current_revision__isnull=False,
        ).select_related("current_revision")
    )
    intervals = [
        int((item.current_revision.config_snapshot or {}).get("interval_minutes", 2))
        for item in running
    ]
    policy, _ = MessageSyncPolicy.objects.select_for_update().get_or_create(
        boss_account=account,
        defaults={"enabled": bool(running), "interval_minutes": min(intervals) if intervals else 2},
    )
    policy.enabled = bool(running)
    if intervals:
        policy.interval_minutes = min(intervals)
    policy.save(update_fields=["enabled", "interval_minutes", "updated_at"])
    return policy


def plan_fence_is_current(*, revision_id, generation, require_running=True):
    if revision_id is None or generation is None:
        return True
    states = [RecruitmentAutomationPlan.DesiredState.RUNNING] if require_running else list(
        RecruitmentAutomationPlan.DesiredState.values
    )
    return RecruitmentAutomationPlan.objects.filter(
        current_revision_id=revision_id,
        control_generation=generation,
        desired_state__in=states,
        job__status=RecruitmentJob.Status.OPEN,
        job__archived_at__isnull=True,
        job__boss_account__active=True,
        job__boss_account__archived_at__isnull=True,
    ).exists()


def assert_plan_fence_current(*, revision_id, generation, message="招聘自动化方案已暂停、停止或被新修订替代"):
    if not plan_fence_is_current(revision_id=revision_id, generation=generation):
        raise AutomationPlanConflict(message)


def current_passive_plan_for_sync(*, job_id, scopes):
    scope = (scopes or {}).get(str(job_id)) if isinstance(scopes, dict) else None
    if not isinstance(scope, dict):
        return None
    try:
        revision_id = int(scope.get("revision_id"))
        generation = int(scope.get("generation"))
    except (TypeError, ValueError):
        return None
    return (
        RecruitmentAutomationPlan.objects.select_related("current_revision", "current_run")
        .filter(
            job_id=job_id,
            kind=RecruitmentAutomationPlan.Kind.PASSIVE_RESUME,
            desired_state=RecruitmentAutomationPlan.DesiredState.RUNNING,
            current_revision_id=revision_id,
            control_generation=generation,
            job__archived_at__isnull=True,
            job__status=RecruitmentJob.Status.OPEN,
            job__boss_account__active=True,
            job__boss_account__archived_at__isnull=True,
        )
        .first()
    )


def message_sync_scopes_for_account(account):
    plans = RecruitmentAutomationPlan.objects.filter(
        job__boss_account=account,
        job__archived_at__isnull=True,
        job__status=RecruitmentJob.Status.OPEN,
        kind=RecruitmentAutomationPlan.Kind.PASSIVE_RESUME,
        desired_state=RecruitmentAutomationPlan.DesiredState.RUNNING,
        current_revision__isnull=False,
        job__boss_account__active=True,
        job__boss_account__archived_at__isnull=True,
    ).values("job_id", "job__title", "current_revision_id", "control_generation")
    return {
        str(item["job_id"]): {
            "job_title": item["job__title"],
            "revision_id": item["current_revision_id"],
            "generation": item["control_generation"],
        }
        for item in plans
    }


def effective_plan_state(plan):
    has_active_task = RpaTask.objects.filter(
        automation_plan_revision__plan=plan,
        status__in=[
            RpaTask.Status.LEASED,
            RpaTask.Status.RUNNING,
            RpaTask.Status.CANCEL_REQUESTED,
        ],
    ).exists()
    if plan.current_revision_id is not None and not has_active_task:
        shared_tasks = RpaTask.objects.filter(
            boss_account_id=plan.job.boss_account_id,
            action=RpaTask.Action.SYNC_CONVERSATIONS,
            status__in=[
                RpaTask.Status.LEASED,
                RpaTask.Status.RUNNING,
                RpaTask.Status.CANCEL_REQUESTED,
            ],
        ).values_list("request_payload", flat=True)
        for payload in shared_tasks:
            scopes = (payload or {}).get("passive_plan_scopes") if isinstance(payload, dict) else None
            scope = scopes.get(str(plan.job_id)) if isinstance(scopes, dict) else None
            if not isinstance(scope, dict):
                continue
            try:
                scope_revision_id = int(scope.get("revision_id"))
            except (TypeError, ValueError):
                continue
            if scope_revision_id == plan.current_revision_id:
                has_active_task = True
                break
    if plan.desired_state == RecruitmentAutomationPlan.DesiredState.STOPPED:
        return "stopping" if has_active_task else RecruitmentAutomationPlan.DesiredState.STOPPED
    if plan.desired_state == RecruitmentAutomationPlan.DesiredState.PAUSED:
        return "pausing" if has_active_task else RecruitmentAutomationPlan.DesiredState.PAUSED
    if plan.kind == RecruitmentAutomationPlan.Kind.PASSIVE_RESUME:
        # The bootstrap workflow may finish, while the account poller remains a
        # durable subscription until HR explicitly stops the plan.
        if (
            plan.current_revision_id
            and AutomationApproval.objects.filter(
                automation_plan_revision_id=plan.current_revision_id,
                automation_generation=plan.control_generation,
                action=AutomationApproval.Action.REQUEST_RESUME,
                status=AutomationApproval.Status.DRAFT,
            ).filter(Q(expires_at__isnull=True) | Q(expires_at__gt=timezone.now())).exists()
        ):
            return "waiting_human"
        return RecruitmentAutomationPlan.DesiredState.RUNNING
    if has_active_task:
        return RecruitmentAutomationPlan.DesiredState.RUNNING
    run = plan.current_run
    if run is None:
        return RecruitmentAutomationPlan.DesiredState.RUNNING
    return {
        WorkflowRun.Status.WAITING_HUMAN: "waiting_human",
        WorkflowRun.Status.FAILED: "failed",
        WorkflowRun.Status.SUCCEEDED: "completed",
        WorkflowRun.Status.CANCELLED: "cancelled",
        WorkflowRun.Status.PAUSED: "paused",
    }.get(run.status, RecruitmentAutomationPlan.DesiredState.RUNNING)


def _cancel_pending_plan_work(*, plan, revision_id, generation, actor, now):
    pending_tasks = list(
        RpaTask.objects.select_for_update()
        .filter(
            automation_plan_revision_id=revision_id,
            automation_generation=generation,
            status=RpaTask.Status.PENDING,
        )
        .select_related("execution_batch")
    )
    step_ids = []
    batch_ids = set()
    for task in pending_tasks:
        step_id = (task.request_payload or {}).get("step_id")
        if step_id:
            step_ids.append(step_id)
        if task.execution_batch_id:
            batch_ids.add(task.execution_batch_id)
        task.status = RpaTask.Status.CANCELLED
        task.error_code = "automation_plan_stopped"
        task.error_message = "招聘自动化方案已停止，任务未进入外部适配器"
        task.completed_at = now
        task.lease_expires_at = None
        task.lease_token = None
        task.save(update_fields=[
            "status", "error_code", "error_message", "completed_at", "lease_expires_at",
            "lease_token", "updated_at",
        ])
        append_event(task=task, event="cancelled", message="招聘自动化方案已停止，任务未执行")
    if step_ids:
        StepExecution.objects.filter(pk__in=step_ids).update(
            status=StepExecution.Status.CANCELLED,
            error_code="automation_plan_stopped",
            error_message="招聘自动化方案已停止",
            completed_at=now,
            updated_at=now,
        )
        ConversationAction.objects.filter(step_id__in=step_ids).update(
            status=ConversationAction.Status.CANCELLED,
            error_code="automation_plan_stopped",
            error_message="招聘自动化方案已停止",
            completed_at=now,
            updated_at=now,
        )
    for batch in ExecutionBatch.objects.select_for_update().filter(
        automation_plan_revision_id=revision_id,
        automation_generation=generation,
        status__in=[
            ExecutionBatch.Status.PENDING,
            ExecutionBatch.Status.RUNNING,
            ExecutionBatch.Status.WAITING_HUMAN,
            ExecutionBatch.Status.PARTIAL,
        ],
    ):
        has_active = batch.rpa_tasks.filter(
            status__in=[RpaTask.Status.LEASED, RpaTask.Status.RUNNING]
        ).exists()
        if not has_active:
            batch.status = ExecutionBatch.Status.CANCELLED
            batch.save(update_fields=["status", "updated_at"])
        batch.steps.exclude(pk__in=step_ids).filter(
            status__in=[StepExecution.Status.PENDING, StepExecution.Status.WAITING_HUMAN]
        ).update(
            status=StepExecution.Status.CANCELLED,
            error_code="automation_plan_stopped",
            error_message="招聘自动化方案已停止",
            completed_at=now,
            updated_at=now,
        )
        ConversationAction.objects.filter(
            batch=batch,
            status__in=[
                ConversationAction.Status.DRAFT,
                ConversationAction.Status.APPROVED,
                ConversationAction.Status.PENDING,
            ],
        ).update(
            status=ConversationAction.Status.CANCELLED,
            error_code="automation_plan_stopped",
            error_message="招聘自动化方案已停止",
            completed_at=now,
            updated_at=now,
        )
    AutomationApproval.objects.select_for_update().filter(
        automation_plan_revision_id=revision_id,
        automation_generation=generation,
        status=AutomationApproval.Status.DRAFT,
    ).update(
        status=AutomationApproval.Status.REJECTED,
        approved_by=actor,
        approved_at=now,
    )
    active_campaign_ids = set()
    active_search_payloads = RpaTask.objects.filter(
        automation_plan_revision_id=revision_id,
        automation_generation=generation,
        action=RpaTask.Action.SEARCH_AND_PULL_RESUMES,
        status__in=[RpaTask.Status.LEASED, RpaTask.Status.RUNNING],
    ).values_list("request_payload", flat=True)
    for payload in active_search_payloads:
        if not isinstance(payload, dict):
            continue
        try:
            active_campaign_ids.add(int(payload.get("campaign_id")))
        except (TypeError, ValueError):
            continue
    campaigns = SearchCampaign.objects.select_for_update().filter(
        automation_plan_revision_id=revision_id,
        automation_generation=generation,
        status__in=[
            SearchCampaign.Status.DRAFT,
            SearchCampaign.Status.QUEUED,
            SearchCampaign.Status.RUNNING,
            SearchCampaign.Status.PAUSED,
        ],
    )
    if active_campaign_ids:
        campaigns = campaigns.exclude(pk__in=active_campaign_ids)
    campaigns.update(
        status=SearchCampaign.Status.CANCELLED,
        stop_reason=SearchCampaign.StopReason.USER_STOPPED,
        error_message="",
        completed_at=now,
        updated_at=now,
    )


def _check_control(plan, *, request_id, action, expected_control_version):
    if plan.last_control_request_id == request_id:
        if plan.last_control_action != action:
            raise AutomationPlanConflict("同一控制请求标识已用于其他动作")
        return True
    if plan.control_version != expected_control_version:
        raise AutomationPlanConflict(
            f"方案状态已变化，请刷新后重试（当前版本 {plan.control_version}）"
        )
    return False


@serialize_sqlite_lifecycle
@transaction.atomic
def start_plan(
    *,
    job_id,
    kind,
    config,
    request_id,
    expected_control_version,
    actor,
    workflow_version_id=None,
):
    normalized = normalize_plan_config(kind, config)
    account, job = _lock_job_and_account(job_id)
    _ensure_authorized(account, actor)
    incoming_hash = _request_hash(
        job_id=job.pk,
        kind=kind,
        config=normalized,
        workflow_version_id=workflow_version_id,
    )
    existing_revision = (
        RecruitmentAutomationPlanRevision.objects.select_related("plan__current_revision", "plan__current_run")
        .filter(request_id=request_id)
        .first()
    )
    if existing_revision is not None:
        if (
            existing_revision.plan.job_id != job.pk
            or existing_revision.request_hash != incoming_hash
        ):
            raise AutomationPlanConflict("同一启动请求标识对应的执行方案不一致")
        return PlanCommandResult(existing_revision.plan, idempotent=True)

    if kind == RecruitmentAutomationPlan.Kind.ACTIVE_RESUME_SEARCH:
        try:
            standard = resolve_workbench_standard(
                job=job,
                core=normalized.get("core", []),
                bonus=normalized.get("bonus", []),
                actor=actor,
            )
        except ValueError as exc:
            raise ValidationError({"config": str(exc)}) from exc
        normalized = {
            **normalized,
            "standard_id": standard.pk,
            "standard_version": standard.version,
        }

    if not account.active or account.archived_at is not None:
        raise ValidationError("BOSS 账号已停用或归档")
    if account.login_status != BossAccount.LoginStatus.READY:
        raise ValidationError("BOSS 账号尚未登录或需要人工验证")
    if job.archived_at is not None or job.status != RecruitmentJob.Status.OPEN:
        raise ValidationError("只有招聘中的未归档职位可以开启自动化")

    plan, created = RecruitmentAutomationPlan.objects.get_or_create(
        job=job,
        defaults={"kind": kind, "created_by": actor, "updated_by": actor},
    )
    plan = RecruitmentAutomationPlan.objects.select_for_update().select_related(
        "current_revision", "current_run", "managed_template"
    ).get(pk=plan.pk)
    if plan.control_version != expected_control_version:
        raise AutomationPlanConflict(
            f"方案状态已变化，请刷新后重试（当前版本 {plan.control_version}）"
        )
    if RpaTask.objects.filter(
        automation_plan_revision__plan=plan,
        status__in=[RpaTask.Status.LEASED, RpaTask.Status.RUNNING],
    ).exists():
        raise AutomationPlanConflict("上一代任务正在收尾，请等待状态变为已停止后再开启或修改")
    start_state = effective_plan_state(plan)
    if not created and start_state not in {
        RecruitmentAutomationPlan.DesiredState.STOPPED,
        "failed",
        "completed",
    }:
        raise AutomationPlanConflict("当前方案仍在运行或等待处理，请先停止后再修改或重新开启")
    if plan.kind != kind and start_state not in {
        RecruitmentAutomationPlan.DesiredState.STOPPED,
        "failed",
        "completed",
    }:
        raise AutomationPlanConflict("请先停止当前招聘方案，再切换被动咨询或主动寻访")

    old_run = plan.current_run
    next_generation = plan.control_generation + 1
    if old_run is not None and old_run.status not in RUN_TERMINAL_STATES:
        cancel_run(old_run, actor=actor)

    if workflow_version_id is None:
        managed_template, workflow_version = create_standard_workflow(
            kind=kind,
            account=account,
            actor=actor,
            config=normalized,
            template=plan.managed_template,
        )
        workflow_version = enable_version(version=workflow_version, actor=actor)
        plan.managed_template = managed_template
    else:
        workflow_version = (
            WorkflowVersion.objects.select_for_update()
            .select_related("template", "boss_account")
            .filter(pk=workflow_version_id, boss_account=account, status=WorkflowVersion.Status.ENABLED)
            .first()
        )
        if workflow_version is None:
            raise ValidationError({"workflow_version": "自定义流程必须已启用并属于所选 BOSS 账号"})
        if workflow_version.template.managed_automation_plans.exists():
            raise ValidationError({
                "workflow_version": "招聘作业台托管版本不能作为自定义流程复用，请使用标准方案生成新版本"
            })

    next_revision = (plan.revisions.aggregate(value=Max("revision"))["value"] or 0) + 1
    revision_config = dict(normalized)
    if kind == RecruitmentAutomationPlan.Kind.PASSIVE_RESUME:
        revision_config["execution_authorization"] = {
            "source": "plan_start",
            "actor_id": actor.pk,
            "actions": [ConversationAction.Action.REQUEST_RESUME],
        }
    elif (
        kind == RecruitmentAutomationPlan.Kind.ACTIVE_RESUME_SEARCH
        and workflow_version_id is None
    ):
        revision_config["execution_authorization"] = {
            "source": "plan_start",
            "actor_id": actor.pk,
            "actions": [AutomationApproval.Action.SEARCH_AND_PULL_RESUMES],
        }
    revision = RecruitmentAutomationPlanRevision.objects.create(
        plan=plan,
        revision=next_revision,
        kind=kind,
        request_id=request_id,
        request_hash=incoming_hash,
        config_snapshot=revision_config,
        workflow_version=workflow_version,
        created_by=actor,
    )
    plan.desired_state = RecruitmentAutomationPlan.DesiredState.RUNNING
    plan.archived_at = None
    plan.kind = kind
    plan.control_generation = next_generation
    plan.control_version += 1
    plan.current_revision = revision
    plan.current_run = None
    plan.last_control_request_id = request_id
    plan.last_control_action = "start"
    plan.updated_by = actor
    plan.save(update_fields=[
        "desired_state", "kind", "control_generation", "control_version", "current_revision",
        "current_run", "managed_template", "last_control_request_id", "last_control_action", "updated_by", "archived_at", "updated_at",
    ])
    run = create_run(
        version=workflow_version,
        actor=actor,
        mode=WorkflowRun.Mode.FORMAL,
        idempotency_key=f"automation-plan:{plan.pk}:revision:{revision.revision}",
        input_snapshot={"scheme": kind, **revision_config},
        job=job,
        automation_plan_revision=revision,
        automation_generation=next_generation,
    )
    plan.current_run = run
    plan.save(update_fields=["current_run", "updated_at"])
    advance_run(run, executor=execute_workflow_node)
    # This projection is intentionally the final mutation in the atomic start.
    refresh_message_sync_policy(account=account)
    RecruitmentAuditLog.objects.create(
        actor=actor,
        boss_account=account,
        action="automation_plan_started",
        target_id=str(plan.pk),
        detail={
            "job_id": job.pk,
            "kind": kind,
            "revision": revision.revision,
            "generation": next_generation,
            "workflow_version_id": workflow_version.pk,
            "authorized_actions": revision_config.get("execution_authorization", {}).get("actions", []),
        },
    )
    return PlanCommandResult(plan, created=created)


@serialize_sqlite_lifecycle
@transaction.atomic
def pause_plan(*, plan_id, actor, request_id, expected_control_version):
    snapshot = RecruitmentAutomationPlan.objects.filter(pk=plan_id).values("job__boss_account_id").first()
    if snapshot is None:
        raise ValidationError("招聘自动化方案不存在")
    account = BossAccount.objects.select_for_update().get(pk=snapshot["job__boss_account_id"])
    _ensure_authorized(account, actor)
    plan = RecruitmentAutomationPlan.objects.select_for_update().select_related("current_run").get(pk=plan_id)
    if _check_control(
        plan,
        request_id=request_id,
        action="pause",
        expected_control_version=expected_control_version,
    ):
        return PlanCommandResult(plan, idempotent=True)
    if plan.desired_state == RecruitmentAutomationPlan.DesiredState.STOPPED:
        raise AutomationPlanConflict("已停止的方案不能暂停，请重新开启")
    if plan.desired_state != RecruitmentAutomationPlan.DesiredState.PAUSED:
        stopped_revision_id = plan.current_revision_id
        stopped_generation = plan.control_generation
        plan.desired_state = RecruitmentAutomationPlan.DesiredState.PAUSED
        plan.control_generation += 1
        plan.control_version += 1
        plan.updated_by = actor
        plan.last_control_request_id = request_id
        plan.last_control_action = "pause"
        plan.save(update_fields=[
            "desired_state", "control_generation", "control_version", "last_control_request_id",
            "last_control_action", "updated_by", "updated_at",
        ])
        now = timezone.now()
        if plan.current_run and plan.current_run.status not in RUN_TERMINAL_STATES:
            cancel_run(plan.current_run, actor=actor)
        _cancel_pending_plan_work(
            plan=plan,
            revision_id=stopped_revision_id,
            generation=stopped_generation,
            actor=actor,
            now=now,
        )
    else:
        plan.last_control_request_id = request_id
        plan.last_control_action = "pause"
        plan.save(update_fields=["last_control_request_id", "last_control_action", "updated_at"])
    refresh_message_sync_policy(account=account)
    return PlanCommandResult(plan)


@serialize_sqlite_lifecycle
@transaction.atomic
def resume_plan(*, plan_id, actor, request_id, expected_control_version):
    snapshot = RecruitmentAutomationPlan.objects.filter(pk=plan_id).values("job__boss_account_id").first()
    if snapshot is None:
        raise ValidationError("招聘自动化方案不存在")
    account = BossAccount.objects.select_for_update().get(pk=snapshot["job__boss_account_id"])
    _ensure_authorized(account, actor)
    if account.login_status != BossAccount.LoginStatus.READY:
        raise ValidationError("BOSS 账号尚未登录或需要人工验证")
    plan = RecruitmentAutomationPlan.objects.select_for_update().select_related(
        "current_run", "current_revision__workflow_version"
    ).get(pk=plan_id)
    if _check_control(
        plan,
        request_id=request_id,
        action="resume",
        expected_control_version=expected_control_version,
    ):
        return PlanCommandResult(plan, idempotent=True)
    if plan.desired_state == RecruitmentAutomationPlan.DesiredState.STOPPED:
        raise AutomationPlanConflict("已停止的方案不能恢复，请重新开启")
    if RpaTask.objects.filter(
        automation_plan_revision__plan=plan,
        status__in=[RpaTask.Status.LEASED, RpaTask.Status.RUNNING],
    ).exists():
        raise AutomationPlanConflict("上一代任务正在收尾，暂时不能恢复")
    if plan.desired_state != RecruitmentAutomationPlan.DesiredState.RUNNING:
        if plan.current_revision is None:
            raise AutomationPlanConflict("方案缺少可恢复的修订，请重新开启")
        plan.desired_state = RecruitmentAutomationPlan.DesiredState.RUNNING
        plan.control_generation += 1
        plan.control_version += 1
        plan.updated_by = actor
        plan.last_control_request_id = request_id
        plan.last_control_action = "resume"
        plan.save(update_fields=[
            "desired_state", "control_generation", "control_version", "last_control_request_id", "last_control_action",
            "updated_by", "updated_at",
        ])
        run = create_run(
            version=plan.current_revision.workflow_version,
            actor=actor,
            mode=WorkflowRun.Mode.FORMAL,
            idempotency_key=f"automation-plan:{plan.pk}:resume:{plan.control_generation}",
            input_snapshot={"scheme": plan.kind, **(plan.current_revision.config_snapshot or {})},
            job=plan.job,
            automation_plan_revision=plan.current_revision,
            automation_generation=plan.control_generation,
        )
        plan.current_run = run
        plan.save(update_fields=["current_run", "updated_at"])
        advance_run(run, executor=execute_workflow_node)
    else:
        plan.last_control_request_id = request_id
        plan.last_control_action = "resume"
        plan.save(update_fields=["last_control_request_id", "last_control_action", "updated_at"])
    refresh_message_sync_policy(account=account)
    return PlanCommandResult(plan)


@serialize_sqlite_lifecycle
@transaction.atomic
def stop_plan(*, plan_id, actor, request_id, expected_control_version):
    snapshot = RecruitmentAutomationPlan.objects.filter(pk=plan_id).values("job__boss_account_id").first()
    if snapshot is None:
        raise ValidationError("招聘自动化方案不存在")
    account = BossAccount.objects.select_for_update().get(pk=snapshot["job__boss_account_id"])
    _ensure_authorized(account, actor)
    plan = RecruitmentAutomationPlan.objects.select_for_update().select_related("current_run").get(pk=plan_id)
    if _check_control(
        plan,
        request_id=request_id,
        action="stop",
        expected_control_version=expected_control_version,
    ):
        return PlanCommandResult(plan, idempotent=True)
    stopped_revision_id = None
    stopped_generation = None
    if plan.desired_state != RecruitmentAutomationPlan.DesiredState.STOPPED:
        stopped_revision_id = plan.current_revision_id
        stopped_generation = plan.control_generation
        plan.desired_state = RecruitmentAutomationPlan.DesiredState.STOPPED
        plan.control_generation += 1
        plan.control_version += 1
        plan.updated_by = actor
    plan.last_control_request_id = request_id
    plan.last_control_action = "stop"
    # Persist the fence before touching pending/running execution state.
    plan.save(update_fields=[
        "desired_state", "control_generation", "control_version", "last_control_request_id",
        "last_control_action", "updated_by", "updated_at",
    ])
    now = timezone.now()
    if plan.current_run and plan.current_run.status not in RUN_TERMINAL_STATES:
        cancel_run(plan.current_run, actor=actor)
    if stopped_revision_id is not None:
        _cancel_pending_plan_work(
            plan=plan,
            revision_id=stopped_revision_id,
            generation=stopped_generation,
            actor=actor,
            now=now,
        )
    refresh_message_sync_policy(account=account)
    RecruitmentAuditLog.objects.create(
        actor=actor,
        boss_account=account,
        action="automation_plan_stopped",
        target_id=str(plan.pk),
        detail={"job_id": plan.job_id, "generation": plan.control_generation},
    )
    return PlanCommandResult(plan)
