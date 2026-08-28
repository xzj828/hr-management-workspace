import hashlib
from datetime import timedelta

from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError

from attendance.permissions import is_hr_user
from recruitment.models import (
    AutomationApproval,
    AutomationUsage,
    BossAccount,
    Candidate,
    CandidateDiscovery,
    CandidateExternalIdentity,
    ConversationAction,
    ConversationSyncState,
    ExecutionBatch,
    HumanAttention,
    InterviewInvitation,
    JobApplication,
    RecruitmentAuditLog,
    RecruitmentAutomationPlan,
    RecruitmentJob,
    RpaTask,
    StepExecution,
)
from recruitment.rpa.tasks import append_event, create_task
from recruitment.services.human_attention import ensure_attention
from recruitment.services.sqlite_lifecycle import serialize_sqlite_lifecycle
from recruitment.services.stages import advance_for_event
from recruitment.services.usage import consume


ACTION_TO_APPROVAL = {
    ConversationAction.Action.GREET: AutomationApproval.Action.GREET,
    ConversationAction.Action.REQUEST_RESUME: AutomationApproval.Action.REQUEST_RESUME,
    ConversationAction.Action.SEND_INTERVIEW: AutomationApproval.Action.SEND_INTERVIEW,
}

GREET_ACTIVE_STATUSES = {
    ConversationAction.Status.DRAFT,
    ConversationAction.Status.APPROVED,
    ConversationAction.Status.PENDING,
    ConversationAction.Status.RUNNING,
    ConversationAction.Status.WAITING_HUMAN,
}
GREET_CONTACTED_STAGES = {
    JobApplication.Stage.GREETED,
    JobApplication.Stage.COMMUNICATING,
    JobApplication.Stage.WAITING_RESUME,
    JobApplication.Stage.RESUME_RECEIVED,
    JobApplication.Stage.TO_SCREEN,
    JobApplication.Stage.TO_INTERVIEW,
    JobApplication.Stage.INTERVIEWING,
    JobApplication.Stage.TO_OFFER,
    JobApplication.Stage.HIRED,
}
GREET_REASON_LABELS = {
    "": "可打招呼",
    "already_contacted": "候选人已联系",
    "greeting_in_progress": "已有打招呼任务处理中",
    "stable_identity_missing": "缺少平台稳定身份",
    "stage_ineligible": "候选人当前阶段不可联系",
}


def _draft_greet_is_expired(action, now):
    approval = action.approval
    return (
        action.status == ConversationAction.Status.DRAFT
        and approval is not None
        and (
            approval.status in {
                AutomationApproval.Status.REJECTED,
                AutomationApproval.Status.EXPIRED,
            }
            or (
                approval.status == AutomationApproval.Status.DRAFT
                and approval.expires_at is not None
                and approval.expires_at <= now
            )
        )
    )


def greeting_eligibility_map(*, applications, account):
    """Return a safe, account-scoped greeting projection without exposing stable IDs."""
    items = list(applications)
    if not items:
        return {}
    candidate_ids = [item.candidate_id for item in items]
    identity_candidate_ids = set(
        CandidateExternalIdentity.objects.filter(
            candidate_id__in=candidate_ids,
            boss_account=account,
        ).exclude(external_id="").values_list("candidate_id", flat=True)
    )
    latest_by_application = {}
    active_by_application = {}
    succeeded_candidate_ids = set()
    now = timezone.now()
    for action in (
        ConversationAction.objects.filter(
            application__candidate_id__in=candidate_ids,
            action=ConversationAction.Action.GREET,
        )
        .select_related("approval", "application")
        .order_by("application_id", "-created_at", "-id")
    ):
        if action.status == ConversationAction.Status.SUCCEEDED:
            succeeded_candidate_ids.add(action.application.candidate_id)
        expired_draft = _draft_greet_is_expired(action, now)
        if action.application_id not in latest_by_application and not expired_draft:
            latest_by_application[action.application_id] = action
        if (
            action.application_id not in active_by_application
            and action.status in GREET_ACTIVE_STATUSES
            and not expired_draft
        ):
            active_by_application[action.application_id] = action

    result = {}
    for application in items:
        latest = latest_by_application.get(application.pk)
        active = active_by_application.get(application.pk)
        if application.candidate_id in succeeded_candidate_ids or application.stage in GREET_CONTACTED_STAGES:
            reason_code = "already_contacted"
        elif application.stage == JobApplication.Stage.REJECTED:
            reason_code = "stage_ineligible"
        elif active is not None:
            reason_code = "greeting_in_progress"
        elif application.candidate_id not in identity_candidate_ids:
            reason_code = "stable_identity_missing"
        else:
            reason_code = ""
        projection_action = active if reason_code == "greeting_in_progress" else latest
        result[application.pk] = {
            "eligible": not reason_code,
            "status": projection_action.status if projection_action is not None else "not_requested",
            "reason_code": reason_code,
            "reason_label": GREET_REASON_LABELS[reason_code],
            "action_id": str(projection_action.pk) if projection_action is not None else None,
            "updated_at": projection_action.updated_at if projection_action is not None else None,
        }
    return result


def _identity_snapshot(application, account, *, require_stable_id=False):
    identities = CandidateExternalIdentity.objects.filter(
        candidate=application.candidate, boss_account=account
    )
    if require_stable_id:
        identities = identities.exclude(external_id="")
    identity = identities.order_by("-last_seen_at").first()
    discovery = CandidateDiscovery.objects.filter(
        imported_candidate=application.candidate,
        boss_account=account,
        job=application.job,
    ).order_by("-updated_at").first()
    snapshot = {
        "boss_account_id": account.pk,
        "candidate_id": application.candidate_id,
        "application_id": application.pk,
        "name": application.candidate.name,
        "external_id": identity.external_id if identity else application.candidate.external_id,
        "fingerprint": identity.fingerprint if identity else "",
        "job_id": application.job_id,
        "job_title": application.job.title,
    }
    if discovery is not None:
        snapshot["verification"] = {
            "source": discovery.source,
            "criteria": discovery.criteria if isinstance(discovery.criteria, dict) else {},
        }
    return snapshot


@serialize_sqlite_lifecycle
@transaction.atomic
def prepare_communication(
    *,
    account,
    applications,
    action,
    message,
    actor,
    request_id,
    invitation=None,
    item_contexts=None,
    automation_plan_revision=None,
    automation_generation=None,
):
    account = BossAccount.objects.select_for_update().get(pk=account.pk)
    if not actor.is_superuser and (
        not is_hr_user(actor) or not account.authorized_users.filter(pk=actor.pk).exists()
    ):
        raise PermissionDenied("无权操作该 BOSS 账号")
    if action not in ACTION_TO_APPROVAL:
        raise ValidationError("不支持的沟通动作")
    normalized = str(message or "").strip()
    if not normalized or len(normalized) > 1000:
        raise ValidationError("最终话术必须为 1 到 1000 个字符")
    requested_ids = [item.pk for item in applications]
    items = list(
        JobApplication.objects.select_for_update()
        .select_related("candidate", "job")
        .filter(pk__in=requested_ids, archived_at__isnull=True)
        .order_by("pk")
    )
    if len(items) != len(set(requested_ids)):
        raise ValidationError("候选人不存在、已归档或被重复选择")
    if not items or len(items) > 100:
        raise ValidationError("每批请选择 1 到 100 位候选人")
    if any(item.job.boss_account_id != account.pk for item in items):
        raise ValidationError("候选人与所选 BOSS 账号不匹配")
    request_key = str(request_id)
    plan_revision_id = getattr(automation_plan_revision, "pk", automation_plan_revision)
    if (plan_revision_id is None) != (automation_generation is None):
        raise ValidationError("沟通动作的方案修订与代际必须同时存在")
    if plan_revision_id is not None:
        from recruitment.services.automation_plans import assert_plan_fence_current

        RecruitmentAutomationPlan.objects.select_for_update().get(
            revisions__pk=plan_revision_id,
        )
        assert_plan_fence_current(
            revision_id=plan_revision_id,
            generation=automation_generation,
            message="招聘自动化方案当前未运行，不能创建新的沟通确认",
        )
    idempotency_key = f"communication:{account.pk}:{action}:{request_key}"
    existing_approval = AutomationApproval.objects.filter(idempotency_key=idempotency_key).first()
    if existing_approval is not None:
        if (
            existing_approval.automation_plan_revision_id != plan_revision_id
            or existing_approval.automation_generation != automation_generation
        ):
            raise ValidationError("沟通确认请求标识已被其他方案代际使用")
        existing_payload = existing_approval.payload if isinstance(existing_approval.payload, dict) else {}
        existing_application_ids = sorted(
            int(item["application_id"])
            for item in existing_payload.get("items", [])
            if isinstance(item, dict) and str(item.get("application_id", "")).isdigit()
        )
        if (
            existing_payload.get("action") != action
            or str(existing_payload.get("message", "")).strip() != normalized
            or existing_application_ids != sorted(requested_ids)
        ):
            raise ValidationError("沟通确认请求标识已被不同候选人或话术使用")
        return existing_approval
    if action == ConversationAction.Action.GREET:
        if len({item.job_id for item in items}) != 1:
            raise ValidationError("批量打招呼只能选择同一岗位的候选人")
        eligibility = greeting_eligibility_map(applications=items, account=account)
        blocked = [item for item in items if not eligibility[item.pk]["eligible"]]
        if blocked:
            reasons = "；".join(
                f"{item.candidate.name}：{eligibility[item.pk]['reason_label']}" for item in blocked[:5]
            )
            if len(blocked) > 5:
                reasons += f"；另有 {len(blocked) - 5} 人不可操作"
            raise ValidationError({"applications": f"所选候选人无法批量打招呼：{reasons}"})
    approval, created = AutomationApproval.objects.get_or_create(
        idempotency_key=idempotency_key,
        defaults={
            "action": ACTION_TO_APPROVAL[action],
            "boss_account": account,
            "created_by": actor,
            "payload": {
                "action": action,
                "message": normalized,
                "invitation": invitation or {},
                "items": [],
                **(
                    {
                        "automation_plan_revision_id": plan_revision_id,
                        "automation_generation": automation_generation,
                    }
                    if plan_revision_id is not None
                    else {}
                ),
            },
            "item_count": len(items),
            "expires_at": timezone.now() + timedelta(minutes=30),
            "automation_plan_revision_id": plan_revision_id,
            "automation_generation": automation_generation,
        },
    )
    if not created:
        if (
            approval.automation_plan_revision_id != plan_revision_id
            or approval.automation_generation != automation_generation
        ):
            raise ValidationError("沟通确认请求标识已被其他方案代际使用")
        return approval
    contexts = item_contexts if isinstance(item_contexts, dict) else {}
    payload_items = []
    for application in items:
        snapshot = _identity_snapshot(
            application,
            account,
            require_stable_id=action == ConversationAction.Action.GREET,
        )
        digest = hashlib.sha256(f"{approval.pk}:{application.pk}:{action}".encode()).hexdigest()[:24]
        conversation = ConversationAction.objects.create(
            application=application,
            boss_account=account,
            action=action,
            message_snapshot=normalized,
            target_snapshot=snapshot,
            idempotency_key=f"conversation:{digest}",
            approval=approval,
            created_by=actor,
            automation_plan_revision_id=plan_revision_id,
            automation_generation=automation_generation,
        )
        if action == ConversationAction.Action.SEND_INTERVIEW:
            data = invitation or {}
            InterviewInvitation.objects.create(
                action=conversation,
                interview_at=data.get("interview_at"),
                mode=data.get("mode"),
                location=data.get("location", ""),
                contact_name=data.get("contact_name", ""),
                note=data.get("note", ""),
            )
        context = contexts.get(application.pk, contexts.get(str(application.pk), {}))
        safe_context = {}
        if isinstance(context, dict):
            safe_context = {
                "first_contact": bool(context.get("first_contact", False)),
                **(
                    {"source_message_id": int(context["source_message_id"])}
                    if str(context.get("source_message_id", "")).isdigit()
                    else {}
                ),
            }
        payload_items.append({"conversation_action_id": str(conversation.pk), **snapshot, **safe_context})
    approval.payload["items"] = payload_items
    approval.save(update_fields=["payload"])
    return approval


def _is_duplicate_greet(action):
    return action.action == ConversationAction.Action.GREET and ConversationAction.objects.filter(
        application__candidate=action.application.candidate,
        action=ConversationAction.Action.GREET,
        status=ConversationAction.Status.SUCCEEDED,
    ).exclude(pk=action.pk).exists()


def enqueue_next_step(batch):
    if batch.automation_plan_revision_id:
        from recruitment.services.automation_plans import plan_fence_is_current

        if not plan_fence_is_current(
            revision_id=batch.automation_plan_revision_id,
            generation=batch.automation_generation,
        ):
            return None
    if batch.rpa_tasks.filter(status__in=["pending", "leased", "running"]).exists():
        return None
    step = batch.steps.filter(status=StepExecution.Status.PENDING).order_by("created_at").first()
    if step is None:
        return None
    action = step.conversation_action
    approved_item = next(
        (
            item
            for item in batch.approval.payload.get("items", [])
            if isinstance(item, dict) and str(item.get("conversation_action_id", "")) == str(action.pk)
        ),
        {},
    )
    task = create_task(
        account=batch.boss_account,
        action=action.action,
        actor=batch.created_by,
        approval=batch.approval,
        execution_batch=batch,
        workflow_node_run=batch.workflow_node_run,
        request_payload={
            "step_id": step.pk,
            "conversation_action_id": str(action.pk),
            "message": action.message_snapshot,
            "target": action.target_snapshot,
            **(
                {"first_contact": bool(approved_item.get("first_contact", False))}
                if action.action == ConversationAction.Action.REQUEST_RESUME
                else {}
            ),
        },
        idempotency_key=f"communication-task:{action.pk}",
        creation_path="communication_batch",
    )
    return task


@transaction.atomic
def materialize_communication_batch(*, approval, actor):
    is_rejection_notice = approval.action == AutomationApproval.Action.REJECTION_NOTICE
    if is_rejection_notice:
        from recruitment.services.screening import lock_rejection_approval_domain

        lock_rejection_approval_domain(approval=approval)
    locked = AutomationApproval.objects.select_for_update().get(pk=approval.pk)
    if locked.status != AutomationApproval.Status.APPROVED or locked.approved_by_id != actor.pk:
        raise ValidationError("沟通确认记录无效")
    batch, _ = ExecutionBatch.objects.get_or_create(
        approval=locked,
        defaults={
            "boss_account": locked.boss_account,
            "action": locked.action,
            "idempotency_key": f"communication-batch:{locked.pk}",
            "created_by": actor,
            "total_items": locked.item_count,
            "workflow_node_run_id": locked.payload.get("workflow_node_run_id"),
            "automation_plan_revision_id": locked.automation_plan_revision_id,
            "automation_generation": locked.automation_generation,
        },
    )
    if batch.steps.exists():
        return batch
    if is_rejection_notice:
        from recruitment.services.screening import validate_rejection_approval_snapshot

        locked_account = BossAccount.objects.select_for_update().get(pk=batch.boss_account_id)
        actions = validate_rejection_approval_snapshot(approval=locked)
        if any([
            batch.reserved_metric,
            batch.reserved_amount,
            batch.reserved_day,
            batch.quota_reserved_at,
        ]):
            raise ValidationError("未通过通知批次的额度预占状态不完整")
        consume(
            account=locked_account,
            metric=AutomationUsage.Metric.MESSAGE,
            amount=locked.item_count,
        )
        batch.reserved_metric = AutomationUsage.Metric.MESSAGE
        batch.reserved_amount = locked.item_count
        batch.reserved_day = timezone.localdate()
        batch.quota_reserved_at = timezone.now()
        batch.save(update_fields=[
            "reserved_metric", "reserved_amount", "reserved_day", "quota_reserved_at", "updated_at",
        ])
    else:
        actions = ConversationAction.objects.filter(approval=locked).select_related("application__candidate")
    for action in actions:
        skipped = False if is_rejection_notice else _is_duplicate_greet(action)
        step = StepExecution.objects.create(
            batch=batch,
            target_key=str(action.pk),
            target_payload=action.target_snapshot,
            status=StepExecution.Status.SKIPPED if skipped else StepExecution.Status.PENDING,
            error_code="duplicate_contact" if skipped else "",
            error_message="该候选人已由其他账号成功联系" if skipped else "",
            completed_at=timezone.now() if skipped else None,
        )
        action.batch = batch
        action.step = step
        action.status = ConversationAction.Status.SKIPPED if skipped else ConversationAction.Status.PENDING
        action.approved_at = locked.approved_at
        action.save(update_fields=["batch", "step", "status", "approved_at", "updated_at"])
    batch.succeeded_items = batch.steps.filter(status=StepExecution.Status.SUCCEEDED).count()
    batch.failed_items = batch.steps.filter(status__in=[StepExecution.Status.FAILED, StepExecution.Status.SKIPPED]).count()
    if not batch.steps.filter(status=StepExecution.Status.PENDING).exists():
        batch.status = ExecutionBatch.Status.PARTIAL
    batch.save(update_fields=["succeeded_items", "failed_items", "status", "updated_at"])
    RecruitmentAuditLog.objects.create(
        actor=actor, boss_account=batch.boss_account, action="communication_batch_created",
        target_id=str(batch.pk), detail={"action": batch.action, "total_items": batch.total_items},
    )
    if is_rejection_notice:
        for action in actions:
            step = action.step
            create_task(
                account=batch.boss_account,
                action=action.action,
                actor=batch.created_by,
                approval=batch.approval,
                execution_batch=batch,
                request_payload={
                    "step_id": step.pk,
                    "conversation_action_id": str(action.pk),
                    "message": action.message_snapshot,
                    "target": action.target_snapshot,
                },
                idempotency_key=f"communication-task:{action.pk}",
                creation_path="rejection_notice_batch",
                usage_preconsumed=True,
            )
    else:
        enqueue_next_step(batch)
    return batch


@serialize_sqlite_lifecycle
@transaction.atomic
def materialize_plan_start_authorized_resume_request(*, approval, actor):
    """Reuse an immutable passive-plan start command as the request-resume approval."""
    locked = (
        AutomationApproval.objects.select_for_update()
        .select_related("automation_plan_revision")
        .get(pk=approval.pk)
    )
    authorization = (
        locked.automation_plan_revision.config_snapshot.get("execution_authorization", {})
        if locked.automation_plan_revision_id
        else {}
    )
    if (
        locked.action != AutomationApproval.Action.REQUEST_RESUME
        or locked.automation_plan_revision_id is None
        or locked.automation_plan_revision.kind != RecruitmentAutomationPlan.Kind.PASSIVE_RESUME
        or authorization.get("source") != "plan_start"
        or ConversationAction.Action.REQUEST_RESUME not in authorization.get("actions", [])
        or authorization.get("actor_id") != actor.pk
    ):
        raise ValidationError("该求简历动作没有开始执行授权")

    approved_from_draft = locked.status == AutomationApproval.Status.DRAFT
    if approved_from_draft:
        from recruitment.services.approvals import approve

        locked = approve(approval=locked, actor=actor)
    elif not (
        locked.status == AutomationApproval.Status.APPROVED
        and locked.approved_by_id == actor.pk
    ):
        raise ValidationError("开始执行授权对应的求简历确认状态无效")

    batch = materialize_communication_batch(approval=locked, actor=actor)
    if approved_from_draft:
        RecruitmentAuditLog.objects.create(
            actor=actor,
            boss_account=locked.boss_account,
            action="automation_approval_authorized_at_plan_start",
            target_id=str(locked.pk),
            detail={
                "approval_action": locked.action,
                "automation_plan_revision_id": locked.automation_plan_revision_id,
                "automation_generation": locked.automation_generation,
                "batch_id": str(batch.pk),
            },
        )
    return batch


@transaction.atomic
def cancel_workflow_communication(*, workflow_node_run, actor, now=None):
    """Cancel every communication item that has not entered the external adapter."""
    completed_at = now or timezone.now()
    batch = (
        ExecutionBatch.objects.select_for_update()
        .filter(workflow_node_run=workflow_node_run)
        .first()
    )
    if batch is None:
        return False
    tasks = RpaTask.objects.select_for_update().filter(execution_batch=batch)
    active_tasks = tasks.filter(status__in=[RpaTask.Status.LEASED, RpaTask.Status.RUNNING])
    active_step_ids = {
        value
        for value in active_tasks.values_list("request_payload__step_id", flat=True)
        if value is not None
    }
    for task in active_tasks:
        if task.status == RpaTask.Status.CANCEL_REQUESTED:
            continue
        task.status = RpaTask.Status.CANCEL_REQUESTED
        task.save(update_fields=["status", "updated_at"])
        append_event(
            task=task,
            event="cancel_requested",
            message="所属流程已取消，已通知本机 Worker 中断当前沟通任务",
            data={"status": task.status},
        )
    for task in tasks.filter(status=RpaTask.Status.PENDING):
        task.status = RpaTask.Status.CANCELLED
        task.error_code = "workflow_cancelled"
        task.error_message = "所属流程已取消，任务未进入外部适配器"
        task.completed_at = completed_at
        task.lease_expires_at = None
        task.save(update_fields=[
            "status", "error_code", "error_message", "completed_at", "lease_expires_at", "updated_at",
        ])
        append_event(task=task, event="cancelled", message="所属流程已取消，沟通任务未执行")

    cancellable_steps = batch.steps.exclude(pk__in=active_step_ids).filter(status__in=[
        StepExecution.Status.PENDING,
        StepExecution.Status.WAITING_HUMAN,
    ])
    step_ids = list(cancellable_steps.values_list("pk", flat=True))
    cancellable_steps.update(
        status=StepExecution.Status.CANCELLED,
        error_code="workflow_cancelled",
        error_message="所属流程已取消",
        completed_at=completed_at,
        updated_at=completed_at,
    )
    ConversationAction.objects.filter(step_id__in=step_ids).update(
        status=ConversationAction.Status.CANCELLED,
        error_code="workflow_cancelled",
        error_message="所属流程已取消",
        completed_at=completed_at,
        updated_at=completed_at,
    )
    batch.status = ExecutionBatch.Status.CANCELLED
    batch.save(update_fields=["status", "updated_at"])
    RecruitmentAuditLog.objects.create(
        actor=actor,
        boss_account=batch.boss_account,
        action="communication_batch_cancelled_with_workflow",
        target_id=str(batch.pk),
        detail={"active_external_tasks": active_tasks.count()},
    )
    return active_tasks.exists()


@serialize_sqlite_lifecycle
@transaction.atomic
def complete_communication_task(*, task, status, result, error_code, error_message):
    action = ConversationAction.objects.select_for_update().select_related(
        "application__job", "batch", "step", "created_by"
    ).get(pk=task.request_payload.get("conversation_action_id"))
    step = StepExecution.objects.select_for_update().get(pk=action.step_id)
    batch = ExecutionBatch.objects.select_for_update().get(pk=action.batch_id)
    plan_fence_closed = False
    if batch.automation_plan_revision_id:
        from recruitment.services.automation_plans import plan_fence_is_current

        plan_fence_closed = not plan_fence_is_current(
            revision_id=batch.automation_plan_revision_id,
            generation=batch.automation_generation,
        )
    now = timezone.now()
    target = task.request_payload.get("target") if isinstance(task.request_payload.get("target"), dict) else {}
    approved_items = task.approval.payload.get("items", []) if task.approval and isinstance(task.approval.payload, dict) else []
    approved_target = next(
        (
            item for item in approved_items
            if isinstance(item, dict)
            and str(item.get("conversation_action_id", "")) == str(action.pk)
        ),
        {},
    )
    expected_external_id = str(target.get("external_id", "")).strip()
    identity_verified = (
        result.get("verified") is True
        and bool(expected_external_id)
        and str(action.target_snapshot.get("external_id", "")).strip() == expected_external_id
        and str(approved_target.get("external_id", "")).strip() == expected_external_id
        and str(result.get("expected_external_id", "")).strip() == expected_external_id
        and str(result.get("observed_external_id", "")).strip() == expected_external_id
        and (
            action.action != ConversationAction.Action.GREET
            or result.get("greeting_verified") is True
        )
    )
    unverified_success = status == "succeeded" and not identity_verified
    if status == "succeeded" and identity_verified:
        step_status = StepExecution.Status.SUCCEEDED
        action_status = ConversationAction.Status.SUCCEEDED
    elif status == "waiting_human" or (status == "succeeded" and not identity_verified):
        step_status = StepExecution.Status.WAITING_HUMAN
        action_status = ConversationAction.Status.WAITING_HUMAN
        status = "waiting_human"
        if unverified_success:
            error_code = "external_result_uncertain"
            error_message = "发送结果待人工核查，禁止自动重试"
        elif not error_code:
            error_code = "target_identity_unverifiable"
        if not error_message:
            error_message = "Worker 未返回与批准快照一致的平台稳定 ID，已转人工处理"
    else:
        step_status = StepExecution.Status.FAILED
        action_status = ConversationAction.Status.FAILED
    step.status = step_status
    step.result = result
    step.error_code = str(error_code or "")[:64]
    step.error_message = str(error_message or "")[:2000]
    step.completed_at = now
    step.save(update_fields=["status", "result", "error_code", "error_message", "completed_at", "updated_at"])
    action.status = action_status
    action.result = result
    action.error_code = step.error_code
    action.error_message = step.error_message
    action.completed_at = now
    action.save(update_fields=["status", "result", "error_code", "error_message", "completed_at", "updated_at"])
    task.status = status
    task.result = result
    task.error_code = step.error_code
    task.error_message = step.error_message
    task.completed_at = now
    task.lease_expires_at = None
    task.save(update_fields=["status", "result", "error_code", "error_message", "completed_at", "lease_expires_at", "updated_at"])
    if task.status == RpaTask.Status.WAITING_HUMAN and task.error_code == "external_result_uncertain":
        is_rejection = action.action == ConversationAction.Action.REJECTION_NOTICE
        ensure_attention(
            attention_type=HumanAttention.Type.OTHER,
            title="未通过通知发送结果待人工核查" if is_rejection else "BOSS 沟通发送结果待人工核查",
            idempotency_key=(
                f"rejection-notice-result-uncertain:{task.pk}"
                if is_rejection
                else f"communication-result-uncertain:{task.pk}"
            ),
            account=batch.boss_account,
            job=action.application.job,
            application=action.application,
            detail={
                "error_code": "external_result_uncertain",
                "task_id": str(task.pk),
                "conversation_action_id": str(action.pk),
                "instruction": "请在 BOSS 直聘中核查是否已发送；系统不会自动重试",
            },
            priority=100,
        )
    if (
        not plan_fence_closed
        and step_status == StepExecution.Status.SUCCEEDED
        and action.action != ConversationAction.Action.REJECTION_NOTICE
    ):
        event = {
            ConversationAction.Action.GREET: "greet_succeeded",
            ConversationAction.Action.REQUEST_RESUME: "resume_requested",
            ConversationAction.Action.SEND_INTERVIEW: "interview_sent",
        }[action.action]
        advance_for_event(application=action.application, event=event, actor=action.created_by, task=task)
        if action.action == ConversationAction.Action.GREET:
            HumanAttention.objects.select_for_update().filter(
                application=action.application,
                job=action.application.job,
                boss_account=batch.boss_account,
                attention_type=HumanAttention.Type.GREETING_REQUIRED,
                status=HumanAttention.Status.OPEN,
            ).update(
                status=HumanAttention.Status.RESOLVED,
                resolved_by=action.created_by,
                resolution_note="平台稳定身份与打招呼回执已核验，系统自动关闭待打招呼事项",
                resolved_at=now,
                updated_at=now,
            )
    safe_item_waiting_codes = {
        "stable_identity_action_unavailable",
        "target_identity_ambiguous",
        "target_identity_missing",
    }
    stop_remaining_batch = (
        plan_fence_closed
        or task.error_code == "external_result_uncertain"
        or (
            action.action == ConversationAction.Action.REJECTION_NOTICE
            and (
            step_status == StepExecution.Status.FAILED
            or unverified_success
            or (
                step_status == StepExecution.Status.WAITING_HUMAN
                and step.error_code not in safe_item_waiting_codes
            )
            )
        )
    )
    if stop_remaining_batch:
        cancel_code = (
            "rejection_batch_stopped"
            if action.action == ConversationAction.Action.REJECTION_NOTICE
            else "communication_batch_stopped"
        )
        cancel_message = "前一项外部执行结果不确定或账号环境异常，剩余沟通已停止"
        pending_tasks = RpaTask.objects.select_for_update().filter(
            execution_batch=batch,
            status=RpaTask.Status.PENDING,
        ).exclude(pk=task.pk)
        pending_step_ids = [
            step_id
            for step_id in pending_tasks.values_list("request_payload__step_id", flat=True)
            if step_id is not None
        ]
        pending_step_ids.extend(
            batch.steps.filter(status=StepExecution.Status.PENDING)
            .exclude(pk=step.pk)
            .values_list("pk", flat=True)
        )
        pending_step_ids = list(set(pending_step_ids))
        for pending_task in pending_tasks:
            pending_task.status = RpaTask.Status.CANCELLED
            pending_task.error_code = cancel_code
            pending_task.error_message = cancel_message
            pending_task.completed_at = now
            pending_task.save(update_fields=[
                "status", "error_code", "error_message", "completed_at", "updated_at",
            ])
            append_event(
                task=pending_task,
                event="cancelled",
                message="未通过通知批次因安全边界停止，任务未进入外部适配器",
            )
        StepExecution.objects.filter(pk__in=pending_step_ids).update(
            status=StepExecution.Status.CANCELLED,
            error_code=cancel_code,
            error_message=cancel_message,
            completed_at=now,
            updated_at=now,
        )
        ConversationAction.objects.filter(step_id__in=pending_step_ids).update(
            status=ConversationAction.Status.CANCELLED,
            error_code=cancel_code,
            error_message=cancel_message,
            completed_at=now,
            updated_at=now,
        )
    batch_was_cancelled = batch.status == ExecutionBatch.Status.CANCELLED
    batch.succeeded_items = batch.steps.filter(status=StepExecution.Status.SUCCEEDED).count()
    batch.failed_items = batch.steps.filter(
        status__in=[StepExecution.Status.FAILED, StepExecution.Status.SKIPPED]
    ).count()
    remaining = batch.steps.filter(status=StepExecution.Status.PENDING).exists()
    waiting = batch.steps.filter(status=StepExecution.Status.WAITING_HUMAN).exists()
    if batch_was_cancelled or plan_fence_closed:
        batch.status = ExecutionBatch.Status.CANCELLED
    elif waiting:
        batch.status = ExecutionBatch.Status.WAITING_HUMAN
    elif remaining:
        batch.status = ExecutionBatch.Status.RUNNING
    elif batch.failed_items and batch.succeeded_items:
        batch.status = ExecutionBatch.Status.PARTIAL
    elif batch.failed_items:
        batch.status = ExecutionBatch.Status.FAILED
    else:
        batch.status = ExecutionBatch.Status.SUCCEEDED
    batch.save(update_fields=["succeeded_items", "failed_items", "status", "updated_at"])
    if not batch_was_cancelled and not plan_fence_closed and not waiting and remaining:
        enqueue_next_step(batch)
    return batch


def _conversation_job(*, account, job_title, allowed_job_ids):
    allowed = {int(value) for value in (allowed_job_ids or [])}
    normalized_title = " ".join(str(job_title or "").split()).strip()
    if normalized_title:
        jobs = list(
            RecruitmentJob.objects.filter(
                boss_account=account,
                title=normalized_title,
                archived_at__isnull=True,
            )[:2]
        )
        if len(jobs) != 1:
            return None
        job = jobs[0]
        return job if allowed_job_ids is None or job.pk in allowed else None
    if allowed_job_ids is None or len(allowed) != 1:
        return None
    return RecruitmentJob.objects.filter(
        pk=next(iter(allowed)),
        boss_account=account,
        archived_at__isnull=True,
    ).first()


def _resolve_conversation_application(*, account, row, actor, allowed_job_ids):
    name = " ".join(str(row.get("name", "")).split()).strip()[:100]
    external_id = str(row.get("external_id", "")).strip()[:160]
    job_title = str(row.get("job_title", "")).strip()
    if external_id and name:
        job = _conversation_job(
            account=account,
            job_title=job_title,
            allowed_job_ids=allowed_job_ids,
        )
        if job is None:
            return None, False, False
        from recruitment.services.discovery import _fingerprint

        fingerprint = _fingerprint(account.pk, {"external_id": external_id})
        identity = (
            CandidateExternalIdentity.objects.select_for_update()
            .select_related("candidate")
            .filter(boss_account=account, fingerprint=fingerprint)
            .first()
        )
        candidate_created = False
        if identity is not None:
            if str(identity.external_id).strip() != external_id:
                return None, False, False
            candidate = identity.candidate
        else:
            candidate, candidate_created = Candidate.objects.get_or_create(
                identity_key=f"boss:{account.pk}:{external_id}",
                defaults={"external_id": external_id[:120], "name": name},
            )
            CandidateExternalIdentity.objects.create(
                boss_account=account,
                candidate=candidate,
                external_id=external_id,
                fingerprint=fingerprint,
                identity_quality=CandidateDiscovery.IdentityQuality.PLATFORM,
            )
        application, application_created = JobApplication.objects.get_or_create(
            candidate=candidate,
            job=job,
            defaults={"source": "boss", "owner": actor},
        )
        return application, candidate_created, application_created

    application_queryset = JobApplication.objects.filter(
        job__boss_account=account,
        candidate__name=name,
    )
    if job_title:
        application_queryset = application_queryset.filter(job__title=job_title)
    applications = list(application_queryset.distinct()[:2])
    if len(applications) != 1:
        return None, False, False
    application = applications[0]
    if allowed_job_ids is not None and application.job_id not in set(allowed_job_ids):
        return None, False, False
    return application, False, False


@transaction.atomic
def sync_conversation_states(*, account, rows, actor=None, allowed_job_ids=None):
    if not isinstance(rows, list):
        raise ValueError("沟通状态同步结果无效")
    synced = 0
    ambiguous = 0
    replied = 0
    created_candidates = 0
    created_applications = 0
    for row in rows:
        if not isinstance(row, dict):
            continue
        row.pop("application_id", None)
        if row.get("sync_error"):
            continue
        name = str(row.get("name", "")).strip()
        application, candidate_created, application_created = _resolve_conversation_application(
            account=account,
            row=row,
            actor=actor,
            allowed_job_ids=allowed_job_ids,
        )
        if application is None:
            if name:
                ambiguous += 1
            continue
        row["application_id"] = application.pk
        created_candidates += int(candidate_created)
        created_applications += int(application_created)
        unread = bool(row.get("unread"))
        ConversationSyncState.objects.update_or_create(
            application=application,
            defaults={
                "boss_account": account,
                "cursor": str(row.get("external_id") or row.get("index", ""))[:300],
                "last_message_preview": str(row.get("preview", ""))[:500],
                "has_candidate_reply": unread,
                "last_synced_at": timezone.now(),
            },
        )
        if unread:
            replied += 1
            advance_for_event(application=application, event="candidate_replied", actor=actor)
        synced += 1
    return {
        "synced": synced,
        "ambiguous": ambiguous,
        "candidate_replies": replied,
        "created_candidates": created_candidates,
        "created_applications": created_applications,
    }
