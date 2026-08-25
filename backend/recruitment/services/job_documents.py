import hashlib
from pathlib import Path

from django.db import IntegrityError, transaction

from recruitment.models import JobRequirementDocument, JobRequirementDocumentVersion


MAX_JOB_DOCUMENT_SIZE = 25 * 1024 * 1024
JOB_DOCUMENT_SUFFIXES = {".doc", ".docx", ".xlsx"}


def validate_job_document_file(upload):
    suffix = Path(upload.name or "").suffix.lower()
    if suffix not in JOB_DOCUMENT_SUFFIXES:
        raise ValueError("仅支持 .doc、.docx 或 .xlsx 岗位依据文档")
    if upload.size <= 0 or upload.size > MAX_JOB_DOCUMENT_SIZE:
        raise ValueError("岗位依据文档必须有效且不超过 25MB")


def _sha256(upload):
    digest = hashlib.sha256()
    upload.seek(0)
    for chunk in upload.chunks():
        digest.update(chunk)
    upload.seek(0)
    return digest.hexdigest()


@transaction.atomic
def create_document(*, job, category, title, upload, actor):
    validate_job_document_file(upload)
    document = JobRequirementDocument.objects.create(
        job=job,
        category=category,
        title=title.strip(),
        created_by=actor,
    )
    return create_document_version(document=document, upload=upload, actor=actor)


@transaction.atomic
def create_document_version(*, document, upload, actor):
    validate_job_document_file(upload)
    locked = JobRequirementDocument.objects.select_for_update().get(pk=document.pk)
    next_version = (locked.versions.order_by("-version").values_list("version", flat=True).first() or 0) + 1
    try:
        version = JobRequirementDocumentVersion.objects.create(
            document=locked,
            version=next_version,
            original_name=Path(upload.name).name,
            file=upload,
            file_size=upload.size,
            sha256=_sha256(upload),
            uploaded_by=actor,
        )
    except IntegrityError as exc:
        raise ValueError("该岗位依据文档内容已经存在") from exc
    locked.current_version = version
    locked.save(update_fields=["current_version", "updated_at"])
    from recruitment.services.ai_tasks import enqueue_job_standard

    transaction.on_commit(lambda: enqueue_job_standard(job=locked.job, requested_by=actor))
    return locked


@transaction.atomic
def set_current_version(*, version):
    locked = JobRequirementDocument.objects.select_for_update().get(pk=version.document_id)
    locked.current_version = version
    locked.save(update_fields=["current_version", "updated_at"])
    from recruitment.services.ai_tasks import enqueue_job_standard

    transaction.on_commit(lambda: enqueue_job_standard(job=locked.job, requested_by=version.uploaded_by))
    return locked
