from datetime import timedelta
from dataclasses import dataclass
import hashlib
import threading
import uuid

from django.contrib.auth import get_user_model
from django.db import connection, transaction
from django.utils import timezone

from accounts.models import UserModelCredential
from accounts.services.model_gateway import ModelGatewayError
from recruitment.models import AiProcessingTask, JobRequirementDocument
from recruitment.services.file_extraction import ExtractionError


RETRY_DELAYS = (30, 120, 300)
PROMPT_REVISION = "phase3-v2"
LEASE_SECONDS = 180


@dataclass(frozen=True, repr=False)
class TaskModelCredential:
    api_url: str
    model: str
    encrypted_api_key: str
    fingerprint: str


def _credential_snapshot(credential) -> TaskModelCredential | None:
    if not credential:
        return None
    api_url = str(credential.api_url or "").strip()
    model = str(credential.model or "").strip()
    encrypted_api_key = str(credential.encrypted_api_key or "")
    if not api_url or not model or not encrypted_api_key:
        return None
    fingerprint = hashlib.sha256(
        "\0".join((api_url, model, encrypted_api_key)).encode("utf-8")
    ).hexdigest()
    return TaskModelCredential(
        api_url=api_url,
        model=model,
        encrypted_api_key=encrypted_api_key,
        fingerprint=fingerprint,
    )


def _capture_current_snapshot_locked(user) -> TaskModelCredential | None:
    credential = UserModelCredential.objects.select_for_update().filter(user=user).first()
    return _credential_snapshot(credential)


def _lock_user_and_capture_snapshot(user):
    locked_user = get_user_model().objects.select_for_update().get(pk=user.pk)
    return locked_user, _capture_current_snapshot_locked(locked_user)


def _snapshot_fingerprint(snapshot: TaskModelCredential | None) -> str:
    return snapshot.fingerprint[:12] if snapshot else "unconfigured"


def _snapshot_defaults(snapshot: TaskModelCredential | None) -> dict:
    if not snapshot:
        return {"status": AiProcessingTask.Status.WAITING_CONFIG}
    return {
        "status": AiProcessingTask.Status.PENDING,
        "model_api_url_snapshot": snapshot.api_url,
        "model_name_snapshot": snapshot.model,
        "encrypted_model_api_key_snapshot": snapshot.encrypted_api_key,
        "model_snapshot_fingerprint": snapshot.fingerprint,
        "model_snapshot_bound_at": timezone.now(),
    }


def _apply_snapshot(task: AiProcessingTask, snapshot: TaskModelCredential, *, bound_at=None):
    task.model_api_url_snapshot = snapshot.api_url
    task.model_name_snapshot = snapshot.model
    task.encrypted_model_api_key_snapshot = snapshot.encrypted_api_key
    task.model_snapshot_fingerprint = snapshot.fingerprint
    task.model_snapshot_bound_at = bound_at or timezone.now()


def task_model_credential(task: AiProcessingTask) -> TaskModelCredential:
    if task.model_snapshot_bound_at is None:
        raise ModelGatewayError("model_not_configured", "AI 任务尚未绑定可用的模型连接")
    snapshot = TaskModelCredential(
        api_url=str(task.model_api_url_snapshot or "").strip(),
        model=str(task.model_name_snapshot or "").strip(),
        encrypted_api_key=str(task.encrypted_model_api_key_snapshot or ""),
        fingerprint=str(task.model_snapshot_fingerprint or ""),
    )
    if not all((snapshot.api_url, snapshot.model, snapshot.encrypted_api_key, snapshot.fingerprint)):
        raise ModelGatewayError("model_snapshot_invalid", "AI 任务绑定的模型连接快照不完整")
    return snapshot


def _current_document_versions(job):
    return list(
        JobRequirementDocument.objects.filter(job=job, archived_at__isnull=True, current_version__isnull=False)
        .select_related("current_version")
        .order_by("id")
        .values_list("current_version_id", "current_version__sha256")
    )


@transaction.atomic
def enqueue_job_standard(*, job, requested_by, request_id=None) -> tuple[AiProcessingTask, bool]:
    locked_user, snapshot = _lock_user_and_capture_snapshot(requested_by)
    versions = _current_document_versions(job)
    if not versions:
        raise ValueError("该职位没有可解析的岗位 Word 文档")
    fingerprint = ":".join(sha[:12] for _, sha in versions)
    generation = str(request_id or "auto")
    key = f"job-standard:{job.pk}:{locked_user.pk}:{_snapshot_fingerprint(snapshot)}:{PROMPT_REVISION}:{fingerprint}:{generation}"
    return AiProcessingTask.objects.get_or_create(
        idempotency_key=key,
        defaults={
            "kind": AiProcessingTask.Kind.JOB_STANDARD,
            "requested_by": locked_user,
            "job": job,
            "document_version_id": versions[-1][0],
            **_snapshot_defaults(snapshot),
        },
    )


@transaction.atomic
def enqueue_resume_structure(*, resume, requested_by, request_id=None) -> tuple[AiProcessingTask, bool]:
    locked_user, snapshot = _lock_user_and_capture_snapshot(requested_by)
    key = f"resume-structure:{resume.pk}:{locked_user.pk}:{_snapshot_fingerprint(snapshot)}:{PROMPT_REVISION}:{resume.sha256 or resume.version}:{request_id or 'auto'}"
    return AiProcessingTask.objects.get_or_create(
        idempotency_key=key,
        defaults={
            "kind": AiProcessingTask.Kind.RESUME_STRUCTURE,
            "requested_by": locked_user,
            "job": resume.application.job if resume.application_id else None,
            "resume": resume,
            **_snapshot_defaults(snapshot),
        },
    )


@transaction.atomic
def enqueue_resume_score(*, structured_resume, standard, requested_by, request_id=None) -> tuple[AiProcessingTask, bool]:
    locked_user, snapshot = _lock_user_and_capture_snapshot(requested_by)
    request_id = request_id or uuid.uuid4()
    key = f"resume-score:{request_id}:{structured_resume.pk}:{standard.pk}"
    return AiProcessingTask.objects.get_or_create(
        idempotency_key=key,
        defaults={
            "kind": AiProcessingTask.Kind.RESUME_SCORE,
            "requested_by": locked_user,
            "job": standard.job,
            "resume": structured_resume.resume,
            "standard": standard,
            **_snapshot_defaults(snapshot),
        },
    )


@transaction.atomic
def enqueue_resume_report(*, assessment, requested_by, request_id=None) -> tuple[AiProcessingTask, bool]:
    locked_user, snapshot = _lock_user_and_capture_snapshot(requested_by)
    request_id = request_id or uuid.uuid4()
    key = f"resume-report:{request_id}:{assessment.pk}"
    return AiProcessingTask.objects.get_or_create(
        idempotency_key=key,
        defaults={
            "kind": AiProcessingTask.Kind.RESUME_REPORT,
            "requested_by": locked_user,
            "job": assessment.standard.job,
            "resume": assessment.structured_resume.resume,
            "standard": assessment.standard,
            "assessment": assessment,
            **_snapshot_defaults(snapshot),
        },
    )


@transaction.atomic
def _bind_waiting_tasks_for_user(user_id) -> int:
    locked_user = get_user_model().objects.select_for_update().get(pk=user_id)
    snapshot = _capture_current_snapshot_locked(locked_user)
    if not snapshot:
        return 0
    now = timezone.now()
    return AiProcessingTask.objects.filter(
        requested_by_id=locked_user.pk,
        status=AiProcessingTask.Status.WAITING_CONFIG,
        model_snapshot_bound_at__isnull=True,
    ).update(
        status=AiProcessingTask.Status.PENDING,
        available_at=now,
        error_code="",
        error_message="",
        model_api_url_snapshot=snapshot.api_url,
        model_name_snapshot=snapshot.model,
        encrypted_model_api_key_snapshot=snapshot.encrypted_api_key,
        model_snapshot_fingerprint=snapshot.fingerprint,
        model_snapshot_bound_at=now,
        updated_at=now,
    )


def _restore_configured_tasks():
    now = timezone.now()
    AiProcessingTask.objects.filter(
        status__in=[
            AiProcessingTask.Status.PENDING,
            AiProcessingTask.Status.EXTRACTING,
            AiProcessingTask.Status.OCR,
            AiProcessingTask.Status.MODEL,
        ],
        model_snapshot_bound_at__isnull=True,
    ).update(
        status=AiProcessingTask.Status.WAITING_CONFIG,
        leased_at=None,
        lease_expires_at=None,
        lease_token=None,
        error_code="model_not_configured",
        error_message="等待该任务首次绑定可用的大模型配置",
        updated_at=now,
    )
    AiProcessingTask.objects.filter(
        status=AiProcessingTask.Status.WAITING_CONFIG,
        model_snapshot_bound_at__isnull=False,
    ).update(status=AiProcessingTask.Status.PENDING, available_at=now, updated_at=now)
    user_ids = list(
        AiProcessingTask.objects.filter(
            status=AiProcessingTask.Status.WAITING_CONFIG,
            model_snapshot_bound_at__isnull=True,
        )
        .order_by()
        .values_list("requested_by_id", flat=True)
        .distinct()
    )
    for user_id in user_ids:
        _bind_waiting_tasks_for_user(user_id)


def _bind_task_snapshot_once(task: AiProcessingTask) -> AiProcessingTask:
    current = AiProcessingTask.objects.select_related("requested_by").get(pk=task.pk)
    if current.model_snapshot_bound_at is not None:
        return current
    with transaction.atomic():
        locked_user = get_user_model().objects.select_for_update().get(pk=current.requested_by_id)
        locked = AiProcessingTask.objects.select_for_update().select_related("requested_by").get(pk=current.pk)
        if locked.model_snapshot_bound_at is not None:
            return locked
        snapshot = _capture_current_snapshot_locked(locked_user)
        if not snapshot:
            return locked
        _apply_snapshot(locked, snapshot)
        if locked.status == AiProcessingTask.Status.WAITING_CONFIG:
            locked.status = AiProcessingTask.Status.PENDING
            locked.available_at = timezone.now()
        locked.error_code = ""
        locked.error_message = ""
        locked.save()
        return locked


@transaction.atomic
def _lease_pending_task(*, lease_seconds=180) -> AiProcessingTask | None:
    now = timezone.now()
    queryset = AiProcessingTask.objects.filter(
        status=AiProcessingTask.Status.PENDING,
        available_at__lte=now,
        model_snapshot_bound_at__isnull=False,
    ).order_by("available_at", "created_at")
    if connection.features.has_select_for_update_skip_locked:
        queryset = queryset.select_for_update(skip_locked=True)
    else:
        queryset = queryset.select_for_update()
    task = queryset.first()
    if not task:
        return None
    task.status = AiProcessingTask.Status.MODEL
    task.leased_at = now
    task.lease_expires_at = now + timedelta(seconds=lease_seconds)
    task.lease_token = uuid.uuid4()
    task.save(update_fields=["status", "leased_at", "lease_expires_at", "lease_token", "updated_at"])
    return task


def lease_next_task(*, lease_seconds=180) -> AiProcessingTask | None:
    now = timezone.now()
    AiProcessingTask.objects.filter(
        status__in=[AiProcessingTask.Status.EXTRACTING, AiProcessingTask.Status.OCR, AiProcessingTask.Status.MODEL],
        lease_expires_at__lt=now,
    ).update(
        status=AiProcessingTask.Status.PENDING,
        leased_at=None,
        lease_expires_at=None,
        lease_token=None,
        error_code="lease_expired",
        error_message="任务租约过期，已自动恢复",
        available_at=now,
    )
    _restore_configured_tasks()
    return _lease_pending_task(lease_seconds=lease_seconds)


def _execute_job_standard(task):
    from recruitment.services.job_standards import process_job_standard_task

    return process_job_standard_task(task)


def _execute_resume_structure(task):
    from recruitment.services.resume_intelligence import process_resume_structure_task

    return process_resume_structure_task(task)


def _execute_resume_score(task):
    from recruitment.services.resume_intelligence import process_resume_score_task

    return process_resume_score_task(task)


def _execute_resume_report(task):
    from recruitment.services.resume_intelligence import process_resume_report_task

    return process_resume_report_task(task)


TASK_EXECUTORS = {
    AiProcessingTask.Kind.JOB_STANDARD: _execute_job_standard,
    AiProcessingTask.Kind.RESUME_STRUCTURE: _execute_resume_structure,
    AiProcessingTask.Kind.RESUME_SCORE: _execute_resume_score,
    AiProcessingTask.Kind.RESUME_REPORT: _execute_resume_report,
}


def _clear_lease(task):
    task.leased_at = None
    task.lease_expires_at = None
    task.lease_token = None


def _run_with_heartbeat(task):
    token = task.lease_token
    stopped = threading.Event()

    def heartbeat():
        while not stopped.wait(45):
            updated = AiProcessingTask.objects.filter(
                pk=task.pk, lease_token=token,
                status__in=[AiProcessingTask.Status.EXTRACTING, AiProcessingTask.Status.OCR, AiProcessingTask.Status.MODEL],
            ).update(lease_expires_at=timezone.now() + timedelta(seconds=LEASE_SECONDS))
            if not updated:
                return

    thread = threading.Thread(target=heartbeat, name=f"ai-task-heartbeat-{task.pk}", daemon=True)
    thread.start()
    try:
        result = TASK_EXECUTORS[task.kind](task) or {}
    finally:
        stopped.set()
        thread.join(timeout=2)
    if not AiProcessingTask.objects.filter(pk=task.pk, lease_token=token).exists():
        raise RuntimeError("AI 任务租约已转移，当前执行结果已丢弃")
    task.refresh_from_db()
    return result


def _notify_linked_search_campaigns(task):
    from recruitment.services.search_campaign_intelligence import notify_search_campaigns_for_ai_task

    transaction.on_commit(lambda: notify_search_campaigns_for_ai_task(task))
    return task


def execute_task(task: AiProcessingTask) -> AiProcessingTask:
    task = _bind_task_snapshot_once(task)
    if task.model_snapshot_bound_at is None:
        task.status = AiProcessingTask.Status.WAITING_CONFIG
        task.error_code = "model_not_configured"
        task.error_message = "等待该任务首次绑定可用的大模型配置"
        _clear_lease(task)
        task.save()
        return _notify_linked_search_campaigns(task)
    try:
        task_model_credential(task)
    except ModelGatewayError as exc:
        task.status = AiProcessingTask.Status.FAILED
        task.error_code = exc.code
        task.error_message = str(exc)[:500]
        _clear_lease(task)
        task.save()
        return _notify_linked_search_campaigns(task)
    task.status = AiProcessingTask.Status.MODEL
    task.attempt_count += 1
    task.progress = max(task.progress, 40)
    task.error_code = ""
    task.error_message = ""
    if not task.lease_expires_at:
        task.leased_at = timezone.now()
        task.lease_expires_at = task.leased_at + timedelta(seconds=LEASE_SECONDS)
    if not task.lease_token:
        task.lease_token = uuid.uuid4()
    task.save()
    try:
        result = _run_with_heartbeat(task)
    except ModelGatewayError as exc:
        task.error_code = exc.code
        task.error_message = str(exc)[:500]
        _clear_lease(task)
        if exc.retryable and task.attempt_count < task.max_attempts:
            delay = RETRY_DELAYS[min(task.attempt_count - 1, len(RETRY_DELAYS) - 1)]
            task.status = AiProcessingTask.Status.PENDING
            task.available_at = timezone.now() + timedelta(seconds=delay)
        else:
            task.status = AiProcessingTask.Status.FAILED
        task.save()
        return _notify_linked_search_campaigns(task)
    except ExtractionError as exc:
        task.status = AiProcessingTask.Status.FAILED
        task.error_code = exc.code
        task.error_message = str(exc)[:500]
        _clear_lease(task)
        task.save()
        return _notify_linked_search_campaigns(task)
    except Exception:
        task.status = AiProcessingTask.Status.FAILED
        task.error_code = "ai_task_failed"
        task.error_message = "AI 任务执行失败，请查看服务端日志后重试"
        _clear_lease(task)
        task.save()
        return _notify_linked_search_campaigns(task)
    requested_status = result.pop("_task_status", AiProcessingTask.Status.SUCCEEDED)
    task.status = requested_status
    task.progress = 100
    task.result_ref = result
    task.error_code = ""
    task.error_message = ""
    _clear_lease(task)
    task.save()
    return _notify_linked_search_campaigns(task)


def retry_task(*, task, requested_by) -> AiProcessingTask:
    owner_id = AiProcessingTask.objects.values_list("requested_by_id", flat=True).get(pk=task.pk)
    with transaction.atomic():
        locked_owner = get_user_model().objects.select_for_update().get(pk=owner_id)
        locked = AiProcessingTask.objects.select_for_update().get(pk=task.pk)
        if locked.requested_by_id != requested_by.id and not requested_by.is_superuser:
            raise PermissionError("无权重试该 AI 任务")
        if locked.status not in {AiProcessingTask.Status.FAILED, AiProcessingTask.Status.WAITING_CONFIG}:
            raise ValueError("只有失败或等待模型配置的任务可以重试")
        if locked.model_snapshot_bound_at is None:
            snapshot = _capture_current_snapshot_locked(locked_owner)
            if snapshot:
                _apply_snapshot(locked, snapshot)
        locked.status = (
            AiProcessingTask.Status.PENDING
            if locked.model_snapshot_bound_at is not None
            else AiProcessingTask.Status.WAITING_CONFIG
        )
        locked.progress = 0
        locked.attempt_count = 0
        locked.available_at = timezone.now()
        locked.error_code = ""
        locked.error_message = ""
        _clear_lease(locked)
        locked.save()
        return _notify_linked_search_campaigns(locked)
