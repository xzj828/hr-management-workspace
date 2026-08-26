from dataclasses import dataclass

from django.db import transaction

from recruitment.models import RecruitmentJob


@dataclass(frozen=True)
class SyncSummary:
    created: int
    updated: int
    unchanged: int
    total: int


@transaction.atomic
def sync_positions(*, account, owner, rows):
    created_count = 0
    updated_count = 0
    unchanged_count = 0
    valid_statuses = set(RecruitmentJob.Status.values)

    for row in rows:
        external_id = str(row.get("external_id", "")).strip()
        title = str(row.get("title", "")).strip()
        job_status = row.get("status")
        if not external_id or not title:
            raise ValueError("职位编号和名称不能为空")
        if job_status not in valid_statuses:
            raise ValueError("职位状态无效")

        job = RecruitmentJob.objects.filter(
            boss_account=account,
            external_id=external_id,
        ).first()
        if job is None:
            RecruitmentJob.objects.create(
                boss_account=account,
                external_id=external_id,
                title=title,
                status=job_status,
                owner=owner,
            )
            created_count += 1
            continue
        previous = {"title": job.title, "status": job.status}
        if job.status != job_status:
            from recruitment.services.lifecycle import change_job_status

            job = change_job_status(job=job, to_status=job_status, actor=owner)
        if job.title != title:
            job.title = title
            job.save(update_fields=["title", "updated_at"])
        if previous == {"title": title, "status": job_status}:
            unchanged_count += 1
        else:
            updated_count += 1

    total = created_count + updated_count + unchanged_count
    return SyncSummary(created_count, updated_count, unchanged_count, total)
