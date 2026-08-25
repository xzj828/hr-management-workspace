from datetime import timedelta

from django.db import connection, transaction
from django.utils import timezone

from accounts.models import UserModelCredential
from accounts.services.model_gateway import ModelGatewayError
from recruitment.models import AiProcessingTask, JobRequirementDocument
from recruitment.services.file_extraction import ExtractionError


RETRY_DELAYS = (30, 120, 300)


def _has_model_configuration(user) -> bool:
    credential = UserModelCredential.objects.filter(user=user).first()
    return bool(
        credential
        and str(credential.api_url or "").strip()
        and str(credential.model or "").strip()
        and credential.encrypted_api_key
    )


def _initial_status(user):
    return AiProcessingTask.Status.PENDING if _has_model_configuration(user) else AiProcessingTask.Status.WAITING_CONFIG


def _current_document_versions(job):
    return list(
        JobRequirementDocument.objects.filter(job=job, archived_at__isnull=True, current_version__isnull=False)
        .select_related("current_version")
        .order_by("id")
        .values_list("current_version_id", "current_version__sha256")
    )


def enqueue_job_standard(*, job, requested_by) -> tuple[AiProcessingTask, bool]:
    versions = _current_document_versions(job)
    if not versions:
        raise ValueError("该职位没有可解析的岗位 Word 文档")
    fingerprint = ":".join(sha[:12] for _, sha in versions)
    key = f"job-standard:{job.pk}:{fingerprint}"
    return AiProcessingTask.objects.get_or_create(
        idempotency_key=key,
        defaults={
            "kind": AiProcessingTask.Kind.JOB_STANDARD,
            "status": _initial_status(requested_by),
            "requested_by": requested_by,
            "job": job,
            "document_version_id": versions[-1][0],
        },
    )


def enqueue_resume_structure(*, resume, requested_by) -> tuple[AiProcessingTask, bool]:
    key = f"resume-structure:{resume.pk}:{resume.sha256 or resume.version}"
    return AiProcessingTask.objects.get_or_create(
        idempotency_key=key,
        defaults={
            "kind": AiProcessingTask.Kind.RESUME_STRUCTURE,
            "status": _initial_status(requested_by),
            "requested_by": requested_by,
            "job": resume.application.job if resume.application_id else None,
            "resume": resume,
        },
    )


def enqueue_resume_score(*, structured_resume, standard, requested_by) -> tuple[AiProcessingTask, bool]:
    key = f"resume-score:{structured_resume.pk}:{standard.pk}"
    return AiProcessingTask.objects.get_or_create(
        idempotency_key=key,
        defaults={
            "kind": AiProcessingTask.Kind.RESUME_SCORE,
            "status": _initial_status(requested_by),
            "requested_by": requested_by,
            "job": standard.job,
            "resume": structured_resume.resume,
            "standard": standard,
        },
    )


def _restore_configured_tasks():
    waiting = AiProcessingTask.objects.filter(status=AiProcessingTask.Status.WAITING_CONFIG).select_related("requested_by")
    ready_ids = [task.pk for task in waiting if _has_model_configuration(task.requested_by)]
    if ready_ids:
        AiProcessingTask.objects.filter(pk__in=ready_ids).update(status=AiProcessingTask.Status.PENDING, available_at=timezone.now())


@transaction.atomic
def lease_next_task(*, lease_seconds=180) -> AiProcessingTask | None:
    now = timezone.now()
    AiProcessingTask.objects.filter(
        status__in=[AiProcessingTask.Status.EXTRACTING, AiProcessingTask.Status.OCR, AiProcessingTask.Status.MODEL],
        lease_expires_at__lt=now,
    ).update(
        status=AiProcessingTask.Status.PENDING,
        leased_at=None,
        lease_expires_at=None,
        error_code="lease_expired",
        error_message="任务租约过期，已自动恢复",
        available_at=now,
    )
    _restore_configured_tasks()
    queryset = AiProcessingTask.objects.filter(
        status=AiProcessingTask.Status.PENDING,
        available_at__lte=now,
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
    task.save(update_fields=["status", "leased_at", "lease_expires_at", "updated_at"])
    return task


def _execute_job_standard(task):
    from recruitment.services.job_standards import process_job_standard_task

    return process_job_standard_task(task)


def _execute_resume_structure(task):
    from recruitment.services.resume_intelligence import process_resume_structure_task

    return process_resume_structure_task(task)


def _execute_resume_score(task):
    from recruitment.services.resume_intelligence import process_resume_score_task

    return process_resume_score_task(task)


TASK_EXECUTORS = {
    AiProcessingTask.Kind.JOB_STANDARD: _execute_job_standard,
    AiProcessingTask.Kind.RESUME_STRUCTURE: _execute_resume_structure,
    AiProcessingTask.Kind.RESUME_SCORE: _execute_resume_score,
}


def _clear_lease(task):
    task.leased_at = None
    task.lease_expires_at = None


def execute_task(task: AiProcessingTask) -> AiProcessingTask:
    task.refresh_from_db()
    if not _has_model_configuration(task.requested_by):
        task.status = AiProcessingTask.Status.WAITING_CONFIG
        task.error_code = "model_not_configured"
        task.error_message = "等待当前账号配置可用的大模型"
        _clear_lease(task)
        task.save()
        return task
    task.status = AiProcessingTask.Status.MODEL
    task.attempt_count += 1
    task.progress = max(task.progress, 40)
    task.error_code = ""
    task.error_message = ""
    if not task.lease_expires_at:
        task.leased_at = timezone.now()
        task.lease_expires_at = task.leased_at + timedelta(seconds=180)
    task.save()
    try:
        result = TASK_EXECUTORS[task.kind](task) or {}
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
        return task
    except ExtractionError as exc:
        task.status = AiProcessingTask.Status.FAILED
        task.error_code = exc.code
        task.error_message = str(exc)[:500]
        _clear_lease(task)
        task.save()
        return task
    except Exception:
        task.status = AiProcessingTask.Status.FAILED
        task.error_code = "ai_task_failed"
        task.error_message = "AI 任务执行失败，请查看服务端日志后重试"
        _clear_lease(task)
        task.save()
        return task
    requested_status = result.pop("_task_status", AiProcessingTask.Status.SUCCEEDED)
    task.status = requested_status
    task.progress = 100
    task.result_ref = result
    task.error_code = ""
    task.error_message = ""
    _clear_lease(task)
    task.save()
    return task


@transaction.atomic
def retry_task(*, task, requested_by) -> AiProcessingTask:
    locked = AiProcessingTask.objects.select_for_update().get(pk=task.pk)
    if locked.requested_by_id != requested_by.id and not requested_by.is_superuser:
        raise PermissionError("无权重试该 AI 任务")
    if locked.status not in {AiProcessingTask.Status.FAILED, AiProcessingTask.Status.WAITING_CONFIG}:
        raise ValueError("只有失败或等待模型配置的任务可以重试")
    locked.status = _initial_status(requested_by)
    locked.progress = 0
    locked.attempt_count = 0
    locked.available_at = timezone.now()
    locked.error_code = ""
    locked.error_message = ""
    _clear_lease(locked)
    locked.save()
    return locked
