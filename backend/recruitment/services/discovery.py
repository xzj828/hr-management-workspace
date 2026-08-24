import hashlib
import json
from dataclasses import dataclass
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from recruitment.models import (
    Candidate,
    CandidateDiscovery,
    CandidateExternalIdentity,
    JobApplication,
)


@dataclass(frozen=True)
class DiscoverySyncResult:
    created: int
    updated: int
    total: int


@dataclass(frozen=True)
class DiscoveryImportResult:
    created_candidates: int
    existing_candidates: int
    created_applications: int
    total: int


def _clean(value, limit):
    return " ".join(str(value or "").split()).strip()[:limit]


def _fingerprint(account_id, row):
    external_id = _clean(row.get("external_id"), 160)
    if external_id:
        identity = ["platform", account_id, external_id]
    else:
        identity = [
            "fingerprint",
            account_id,
            _clean(row.get("display_name"), 100).casefold(),
            _clean(row.get("current_title"), 160).casefold(),
            _clean(row.get("city"), 80).casefold(),
            _clean(row.get("experience"), 160).casefold(),
            _clean(row.get("education"), 160).casefold(),
        ]
    encoded = json.dumps(identity, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@transaction.atomic
def sync_discoveries(*, account, job, source, criteria, rows):
    if job.boss_account_id != account.pk:
        raise ValueError("职位不属于所选 BOSS 账号")
    if source not in CandidateDiscovery.Source.values:
        raise ValueError("候选人发现来源无效")
    if not isinstance(rows, list):
        raise ValueError("候选人发现结果无效")
    created = 0
    updated = 0
    expires_at = timezone.now() + timedelta(days=7)
    safe_criteria = criteria if isinstance(criteria, dict) else {}
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("候选人发现结果无效")
        display_name = _clean(row.get("display_name"), 100)
        if not display_name:
            raise ValueError("候选人缺少展示名称")
        external_id = _clean(row.get("external_id"), 160)
        fingerprint = _fingerprint(account.pk, row)
        quality = (
            CandidateDiscovery.IdentityQuality.PLATFORM
            if external_id
            else CandidateDiscovery.IdentityQuality.FINGERPRINT
        )
        tags = row.get("tags") if isinstance(row.get("tags"), list) else []
        _, was_created = CandidateDiscovery.objects.update_or_create(
            boss_account=account,
            job=job,
            fingerprint=fingerprint,
            defaults={
                "source": source,
                "external_id": external_id,
                "identity_quality": quality,
                "display_name": display_name,
                "current_title": _clean(row.get("current_title"), 160),
                "city": _clean(row.get("city"), 80),
                "experience": _clean(row.get("experience"), 160),
                "education": _clean(row.get("education"), 160),
                "advantage": _clean(row.get("advantage"), 4000),
                "tags": [_clean(item, 80) for item in tags if _clean(item, 80)][:20],
                "criteria": safe_criteria,
                "source_payload": row,
                "contact_hint": _clean(row.get("contact_hint"), 40),
                "expires_at": expires_at,
            },
        )
        created += int(was_created)
        updated += int(not was_created)
    return DiscoverySyncResult(created=created, updated=updated, total=len(rows))


@transaction.atomic
def import_discoveries(*, discoveries, actor):
    ids = [item.pk for item in discoveries]
    locked = list(
        CandidateDiscovery.objects.select_for_update()
        .select_related("boss_account", "job", "imported_candidate")
        .filter(pk__in=ids)
        .order_by("created_at")
    )
    if len(locked) != len(set(ids)):
        raise ValueError("部分候选人发现记录不存在")
    created_candidates = 0
    existing_candidates = 0
    created_applications = 0
    now = timezone.now()
    for discovery in locked:
        identity = CandidateExternalIdentity.objects.select_for_update().filter(
            boss_account=discovery.boss_account,
            fingerprint=discovery.fingerprint,
        ).first()
        candidate = identity.candidate if identity else discovery.imported_candidate
        if candidate is None:
            identity_key = (
                f"boss:{discovery.boss_account_id}:{discovery.external_id}"
                if discovery.external_id
                else f"boss-fp:{discovery.boss_account_id}:{discovery.fingerprint}"
            )
            candidate, was_created = Candidate.objects.get_or_create(
                identity_key=identity_key,
                defaults={
                    "external_id": discovery.external_id,
                    "name": discovery.display_name,
                    "current_title": discovery.current_title,
                    "current_city": discovery.city,
                },
            )
            created_candidates += int(was_created)
            existing_candidates += int(not was_created)
        else:
            existing_candidates += 1
        if identity is None:
            CandidateExternalIdentity.objects.create(
                boss_account=discovery.boss_account,
                candidate=candidate,
                external_id=discovery.external_id,
                fingerprint=discovery.fingerprint,
                identity_quality=discovery.identity_quality,
            )
        _, application_created = JobApplication.objects.get_or_create(
            candidate=candidate,
            job=discovery.job,
            defaults={"source": "boss", "owner": actor, "stage": JobApplication.Stage.NEW},
        )
        created_applications += int(application_created)
        discovery.imported_candidate = candidate
        discovery.imported_at = discovery.imported_at or now
        discovery.save(update_fields=["imported_candidate", "imported_at", "updated_at"])
    return DiscoveryImportResult(
        created_candidates=created_candidates,
        existing_candidates=existing_candidates,
        created_applications=created_applications,
        total=len(locked),
    )
