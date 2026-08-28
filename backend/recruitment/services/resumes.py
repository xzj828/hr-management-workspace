import hashlib
from pathlib import Path

from django.core.files.base import ContentFile
from django.db import transaction
from django.db.models import Max
from django.utils import timezone

from recruitment.models import AiProcessingTask, RecruitmentAuditLog, Resume
from recruitment.services.stages import advance_for_event


class ResumePurgeConflict(Exception):
    """The resume cannot be purged while file processing is in flight."""


class ResumePurgeStorageError(Exception):
    """The stored resume file could not be removed safely."""


@transaction.atomic
def purge_resume_file(*, resume, actor):
    locked = (
        Resume.objects.select_for_update()
        .select_related("application__job__boss_account")
        .get(pk=resume.pk)
    )
    if locked.archived_at is not None and not locked.file:
        return 0

    tasks = locked.ai_tasks.select_for_update()
    in_flight_statuses = [
        AiProcessingTask.Status.EXTRACTING,
        AiProcessingTask.Status.OCR,
        AiProcessingTask.Status.MODEL,
    ]
    if tasks.filter(status__in=in_flight_statuses).exists():
        raise ResumePurgeConflict("简历正在处理中，请等待当前 AI 任务结束后再删除")

    now = timezone.now()
    tasks.filter(
        status__in=[AiProcessingTask.Status.WAITING_CONFIG, AiProcessingTask.Status.PENDING]
    ).update(
        status=AiProcessingTask.Status.FAILED,
        error_code="source_file_deleted",
        error_message="原始简历已由 HR 删除，任务已终止",
        leased_at=None,
        lease_expires_at=None,
        lease_token=None,
        updated_at=now,
    )

    released_bytes = locked.file_size if locked.file else 0
    if locked.file:
        storage = locked.file.storage
        stored_name = locked.file.name
        try:
            storage.delete(stored_name)
            if storage.exists(stored_name):
                raise OSError("stored file still exists")
        except Exception as exc:
            raise ResumePurgeStorageError("简历原文件删除失败，请检查本地存储后重试") from exc

    locked.file = ""
    locked.file_size = 0
    locked.processing_status = Resume.ProcessingStatus.ERROR
    locked.archived_at = now
    locked.save(update_fields=["file", "file_size", "processing_status", "archived_at", "updated_at"])
    RecruitmentAuditLog.objects.create(
        actor=actor,
        boss_account=locked.application.job.boss_account if locked.application_id else None,
        action="resume_file_purged",
        target_id=str(locked.pk),
        detail={
            "candidate_id": locked.candidate_id,
            "version": locked.version,
            "released_bytes": released_bytes,
        },
    )
    return released_bytes


@transaction.atomic
def archive_pdf(*, application, filename, content, source=Resume.Source.BOSS, external_id="", actor=None):
    data = bytes(content or b"")
    if not data.startswith(b"%PDF-") or len(data) > 25 * 1024 * 1024:
        raise ValueError("简历必须是有效且不超过 25MB 的 PDF 文件")
    digest = hashlib.sha256(data).hexdigest()
    existing = Resume.objects.filter(candidate=application.candidate, sha256=digest).first()
    if existing:
        return existing, False
    version = (Resume.objects.filter(candidate=application.candidate).aggregate(value=Max("version"))["value"] or 0) + 1
    safe_name = Path(str(filename or "resume.pdf")).name[:255]
    if not safe_name.lower().endswith(".pdf"):
        safe_name = f"{safe_name}.pdf"
    resume = Resume(
        candidate=application.candidate,
        application=application,
        original_name=safe_name,
        content_type="application/pdf",
        file_size=len(data),
        source=source,
        processing_status=Resume.ProcessingStatus.READY,
        sha256=digest,
        version=version,
        external_id=str(external_id or "")[:160],
        acquired_at=timezone.now(),
    )
    resume.file.save(safe_name, ContentFile(data), save=False)
    resume.save()
    advance_for_event(application=application, event="resume_archived", actor=actor)
    RecruitmentAuditLog.objects.create(
        actor=actor,
        boss_account=application.job.boss_account,
        action="resume_archived",
        target_id=str(resume.pk),
        detail={"candidate_id": application.candidate_id, "version": version, "sha256": digest[:12]},
    )
    from recruitment.services.workflow_events import publish_workflow_event

    transaction.on_commit(
        lambda: publish_workflow_event(
            event="resume.archived",
            application=application,
            event_key=f"resume:{resume.pk}",
            payload={"resume_id": resume.pk},
        )
    )
    from recruitment.services.ai_tasks import enqueue_resume_structure

    requested_by = actor or application.job.owner or application.job.boss_account.authorized_users.order_by("id").first()
    if requested_by:
        transaction.on_commit(lambda: enqueue_resume_structure(resume=resume, requested_by=requested_by))
    return resume, True


@transaction.atomic
def archive_online_resume_image(
    *, application, filename, content, external_id="", actor=None, enqueue_intelligence=True
):
    data = bytes(content or b"")
    if not data.startswith(b"\x89PNG\r\n\x1a\n") or len(data) > 25 * 1024 * 1024:
        raise ValueError("在线简历必须是有效且不超过 25MB 的 PNG 文件")
    digest = hashlib.sha256(data).hexdigest()
    existing = Resume.objects.filter(candidate=application.candidate, sha256=digest).first()
    if existing:
        return existing, False
    version = (Resume.objects.filter(candidate=application.candidate).aggregate(value=Max("version"))["value"] or 0) + 1
    safe_name = Path(str(filename or "online-resume.png")).name[:255]
    if not safe_name.lower().endswith(".png"):
        safe_name = f"{safe_name}.png"
    resume = Resume(
        candidate=application.candidate,
        application=application,
        original_name=safe_name,
        content_type="image/png",
        file_size=len(data),
        source=Resume.Source.BOSS_ONLINE,
        processing_status=Resume.ProcessingStatus.READY,
        sha256=digest,
        version=version,
        external_id=str(external_id or "")[:160],
        acquired_at=timezone.now(),
    )
    storage = resume.file.storage
    stored_name = ""
    try:
        resume.file.save(safe_name, ContentFile(data), save=False)
        stored_name = resume.file.name
        resume.save()
        advance_for_event(application=application, event="resume_archived", actor=actor)
        RecruitmentAuditLog.objects.create(
            actor=actor,
            boss_account=application.job.boss_account,
            action="online_resume_archived",
            target_id=str(resume.pk),
            detail={"candidate_id": application.candidate_id, "version": version, "sha256": digest[:12]},
        )
        from recruitment.services.workflow_events import publish_workflow_event
        transaction.on_commit(
            lambda: publish_workflow_event(
                event="resume.archived", application=application,
                event_key=f"resume:{resume.pk}", payload={"resume_id": resume.pk},
            )
        )
        from recruitment.services.ai_tasks import enqueue_resume_structure

        requested_by = actor or application.job.owner or application.job.boss_account.authorized_users.order_by("id").first()
        if requested_by and enqueue_intelligence:
            transaction.on_commit(lambda: enqueue_resume_structure(resume=resume, requested_by=requested_by))
        return resume, True
    except Exception:
        # FileField writes storage before the surrounding database transaction commits.
        # Compensate if any later database or workflow bookkeeping step fails.
        if stored_name:
            try:
                storage.delete(stored_name)
            except OSError:
                pass
        raise

