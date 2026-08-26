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
    CandidateDiscovery,
    CandidateExternalIdentity,
    ConversationAction,
    ConversationSyncState,
    ExecutionBatch,
    HumanAttention,
    InterviewInvitation,
    RecruitmentAuditLog,
    RecruitmentAutomationPlan,
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


def _identity_snapshot(application, account):
    identity = CandidateExternalIdentity.objects.filter(
        candidate=application.candidate, boss_account=account
    ).order_by("-last_seen_at").first()
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
    items = list(applications)
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
    approval, created = AutomationApproval.objects.get_or_create(
        idempotency_key=f"communication:{account.pk}:{action}:{request_key}",
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
        snapshot = _identity_snapshot(application, account)
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
        "application", "batch", "step", "created_by"
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
    )
    unverified_success = status == "succeeded" and not identity_verified
    if status == "succeeded" and identity_verified:
        step_status = StepExecution.Status.SUCCEEDED
        action_status = ConversationAction.Status.SUCCEEDED
    elif status == "waiting_human" or (status == "succeeded" and not identity_verified):
        step_status = StepExecution.Status.WAITING_HUMAN
        action_status = ConversationAction.Status.WAITING_HUMAN
        status = "waiting_human"
        if unverified_success and action.action == ConversationAction.Action.REJECTION_NOTICE:
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


@transaction.atomic
def sync_conversation_states(*, account, rows, actor=None, allowed_job_ids=None):
    if not isinstance(rows, list):
        raise ValueError("沟通状态同步结果无效")
    synced = 0
    ambiguous = 0
    replied = 0
    for row in rows:
        if not isinstance(row, dict):
            continue
        name = str(row.get("name", "")).strip()
        jobs = account.jobs.filter(applications__candidate__name=name)
        applications = list(
            jobs
            .values_list("applications__id", flat=True)
            .distinct()[:2]
        )
        if len(applications) != 1:
            if name:
                ambiguous += 1
            continue
        from recruitment.models import JobApplication

        application = JobApplication.objects.get(pk=applications[0])
        if allowed_job_ids is not None and application.job_id not in allowed_job_ids:
            continue
        unread = bool(row.get("unread"))
        ConversationSyncState.objects.update_or_create(
            application=application,
            defaults={
                "boss_account": account,
                "cursor": str(row.get("index", ""))[:300],
                "last_message_preview": str(row.get("preview", ""))[:500],
                "has_candidate_reply": unread,
                "last_synced_at": timezone.now(),
            },
        )
        if unread:
            replied += 1
            advance_for_event(application=application, event="candidate_replied", actor=actor)
        synced += 1
    return {"synced": synced, "ambiguous": ambiguous, "candidate_replies": replied}
