import hashlib
import json
from datetime import timedelta

from django.db import IntegrityError, transaction
from django.db.models import Max, Q
from django.utils import timezone
from rest_framework.exceptions import APIException, PermissionDenied, ValidationError

from attendance.permissions import is_hr_user
from recruitment.models import (
    AiProcessingTask,
    ApplicationScreeningDecision,
    AutomationApproval,
    BossAccount,
    ConversationAction,
    ExecutionBatch,
    JobApplication,
    JobStandardVersion,
    RecruitmentAuditLog,
    RecruitmentJob,
    Resume,
    ResumeAssessment,
    RpaTask,
    ScreeningDecisionBatch,
    StructuredResumeVersion,
    StepExecution,
)


class ScreeningConflict(APIException):
    status_code = 409
    default_code = "screening_conflict"
    default_detail = "请求标识已被不同内容使用"


FORBIDDEN_REJECTION_STAGES = {
    JobApplication.Stage.TO_INTERVIEW,
    JobApplication.Stage.INTERVIEWING,
    JobApplication.Stage.TO_OFFER,
    JobApplication.Stage.HIRED,
}
SAFE_ITEM_WAITING_CODES = {
    "stable_identity_action_unavailable",
    "target_identity_ambiguous",
    "target_identity_missing",
}


def neutral_rejection_messages(job):
    """Return the complete server-owned allow-list for candidate-facing copy."""
    title = str(job.title or "").strip()
    subject = f"{title}岗位" if title else "该岗位"
    body = "的关注和时间。综合本次招聘安排，我们暂时无法继续推进后续流程，祝您求职顺利。"
    return {
        f"您好，感谢您对{subject}{body}",
        f"您好，感谢您对该岗位{body}",
    }


def validate_neutral_rejection_message(*, job, message):
    normalized = str(message or "").strip()
    if normalized not in neutral_rejection_messages(job):
        raise ValidationError({
            "message": "通知只能使用系统提供的中性模板，不得包含分数、AI 判断、内部原因或候选人敏感原文"
        })
    return normalized


def _payload_hash(payload):
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _current_resume(application):
    return (
        Resume.objects.filter(application=application, archived_at__isnull=True)
        .order_by("-version", "-id")
        .first()
    )


def _score_task_matches_structure(*, task, structure, standard):
    if (
        task.kind != AiProcessingTask.Kind.RESUME_SCORE
        or task.standard_id != standard.pk
        or task.resume_id != structure.resume_id
    ):
        return False
    result_ref = task.result_ref if isinstance(task.result_ref, dict) else {}
    referenced_structure = result_ref.get("structured_resume_id")
    if referenced_structure is not None:
        return str(referenced_structure) == str(structure.pk)
    return str(task.idempotency_key).endswith(f":{structure.pk}:{standard.pk}")


def current_screening_snapshot(*, application, standard=None):
    resume = _current_resume(application)
    if resume is None:
        return {"resume": None, "structure": None, "assessment": None, "ai_state": "no_resume"}
    structure = resume.structured_versions.order_by("-version", "-id").first()
    assessment = None
    if structure is not None and standard is not None:
        assessment = (
            ResumeAssessment.objects.filter(structured_resume=structure, standard=standard)
            .order_by("-version", "-created_at", "-id")
            .first()
        )
    if assessment is not None:
        ai_state = "scored"
    elif standard is None:
        ai_state = "standard_missing"
    else:
        if structure is None:
            task = (
                AiProcessingTask.objects.filter(resume=resume, kind=AiProcessingTask.Kind.RESUME_STRUCTURE)
                .order_by("-updated_at", "-created_at")
                .first()
            )
        else:
            task = next((
                candidate_task
                for candidate_task in AiProcessingTask.objects.filter(
                    resume=resume,
                    kind=AiProcessingTask.Kind.RESUME_SCORE,
                    standard=standard,
                ).order_by("-updated_at", "-created_at")
                if _score_task_matches_structure(
                    task=candidate_task,
                    structure=structure,
                    standard=standard,
                )
            ), None)
        if task is not None and task.status == AiProcessingTask.Status.FAILED:
            ai_state = "failed"
        elif task is not None and task.status in {
            AiProcessingTask.Status.WAITING_CONFIG,
            AiProcessingTask.Status.PENDING,
            AiProcessingTask.Status.EXTRACTING,
            AiProcessingTask.Status.OCR,
            AiProcessingTask.Status.MODEL,
            AiProcessingTask.Status.WAITING_REVIEW,
        }:
            ai_state = "processing"
        else:
            ai_state = "unscored"
    return {
        "resume": resume,
        "structure": structure,
        "assessment": assessment,
        "ai_state": ai_state,
    }


def build_screening_results(*, job):
    standard = (
        JobStandardVersion.objects.filter(job=job, status=JobStandardVersion.Status.PUBLISHED)
        .order_by("-published_at", "-id")
        .first()
    )
    applications = list(
        JobApplication.objects.filter(job=job, archived_at__isnull=True)
        .select_related("candidate", "owner")
        .order_by("id")
    )
    application_ids = [application.pk for application in applications]
    current_resumes = {}
    for resume in (
        Resume.objects.filter(application_id__in=application_ids, archived_at__isnull=True)
        .select_related("candidate", "application__job")
        .order_by("application_id", "-version", "-id")
    ):
        current_resumes.setdefault(resume.application_id, resume)
    resume_ids = [resume.pk for resume in current_resumes.values()]
    current_structures = {}
    for structure in (
        StructuredResumeVersion.objects.filter(resume_id__in=resume_ids)
        .select_related("resume")
        .order_by("resume_id", "-version", "-id")
    ):
        current_structures.setdefault(structure.resume_id, structure)
    structure_ids = [structure.pk for structure in current_structures.values()]
    current_assessments = {}
    if standard is not None:
        for assessment in (
            ResumeAssessment.objects.filter(
                structured_resume_id__in=structure_ids,
                standard=standard,
            )
            .select_related("structured_resume__resume", "standard")
            .order_by("structured_resume_id", "-version", "-created_at", "-id")
        ):
            current_assessments.setdefault(assessment.structured_resume_id, assessment)
    latest_structure_tasks = {}
    latest_score_tasks = {}
    task_scope = Q(kind=AiProcessingTask.Kind.RESUME_STRUCTURE)
    if standard is not None:
        task_scope |= Q(kind=AiProcessingTask.Kind.RESUME_SCORE, standard=standard)
    for task in (
        AiProcessingTask.objects.filter(
            task_scope,
            resume_id__in=resume_ids,
        )
        .order_by("resume_id", "-updated_at", "-created_at")
    ):
        if task.kind == AiProcessingTask.Kind.RESUME_STRUCTURE:
            latest_structure_tasks.setdefault(task.resume_id, task)
            continue
        structure = current_structures.get(task.resume_id)
        if (
            structure is not None
            and standard is not None
            and task.resume_id not in latest_score_tasks
            and _score_task_matches_structure(task=task, structure=structure, standard=standard)
        ):
            latest_score_tasks[task.resume_id] = task
    latest_decisions = {}
    for decision in (
        ApplicationScreeningDecision.objects.filter(application__in=applications)
        .select_related("batch", "decided_by")
        .order_by("application_id", "-version", "-id")
    ):
        latest_decisions.setdefault(decision.application_id, decision)
    latest_notifications = {}
    latest_blocking_notifications = {}
    for action in (
        ConversationAction.objects.filter(
            application__in=applications,
            action=ConversationAction.Action.REJECTION_NOTICE,
        )
        .select_related("approval")
        .order_by("application_id", "-created_at", "-id")
    ):
        if (
            action.status == ConversationAction.Status.DRAFT
            and action.approval is not None
            and (
                action.approval.status in {
                    AutomationApproval.Status.REJECTED,
                    AutomationApproval.Status.EXPIRED,
                }
                or (
                    action.approval.status == AutomationApproval.Status.DRAFT
                    and action.approval.expires_at is not None
                    and action.approval.expires_at <= timezone.now()
                )
            )
        ):
            continue
        latest_notifications.setdefault(action.application_id, action)
        if action.status != ConversationAction.Status.CANCELLED:
            latest_blocking_notifications.setdefault(action.application_id, action)
    latest_notifications.update(latest_blocking_notifications)

    rows = []
    for application in applications:
        resume = current_resumes.get(application.pk)
        structure = current_structures.get(resume.pk) if resume is not None else None
        assessment = current_assessments.get(structure.pk) if structure is not None else None
        task = None
        if resume is not None:
            task = (
                latest_structure_tasks.get(resume.pk)
                if structure is None
                else latest_score_tasks.get(resume.pk)
            )
        if resume is None:
            ai_state = "no_resume"
        elif assessment is not None:
            ai_state = "scored"
        elif standard is None:
            ai_state = "standard_missing"
        elif task is not None and task.status == AiProcessingTask.Status.FAILED:
            ai_state = "failed"
        elif task is not None and task.status in {
            AiProcessingTask.Status.WAITING_CONFIG,
            AiProcessingTask.Status.PENDING,
            AiProcessingTask.Status.EXTRACTING,
            AiProcessingTask.Status.OCR,
            AiProcessingTask.Status.MODEL,
            AiProcessingTask.Status.WAITING_REVIEW,
        }:
            ai_state = "processing"
        else:
            ai_state = "unscored"
        rows.append({
            "application": application,
            "candidate": application.candidate,
            "resume": resume,
            "structure": structure,
            "assessment": assessment,
            "ai_state": ai_state,
            "hr_decision": latest_decisions.get(application.pk),
            "notification": latest_notifications.get(application.pk),
        })
    rows.sort(key=lambda row: (
        row["assessment"] is None,
        -float(row["assessment"].total_score) if row["assessment"] is not None else 0,
        row["application"].pk,
    ))
    rank = 0
    for row in rows:
        if row["assessment"] is None:
            row["rank"] = None
        else:
            rank += 1
            row["rank"] = rank
    return standard, rows


def _recalculate_rejection_batch(batch):
    steps = batch.steps.all()
    batch.succeeded_items = steps.filter(status=StepExecution.Status.SUCCEEDED).count()
    batch.failed_items = steps.filter(
        status__in=[StepExecution.Status.FAILED, StepExecution.Status.SKIPPED]
    ).count()
    if steps.filter(status__in=[
        StepExecution.Status.LEASED,
        StepExecution.Status.RUNNING,
        StepExecution.Status.VERIFYING,
    ]).exists():
        batch.status = ExecutionBatch.Status.RUNNING
    elif steps.filter(status=StepExecution.Status.WAITING_HUMAN).exists():
        batch.status = ExecutionBatch.Status.WAITING_HUMAN
    elif steps.filter(status=StepExecution.Status.PENDING).exists():
        batch.status = (
            ExecutionBatch.Status.RUNNING
            if batch.succeeded_items or batch.failed_items
            else ExecutionBatch.Status.PENDING
        )
    elif steps.filter(status=StepExecution.Status.CANCELLED).count() == steps.count():
        batch.status = ExecutionBatch.Status.CANCELLED
    elif batch.failed_items and batch.succeeded_items:
        batch.status = ExecutionBatch.Status.PARTIAL
    elif batch.failed_items:
        batch.status = ExecutionBatch.Status.FAILED
    elif batch.succeeded_items:
        batch.status = (
            ExecutionBatch.Status.PARTIAL
            if steps.filter(status=StepExecution.Status.CANCELLED).exists()
            else ExecutionBatch.Status.SUCCEEDED
        )
    else:
        batch.status = ExecutionBatch.Status.CANCELLED
    batch.save(update_fields=["succeeded_items", "failed_items", "status", "updated_at"])


def invalidate_rejection_work_for_application(*, application, actor, trigger):
    """Call only after locking account then application; all rejection paths use this lock order."""
    # Complete-task handling already holds the task before it locks its action.
    # Discover action ids without locks, then take task -> action locks so this
    # path cannot deadlock with a completion that is racing the HR operation.
    action_ids = list(
        ConversationAction.objects.filter(
            application=application,
            action=ConversationAction.Action.REJECTION_NOTICE,
            status__in=[
                ConversationAction.Status.DRAFT,
                ConversationAction.Status.APPROVED,
                ConversationAction.Status.PENDING,
                ConversationAction.Status.RUNNING,
                ConversationAction.Status.WAITING_HUMAN,
            ],
        )
        .order_by("pk")
        .values_list("pk", flat=True)
    )
    if not action_ids:
        return 0
    tasks = list(
        RpaTask.objects.select_for_update()
        .filter(
            action=RpaTask.Action.REJECTION_NOTICE,
            request_payload__conversation_action_id__in=[str(value) for value in action_ids],
        )
        .order_by("created_at", "pk")
    )
    actions = list(
        ConversationAction.objects.select_for_update()
        .filter(pk__in=action_ids)
        .select_related("step", "batch")
        .order_by("pk")
    )
    externally_entered = [
        task for task in tasks
        if task.status in {RpaTask.Status.LEASED, RpaTask.Status.RUNNING}
        or (
            task.status == RpaTask.Status.WAITING_HUMAN
            and task.error_code not in SAFE_ITEM_WAITING_CODES
        )
    ]
    if externally_entered or any(
        action.status == ConversationAction.Status.RUNNING
        for action in actions
    ):
        raise ScreeningConflict("未通过通知已进入外部执行或结果待核查，当前操作已阻止，请先人工确认")

    now = timezone.now()
    cancelled_task_ids = []
    for task in tasks:
        if task.status not in {RpaTask.Status.PENDING, RpaTask.Status.WAITING_HUMAN}:
            continue
        task.status = RpaTask.Status.CANCELLED
        task.error_code = "rejection_snapshot_invalidated"
        task.error_message = "人工结论或招聘阶段已变化，任务在进入外部适配器前取消"
        task.completed_at = now
        task.lease_expires_at = None
        task.save(update_fields=[
            "status", "error_code", "error_message", "completed_at", "lease_expires_at", "updated_at",
        ])
        cancelled_task_ids.append(task.pk)
    step_ids = [action.step_id for action in actions if action.step_id]
    StepExecution.objects.filter(
        pk__in=step_ids,
        status__in=[StepExecution.Status.PENDING, StepExecution.Status.WAITING_HUMAN],
    ).update(
        status=StepExecution.Status.CANCELLED,
        error_code="rejection_snapshot_invalidated",
        error_message="人工结论或招聘阶段已变化，步骤已取消",
        completed_at=now,
        updated_at=now,
    )
    cancelled_actions = ConversationAction.objects.filter(
        pk__in=[action.pk for action in actions],
        status__in=[
            ConversationAction.Status.DRAFT,
            ConversationAction.Status.APPROVED,
            ConversationAction.Status.PENDING,
            ConversationAction.Status.WAITING_HUMAN,
        ],
    ).update(
        status=ConversationAction.Status.CANCELLED,
        error_code="rejection_snapshot_invalidated",
        error_message="人工结论或招聘阶段已变化，通知已取消",
        completed_at=now,
        updated_at=now,
    )
    batch_ids = {action.batch_id for action in actions if action.batch_id}
    for batch in ExecutionBatch.objects.select_for_update().filter(pk__in=batch_ids).order_by("pk"):
        _recalculate_rejection_batch(batch)
    if cancelled_actions or cancelled_task_ids:
        RecruitmentAuditLog.objects.create(
            actor=actor,
            boss_account=application.job.boss_account,
            action="rejection_notice_invalidated_before_send",
            target_id=str(application.pk),
            detail={
                "trigger": str(trigger)[:64],
                "cancelled_actions": cancelled_actions,
                "cancelled_tasks": len(cancelled_task_ids),
            },
        )
    return cancelled_actions


def rejection_task_snapshot_is_current(*, task, application):
    payload = task.request_payload if isinstance(task.request_payload, dict) else {}
    target = payload.get("target") if isinstance(payload.get("target"), dict) else {}
    try:
        action = (
            ConversationAction.objects.select_for_update()
            .select_related("approval", "step", "batch")
            .get(pk=payload.get("conversation_action_id"))
        )
    except (ConversationAction.DoesNotExist, ValueError, TypeError):
        return False, None
    latest = (
        ApplicationScreeningDecision.objects.filter(application=application)
        .order_by("-version", "-id")
        .first()
    )
    valid = (
        task.action == RpaTask.Action.REJECTION_NOTICE
        and task.status == RpaTask.Status.PENDING
        and action.action == ConversationAction.Action.REJECTION_NOTICE
        and action.status == ConversationAction.Status.PENDING
        and action.application_id == application.pk
        and action.approval_id == task.approval_id
        and action.batch_id == task.execution_batch_id
        and action.step_id == payload.get("step_id")
        and action.message_snapshot == payload.get("message")
        and target == action.target_snapshot
        and target.get("application_id") == application.pk
        and target.get("job_id") == application.job_id
        and target.get("boss_account_id") == task.boss_account_id
        and latest is not None
        and latest.pk == target.get("screening_decision_id")
        and latest.decision == ApplicationScreeningDecision.Decision.FAIL
        and application.archived_at is None
        and application.candidate.archived_at is None
        and application.job.archived_at is None
        and application.job.status == RecruitmentJob.Status.OPEN
        and application.stage not in FORBIDDEN_REJECTION_STAGES
        and task.approval is not None
        and task.approval.status == AutomationApproval.Status.APPROVED
        and task.approval.action == AutomationApproval.Action.REJECTION_NOTICE
    )
    return valid, action


def cancel_stale_rejection_task_before_lease(*, task, application=None, action=None):
    now = timezone.now()
    task.status = RpaTask.Status.CANCELLED
    task.error_code = "rejection_snapshot_stale"
    task.error_message = "人工结论、招聘阶段或通知快照已变化，任务未进入外部适配器"
    task.completed_at = now
    task.lease_expires_at = None
    task.save(update_fields=[
        "status", "error_code", "error_message", "completed_at", "lease_expires_at", "updated_at",
    ])
    if action is not None:
        if action.step_id:
            StepExecution.objects.filter(
                pk=action.step_id,
                status=StepExecution.Status.PENDING,
            ).update(
                status=StepExecution.Status.CANCELLED,
                error_code="rejection_snapshot_stale",
                error_message="租约前复核发现快照已变化，步骤已取消",
                completed_at=now,
                updated_at=now,
            )
        if action.status == ConversationAction.Status.PENDING:
            action.status = ConversationAction.Status.CANCELLED
            action.error_code = "rejection_snapshot_stale"
            action.error_message = "租约前复核发现快照已变化，通知已取消"
            action.completed_at = now
            action.save(update_fields=[
                "status", "error_code", "error_message", "completed_at", "updated_at",
            ])
        if action.batch_id:
            batch = ExecutionBatch.objects.select_for_update().get(pk=action.batch_id)
            _recalculate_rejection_batch(batch)
    RecruitmentAuditLog.objects.create(
        boss_account=task.boss_account,
        action="rejection_notice_cancelled_at_lease_guard",
        target_id=str(task.pk),
        detail={
            "application_id": application.pk if application is not None else None,
            "error_code": task.error_code,
        },
    )


def _decision_payload(*, request_id, job, application_ids, decision, reason, actor):
    return {
        "request_id": str(request_id),
        "job": job.pk,
        "application_ids": sorted(application_ids),
        "decision": decision,
        "reason": reason,
        "actor": actor.pk,
    }


def _existing_decision_batch(*, request_id, payload_hash, actor):
    existing = (
        ScreeningDecisionBatch.objects.filter(request_id=request_id)
        .select_related("job", "created_by")
        .prefetch_related("decisions__decided_by")
        .first()
    )
    if existing is None:
        return None
    if existing.payload_hash != payload_hash or existing.created_by_id != actor.pk:
        raise ScreeningConflict()
    return existing


@transaction.atomic
def _create_screening_decisions_atomic(*, request_id, job, application_ids, decision, reason, actor, payload_hash):
    existing = _existing_decision_batch(
        request_id=request_id,
        payload_hash=payload_hash,
        actor=actor,
    )
    if existing is not None:
        return existing, False
    expected_account_id = job.boss_account_id
    if expected_account_id:
        BossAccount.objects.select_for_update().get(pk=expected_account_id)
    job = (
        RecruitmentJob.objects.select_for_update()
        .select_related("boss_account")
        .get(pk=job.pk)
    )
    if job.archived_at is not None:
        raise ValidationError("所选岗位已归档，请刷新后重试")
    if job.boss_account_id != expected_account_id:
        raise ScreeningConflict("岗位绑定的 BOSS 账号已变化，请刷新后重试")
    applications = list(
        JobApplication.objects.select_for_update()
        .select_related("candidate", "job")
        .filter(pk__in=application_ids, job=job, archived_at__isnull=True)
        .order_by("pk")
    )
    if len(applications) != len(application_ids):
        raise ValidationError({"application_ids": "部分候选人不存在、已归档或不属于所选岗位"})
    for application in applications:
        invalidate_rejection_work_for_application(
            application=application,
            actor=actor,
            trigger="screening_decision_changed",
        )
    standard = (
        JobStandardVersion.objects.filter(job=job, status=JobStandardVersion.Status.PUBLISHED)
        .order_by("-published_at", "-id")
        .first()
    )
    versions = {
        row["application_id"]: row["latest_version"] or 0
        for row in ApplicationScreeningDecision.objects.filter(application__in=applications)
        .values("application_id")
        .annotate(latest_version=Max("version"))
    }
    batch = ScreeningDecisionBatch.objects.create(
        request_id=request_id,
        job=job,
        decision=decision,
        reason=reason,
        payload_hash=payload_hash,
        created_by=actor,
    )
    for application in applications:
        snapshot = current_screening_snapshot(application=application, standard=standard)
        ApplicationScreeningDecision.objects.create(
            batch=batch,
            application=application,
            resume=snapshot["resume"],
            assessment=snapshot["assessment"],
            decision=decision,
            reason=reason,
            version=versions.get(application.pk, 0) + 1,
            decided_by=actor,
        )
    RecruitmentAuditLog.objects.create(
        actor=actor,
        boss_account=job.boss_account,
        action="screening_decision_batch_created",
        target_id=str(batch.pk),
        detail={"job_id": job.pk, "decision": decision, "item_count": len(applications)},
    )
    return batch, True


def create_screening_decisions(*, request_id, job, application_ids, decision, reason, actor):
    ids = list(dict.fromkeys(application_ids))
    if not ids or len(ids) > 100 or len(ids) != len(application_ids):
        raise ValidationError({"application_ids": "请选择 1 到 100 位不重复的候选人"})
    normalized_reason = str(reason or "").strip()
    if not normalized_reason or len(normalized_reason) > 1000:
        raise ValidationError({"reason": "内部筛选理由必须为 1 到 1000 个字符"})
    if decision not in ApplicationScreeningDecision.Decision.values:
        raise ValidationError({"decision": "筛选结论必须为 pass 或 fail"})
    payload = _decision_payload(
        request_id=request_id,
        job=job,
        application_ids=ids,
        decision=decision,
        reason=normalized_reason,
        actor=actor,
    )
    payload_hash = _payload_hash(payload)
    try:
        return _create_screening_decisions_atomic(
            request_id=request_id,
            job=job,
            application_ids=ids,
            decision=decision,
            reason=normalized_reason,
            actor=actor,
            payload_hash=payload_hash,
        )
    except IntegrityError:
        existing = _existing_decision_batch(
            request_id=request_id,
            payload_hash=payload_hash,
            actor=actor,
        )
        if existing is None:
            raise ScreeningConflict("候选人的人工筛选结论已变化，请刷新后重试")
        return existing, False


def _ensure_rejection_actor(*, account, actor):
    if actor.is_superuser:
        return
    if not is_hr_user(actor) or not account.authorized_users.filter(pk=actor.pk).exists():
        raise PermissionDenied("无权操作该 BOSS 账号")


def lock_rejection_approval_domain(*, approval):
    """Lock account -> screening batch -> applications before approval/task rows."""
    payload = approval.payload if isinstance(approval.payload, dict) else {}
    BossAccount.objects.select_for_update().get(pk=approval.boss_account_id)
    try:
        batch = (
            ScreeningDecisionBatch.objects.select_for_update()
            .select_related("job")
            .get(pk=payload.get("decision_batch_id"))
        )
    except (ScreeningDecisionBatch.DoesNotExist, ValueError, TypeError):
        raise ValidationError("未通过通知引用的人工筛选批次无效")
    if batch.job.boss_account_id != approval.boss_account_id:
        raise ValidationError("未通过通知确认快照范围无效")
    application_ids = list(
        batch.decisions.order_by("application_id").values_list("application_id", flat=True)
    )
    list(
        JobApplication.objects.select_for_update()
        .filter(pk__in=application_ids)
        .order_by("pk")
    )
    return batch


def cancel_rejection_draft_actions_for_approval(*, approval, actor, reason):
    now = timezone.now()
    actions = list(
        ConversationAction.objects.select_for_update()
        .filter(
            approval=approval,
            action=ConversationAction.Action.REJECTION_NOTICE,
            status=ConversationAction.Status.DRAFT,
        )
        .order_by("pk")
    )
    for action in actions:
        action.status = ConversationAction.Status.CANCELLED
        action.error_code = "approval_no_longer_active"
        action.error_message = "确认项已过期或被拒绝，未通过通知草稿已取消"
        action.completed_at = now
        action.save(update_fields=[
            "status", "error_code", "error_message", "completed_at", "updated_at",
        ])
    if actions:
        RecruitmentAuditLog.objects.create(
            actor=actor,
            boss_account=approval.boss_account,
            action="rejection_notice_drafts_cancelled",
            target_id=str(approval.pk),
            detail={"reason": str(reason)[:64], "cancelled_actions": len(actions)},
        )
    return len(actions)


def _validated_rejection_decisions(batch, *, lock_applications=False):
    decision_queryset = batch.decisions.select_related(
        "application__candidate", "application__job"
    ).order_by("application_id")
    decisions = list(decision_queryset)
    if not decisions or batch.decision != ScreeningDecisionBatch.Decision.FAIL:
        raise ValidationError("未通过通知只能基于人工未通过结论创建")
    locked_applications = {}
    if lock_applications:
        locked_applications = JobApplication.objects.select_for_update().filter(
            pk__in=[decision.application_id for decision in decisions]
        ).order_by("pk").in_bulk()
    for decision in decisions:
        application = locked_applications.get(decision.application_id, decision.application)
        latest = (
            ApplicationScreeningDecision.objects.filter(application_id=decision.application_id)
            .order_by("-version", "-id")
            .first()
        )
        if latest is None or latest.pk != decision.pk or latest.decision != ApplicationScreeningDecision.Decision.FAIL:
            raise ValidationError("候选人的最新人工结论已变化，请刷新后重新选择")
        if (
            application.archived_at is not None
            or application.candidate.archived_at is not None
            or application.job.archived_at is not None
            or application.job.status != RecruitmentJob.Status.OPEN
            or application.stage in FORBIDDEN_REJECTION_STAGES
        ):
            raise ValidationError("候选人或岗位已归档、关闭，或已进入面试、Offer、录用阶段，不能自动发送未通过通知")
        if application.job_id != batch.job_id:
            raise ValidationError("筛选结论与岗位范围不一致")
    return decisions


@transaction.atomic
def prepare_rejection_notice(*, request_id, decision_batch, message, actor):
    account_id = (
        ScreeningDecisionBatch.objects.filter(pk=decision_batch.pk)
        .values_list("job__boss_account_id", flat=True)
        .get()
    )
    if account_id is None:
        raise ValidationError("该岗位没有可用的 BOSS 账号")
    account = BossAccount.objects.select_for_update().get(pk=account_id)
    batch = (
        ScreeningDecisionBatch.objects.select_for_update()
        .select_related("job__boss_account")
        .get(pk=decision_batch.pk)
    )
    if not account.active:
        raise ValidationError("该岗位没有可用的 BOSS 账号")
    _ensure_rejection_actor(account=account, actor=actor)
    normalized_message = str(message or "").strip()
    if not normalized_message or len(normalized_message) > 1000:
        raise ValidationError({"message": "最终通知文案必须为 1 到 1000 个字符"})
    request_scope = {
        "request_id": str(request_id),
        "decision_batch_id": str(batch.pk),
        "message": normalized_message,
        "actor": actor.pk,
        "account": account.pk,
    }
    request_hash = _payload_hash(request_scope)
    idempotency_key = f"rejection-notice:{account.pk}:{request_id}"
    existing = AutomationApproval.objects.filter(idempotency_key=idempotency_key).first()
    if existing is not None:
        existing_payload = existing.payload if isinstance(existing.payload, dict) else {}
        if (
            existing.action != AutomationApproval.Action.REJECTION_NOTICE
            or existing.boss_account_id != account.pk
            or existing.created_by_id != actor.pk
            or existing_payload.get("request_payload_hash") != request_hash
        ):
            raise ScreeningConflict()
        return existing, False
    normalized_message = validate_neutral_rejection_message(job=batch.job, message=normalized_message)
    decisions = _validated_rejection_decisions(batch, lock_applications=True)
    draft_rows = list(
        ConversationAction.objects.filter(
            application_id__in=[decision.application_id for decision in decisions],
            action=ConversationAction.Action.REJECTION_NOTICE,
            status=ConversationAction.Status.DRAFT,
        )
        .order_by("pk")
        .values("pk", "approval_id")
    )
    approval_ids = sorted({row["approval_id"] for row in draft_rows if row["approval_id"]})
    approvals = {
        approval.pk: approval
        for approval in AutomationApproval.objects.select_for_update()
        .filter(pk__in=approval_ids)
        .order_by("pk")
    }
    now = timezone.now()
    stale_approval_ids = set()
    for approval in approvals.values():
        if approval.status in {AutomationApproval.Status.REJECTED, AutomationApproval.Status.EXPIRED}:
            stale_approval_ids.add(approval.pk)
        elif (
            approval.status == AutomationApproval.Status.DRAFT
            and approval.expires_at is not None
            and approval.expires_at <= now
        ):
            approval.status = AutomationApproval.Status.EXPIRED
            approval.save(update_fields=["status"])
            stale_approval_ids.add(approval.pk)
    stale_action_ids = [
        row["pk"] for row in draft_rows if row["approval_id"] in stale_approval_ids
    ]
    if stale_action_ids:
        stale_actions = list(
            ConversationAction.objects.select_for_update()
            .filter(pk__in=stale_action_ids, status=ConversationAction.Status.DRAFT)
            .order_by("pk")
        )
        for action in stale_actions:
            action.status = ConversationAction.Status.CANCELLED
            action.error_code = "approval_no_longer_active"
            action.error_message = "确认项已过期或被拒绝，未通过通知草稿已取消"
            action.completed_at = now
            action.save(update_fields=[
                "status", "error_code", "error_message", "completed_at", "updated_at",
            ])
        RecruitmentAuditLog.objects.create(
            actor=actor,
            boss_account=account,
            action="stale_rejection_notice_drafts_cancelled",
            target_id=str(batch.pk),
            detail={"cancelled_actions": len(stale_actions)},
        )
    blocked_statuses = {
        ConversationAction.Status.DRAFT,
        ConversationAction.Status.APPROVED,
        ConversationAction.Status.PENDING,
        ConversationAction.Status.RUNNING,
        ConversationAction.Status.WAITING_HUMAN,
        ConversationAction.Status.SUCCEEDED,
        ConversationAction.Status.FAILED,
    }
    if ConversationAction.objects.filter(
        application_id__in=[decision.application_id for decision in decisions],
        action=ConversationAction.Action.REJECTION_NOTICE,
        status__in=blocked_statuses,
    ).exists():
        raise ValidationError("部分候选人已有待确认、执行中、待人工或已成功的未通过通知，不能重复创建")

    from recruitment.services.communications import _identity_snapshot

    approval = AutomationApproval.objects.create(
        idempotency_key=idempotency_key,
        action=AutomationApproval.Action.REJECTION_NOTICE,
        boss_account=account,
        created_by=actor,
        payload={
            "action": ConversationAction.Action.REJECTION_NOTICE,
            "message": normalized_message,
            "decision_batch_id": str(batch.pk),
            "request_payload_hash": request_hash,
            "items": [],
        },
        item_count=len(decisions),
        expires_at=timezone.now() + timedelta(minutes=30),
    )
    items = []
    for decision in decisions:
        snapshot = _identity_snapshot(decision.application, account)
        snapshot.update({
            "screening_decision_id": decision.pk,
            "screening_decision_batch_id": str(batch.pk),
        })
        digest = hashlib.sha256(
            f"{approval.pk}:{decision.application_id}:rejection_notice".encode("utf-8")
        ).hexdigest()[:24]
        action = ConversationAction.objects.create(
            application=decision.application,
            boss_account=account,
            action=ConversationAction.Action.REJECTION_NOTICE,
            message_snapshot=normalized_message,
            target_snapshot=snapshot,
            idempotency_key=f"conversation:{digest}",
            approval=approval,
            created_by=actor,
        )
        items.append({"conversation_action_id": str(action.pk), **snapshot})
    approval.payload["items"] = items
    approval.save(update_fields=["payload"])
    RecruitmentAuditLog.objects.create(
        actor=actor,
        boss_account=account,
        action="rejection_notice_prepared",
        target_id=str(approval.pk),
        detail={"job_id": batch.job_id, "item_count": len(decisions)},
    )
    return approval, True


def validate_rejection_approval_snapshot(*, approval):
    payload = approval.payload if isinstance(approval.payload, dict) else {}
    try:
        batch = ScreeningDecisionBatch.objects.select_for_update().select_related("job__boss_account").get(
            pk=payload.get("decision_batch_id")
        )
    except (ScreeningDecisionBatch.DoesNotExist, ValueError, TypeError):
        raise ValidationError("未通过通知引用的人工筛选批次无效")
    if (
        approval.action != AutomationApproval.Action.REJECTION_NOTICE
        or payload.get("action") != ConversationAction.Action.REJECTION_NOTICE
        or batch.job.boss_account_id != approval.boss_account_id
    ):
        raise ValidationError("未通过通知确认快照范围无效")
    validate_neutral_rejection_message(job=batch.job, message=payload.get("message"))
    decisions = _validated_rejection_decisions(batch, lock_applications=True)
    items = payload.get("items") if isinstance(payload.get("items"), list) else []
    actions = list(
        ConversationAction.objects.filter(approval=approval).select_related("application__candidate").order_by("application_id")
    )
    if len(decisions) != approval.item_count or len(items) != len(decisions) or len(actions) != len(decisions):
        raise ValidationError("未通过通知确认快照条目不完整")
    decisions_by_id = {decision.pk: decision for decision in decisions}
    if ConversationAction.objects.filter(
        application_id__in=[decision.application_id for decision in decisions],
        action=ConversationAction.Action.REJECTION_NOTICE,
        status__in=[
            ConversationAction.Status.DRAFT,
            ConversationAction.Status.APPROVED,
            ConversationAction.Status.PENDING,
            ConversationAction.Status.RUNNING,
            ConversationAction.Status.WAITING_HUMAN,
            ConversationAction.Status.SUCCEEDED,
            ConversationAction.Status.FAILED,
        ],
    ).exclude(approval=approval).exists():
        raise ValidationError("部分候选人已有未结束、失败或已成功的未通过通知，不能重复执行")
    items_by_action = {
        str(item.get("conversation_action_id", "")): item
        for item in items
        if isinstance(item, dict)
    }
    for action in actions:
        item = items_by_action.get(str(action.pk))
        target = action.target_snapshot if isinstance(action.target_snapshot, dict) else {}
        decision = decisions_by_id.get(target.get("screening_decision_id"))
        if (
            item is None
            or decision is None
            or action.action != ConversationAction.Action.REJECTION_NOTICE
            or action.application_id != decision.application_id
            or action.message_snapshot != payload.get("message")
            or item != {"conversation_action_id": str(action.pk), **target}
        ):
            raise ValidationError("未通过通知确认快照被修改或目标不一致")
    return actions
