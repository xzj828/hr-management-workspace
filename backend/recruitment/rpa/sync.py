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

        previous = RecruitmentJob.objects.filter(
            boss_account=account, external_id=external_id
        ).values("title", "status").first()
        _, created = RecruitmentJob.objects.update_or_create(
            boss_account=account,
            external_id=external_id,
            defaults={"title": title, "status": job_status},
            create_defaults={"title": title, "status": job_status, "owner": owner},
        )
        if created:
            created_count += 1
        elif previous == {"title": title, "status": job_status}:
            unchanged_count += 1
        else:
            updated_count += 1

    total = created_count + updated_count + unchanged_count
    return SyncSummary(created_count, updated_count, unchanged_count, total)
