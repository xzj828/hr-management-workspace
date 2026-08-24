import hashlib
from datetime import timedelta

from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError

from attendance.permissions import is_hr_user
from recruitment.models import (
    AutomationApproval,
    CandidateExternalIdentity,
    ConversationAction,
    ExecutionBatch,
    InterviewInvitation,
    RecruitmentAuditLog,
    StepExecution,
)
from recruitment.rpa.tasks import create_task
from recruitment.services.stages import advance_for_event


ACTION_TO_APPROVAL = {
    ConversationAction.Action.GREET: AutomationApproval.Action.GREET,
    ConversationAction.Action.REQUEST_RESUME: AutomationApproval.Action.REQUEST_RESUME,
    ConversationAction.Action.SEND_INTERVIEW: AutomationApproval.Action.SEND_INTERVIEW,
}


def _identity_snapshot(application, account):
    identity = CandidateExternalIdentity.objects.filter(
        candidate=application.candidate, boss_account=account
    ).order_by("-last_seen_at").first()
    return {
        "boss_account_id": account.pk,
        "candidate_id": application.candidate_id,
        "application_id": application.pk,
        "name": application.candidate.name,
        "external_id": identity.external_id if identity else application.candidate.external_id,
        "fingerprint": identity.fingerprint if identity else "",
        "job_id": application.job_id,
        "job_title": application.job.title,
    }


@transaction.atomic
def prepare_communication(*, account, applications, action, message, actor, request_id, invitation=None):
    if not is_hr_user(actor) or not account.authorized_users.filter(pk=actor.pk).exists():
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
    approval, created = AutomationApproval.objects.get_or_create(
        idempotency_key=f"communication:{account.pk}:{action}:{request_key}",
        defaults={
            "action": ACTION_TO_APPROVAL[action],
            "boss_account": account,
            "created_by": actor,
            "payload": {"action": action, "message": normalized, "invitation": invitation or {}, "items": []},
            "item_count": len(items),
            "expires_at": timezone.now() + timedelta(minutes=30),
        },
    )
    if not created:
        return approval
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
        payload_items.append({"conversation_action_id": str(conversation.pk), **snapshot})
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
    if batch.rpa_tasks.filter(status__in=["pending", "leased", "running"]).exists():
        return None
    step = batch.steps.filter(status=StepExecution.Status.PENDING).order_by("created_at").first()
    if step is None:
        return None
    action = step.conversation_action
    task = create_task(
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
    )
    return task


@transaction.atomic
def materialize_communication_batch(*, approval, actor):
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
        },
    )
    if batch.steps.exists():
        return batch
    actions = ConversationAction.objects.filter(approval=locked).select_related("application__candidate")
    for action in actions:
        skipped = _is_duplicate_greet(action)
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
    enqueue_next_step(batch)
    return batch


@transaction.atomic
def complete_communication_task(*, task, status, result, error_code, error_message):
    action = ConversationAction.objects.select_for_update().select_related(
        "application", "batch", "step", "created_by"
    ).get(pk=task.request_payload.get("conversation_action_id"))
    step = StepExecution.objects.select_for_update().get(pk=action.step_id)
    batch = ExecutionBatch.objects.select_for_update().get(pk=action.batch_id)
    now = timezone.now()
    if status == "succeeded" and result.get("verified") is True:
        step_status = StepExecution.Status.SUCCEEDED
        action_status = ConversationAction.Status.SUCCEEDED
    elif status == "waiting_human" or (status == "succeeded" and result.get("verified") is not True):
        step_status = StepExecution.Status.WAITING_HUMAN
        action_status = ConversationAction.Status.WAITING_HUMAN
        status = "waiting_human"
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
    if step_status == StepExecution.Status.SUCCEEDED:
        event = {
            ConversationAction.Action.GREET: "greet_succeeded",
            ConversationAction.Action.REQUEST_RESUME: "resume_requested",
            ConversationAction.Action.SEND_INTERVIEW: "interview_sent",
        }[action.action]
        advance_for_event(application=action.application, event=event, actor=action.created_by, task=task)
    batch.succeeded_items = batch.steps.filter(status=StepExecution.Status.SUCCEEDED).count()
    batch.failed_items = batch.steps.filter(
        status__in=[StepExecution.Status.FAILED, StepExecution.Status.SKIPPED]
    ).count()
    remaining = batch.steps.filter(status=StepExecution.Status.PENDING).exists()
    waiting = batch.steps.filter(status=StepExecution.Status.WAITING_HUMAN).exists()
    if waiting:
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
    if not waiting and remaining:
        enqueue_next_step(batch)
    return batch
