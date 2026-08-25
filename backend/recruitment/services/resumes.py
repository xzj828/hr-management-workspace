import hashlib
from pathlib import Path

from django.core.files.base import ContentFile
from django.db import transaction
from django.db.models import Max
from django.utils import timezone

from recruitment.models import RecruitmentAuditLog, Resume
from recruitment.services.stages import advance_for_event


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
    return resume, True


@transaction.atomic
def archive_online_resume_image(*, application, filename, content, external_id="", actor=None):
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
    resume.file.save(safe_name, ContentFile(data), save=False)
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
    return resume, True

