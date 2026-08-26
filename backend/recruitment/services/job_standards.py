import json
import re
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.db.models import Max
from django.utils import timezone

from accounts.services.model_gateway import ModelGatewayError, OpenAICompatibleGateway
from recruitment.models import (
    AiProcessingTask,
    FileTextExtraction,
    JobRequirementDocument,
    JobStandardVersion,
    RecruitmentJob,
    RecruitmentAuditLog,
)
from recruitment.services.file_extraction import ExtractionError, extract_file
from recruitment.services.ai_tasks import task_model_credential


SENSITIVE_CRITERIA_KEYS = {"age", "ethnicity", "gender", "marital_status", "pregnancy", "sex"}
SENSITIVE_CRITERIA_TERMS = ("性别", "年龄", "民族", "婚育", "婚姻", "怀孕", "生育")


def _contains_sensitive_criterion(*values) -> bool:
    text = " ".join(str(value or "") for value in values).lower()
    return any(term in text for term in SENSITIVE_CRITERIA_TERMS) or bool(
        re.search(r"\b(age|gender|sex|ethnicity|marital|pregnan(?:t|cy))\b", text)
    )


def _evidence_ids(criteria):
    for group in ("dimensions", "hard_requirements", "required", "preferred", "risks"):
        for item in criteria.get(group, []) or []:
            for block_id in item.get("evidence_block_ids", []) or []:
                yield str(block_id)


def validate_criteria(criteria: dict, *, allowed_evidence_ids: set[str], require_publishable: bool) -> dict:
    if not isinstance(criteria, dict):
        raise ValueError("评分标准必须是 JSON 对象")
    auto_reject = criteria.get("auto_reject_on_hard_fail", False)
    if not isinstance(auto_reject, bool):
        raise ValueError("确定性硬性条件核验开关必须是布尔值")
    normalized = {
        "summary": str(criteria.get("summary") or "").strip(),
        "dimensions": criteria.get("dimensions") or [],
        "hard_requirements": criteria.get("hard_requirements") or [],
        "auto_reject_on_hard_fail": auto_reject,
        "required": criteria.get("required") or [],
        "preferred": criteria.get("preferred") or [],
        "risks": criteria.get("risks") or [],
    }
    if _contains_sensitive_criterion(normalized["summary"]):
        raise ValueError("性别、年龄、民族、婚育等敏感属性不能作为筛选依据")
    for group in ("dimensions", "hard_requirements", "required", "preferred", "risks"):
        if not isinstance(normalized[group], list):
            raise ValueError(f"{group} 必须是列表")
        if any(not isinstance(item, dict) for item in normalized[group]):
            raise ValueError(f"{group} 中每一项必须是对象")
    dimensions = normalized["dimensions"]
    if require_publishable and not dimensions:
        raise ValueError("至少需要一个评分维度")
    seen = set()
    total = Decimal("0")
    for dimension in dimensions:
        key = str(dimension.get("key") or "").strip().lower()
        if not key or key in seen:
            raise ValueError("评分维度标识不能为空或重复")
        if key in SENSITIVE_CRITERIA_KEYS or _contains_sensitive_criterion(
            key, dimension.get("name"), dimension.get("description")
        ):
            raise ValueError("性别、年龄、民族、婚育等敏感属性不能作为评分维度")
        seen.add(key)
        if not str(dimension.get("name") or "").strip() or not str(dimension.get("description") or "").strip():
            raise ValueError("评分维度必须包含名称和判断说明")
        try:
            weight = Decimal(str(dimension.get("weight")))
        except (InvalidOperation, TypeError, ValueError) as exc:
            raise ValueError("评分维度权重必须是数字") from exc
        if weight <= 0 or weight > 100:
            raise ValueError("评分维度权重必须大于 0 且不超过 100")
        dimension["key"] = key
        dimension["weight"] = float(weight) if weight % 1 else int(weight)
        total += weight
    if require_publishable and total != Decimal("100"):
        raise ValueError("评分维度权重合计必须为 100%")
    hard_keys = set()
    for item in normalized["hard_requirements"]:
        key = str(item.get("key") or "").strip().lower()
        if not key or key in hard_keys:
            raise ValueError("硬性指标标识不能为空或重复")
        if key in SENSITIVE_CRITERIA_KEYS or _contains_sensitive_criterion(key, item.get("text")):
            raise ValueError("性别、年龄、民族、婚育等敏感属性不能作为硬性指标")
        if not str(item.get("text") or "").strip():
            raise ValueError("硬性指标必须填写明确要求")
        item["key"] = key
        item["text"] = str(item["text"]).strip()
        rule = item.get("rule")
        if rule is not None:
            if not isinstance(rule, dict):
                raise ValueError("硬性指标自动判定规则必须是对象")
            field = str(rule.get("field") or "").strip()
            operator = str(rule.get("operator") or "").strip()
            supported = {
                "total_experience_months": {"gte", "lte"},
                "highest_degree": {"in", "gte"},
                "skills": {"contains_all"},
                "city": {"in"},
            }
            if field not in supported or operator not in supported[field] or rule.get("value") in (None, "", []):
                raise ValueError("硬性指标自动判定规则不完整或不受支持")
            item["rule"] = {"field": field, "operator": operator, "value": rule["value"]}
        hard_keys.add(key)
    if normalized["auto_reject_on_hard_fail"] and any(not item.get("rule") for item in normalized["hard_requirements"]):
        raise ValueError(
            "启用确定性硬性条件冲突标记前，每个硬性指标都必须配置可确定判定的字段、条件和阈值；"
            "冲突仅供 HR 确认，不改变招聘阶段"
        )
    for group in ("required", "preferred", "risks"):
        for item in normalized[group]:
            if _contains_sensitive_criterion(*item.values()):
                raise ValueError("性别、年龄、民族、婚育等敏感属性不能作为筛选依据")
    unknown = sorted(set(_evidence_ids(normalized)) - set(allowed_evidence_ids))
    if unknown:
        raise ValueError(f"评分标准引用了不存在的原文证据：{unknown[0]}")
    return normalized


def _allowed_evidence_for_versions(document_versions):
    extractions = FileTextExtraction.objects.filter(
        source_kind=FileTextExtraction.SourceKind.JOB_DOCUMENT,
        source_id__in=[version.pk for version in document_versions],
        status=FileTextExtraction.Status.READY,
    )
    return {
        str(block.get("id"))
        for extraction in extractions
        for block in extraction.blocks
        if block.get("id")
    }


def build_standard_prompt(extractions: list[FileTextExtraction]) -> tuple[str, str]:
    blocks = [block for extraction in extractions for block in extraction.blocks]
    system = (
        "你是招聘标准整理助手。只能依据给出的原文证据生成 JSON；不得把性别、年龄、民族、婚育等敏感属性作为标准。"
        "无法确认的信息放入 unresolved_questions，不得补造。"
    )
    user = json.dumps(
        {
            "output_schema": {
                "criteria": {
                    "summary": "string",
                    "dimensions": [{"key": "string", "name": "string", "weight": "number", "description": "string", "evidence_block_ids": ["string"]}],
                    "hard_requirements": [{"key": "string", "text": "string", "evidence_block_ids": ["string"]}],
                    "auto_reject_on_hard_fail": False,
                    "required": [{"text": "string", "evidence_block_ids": ["string"]}],
                    "preferred": [],
                    "risks": [],
                },
                "unresolved_questions": ["string"],
            },
            "document_blocks": blocks,
        },
        ensure_ascii=False,
    )
    return system, user


@transaction.atomic
def create_standard_draft(*, job, document_versions, gateway, actor) -> JobStandardVersion:
    document_versions = list(document_versions)
    extractions = list(
        FileTextExtraction.objects.filter(
            source_kind=FileTextExtraction.SourceKind.JOB_DOCUMENT,
            source_id__in=[version.pk for version in document_versions],
            status=FileTextExtraction.Status.READY,
        ).order_by("source_id")
    )
    if len(extractions) != len(document_versions):
        raise ValueError("岗位文档尚未全部提取完成")
    system, user = build_standard_prompt(extractions)
    payload = gateway.complete_json(system=system, user=user).data
    criteria = validate_criteria(
        payload.get("criteria"),
        allowed_evidence_ids=_allowed_evidence_for_versions(document_versions),
        require_publishable=False,
    )
    questions = payload.get("unresolved_questions") or []
    if not isinstance(questions, list):
        raise ModelGatewayError("model_invalid_response", "模型返回的待确认问题格式无效")
    job = RecruitmentJob.objects.select_for_update().get(pk=job.pk)
    next_version = (JobStandardVersion.objects.filter(job=job).aggregate(value=Max("version"))["value"] or 0) + 1
    standard = JobStandardVersion.objects.create(
        job=job,
        version=next_version,
        criteria=criteria,
        unresolved_questions=[str(item).strip() for item in questions if str(item).strip()],
        model_name=gateway.credential.model,
        created_by=actor,
    )
    standard.source_document_versions.set(document_versions)
    RecruitmentAuditLog.objects.create(
        actor=actor,
        boss_account=job.boss_account,
        action="job_standard_draft_created",
        target_id=str(standard.pk),
        detail={"version": standard.version, "document_version_ids": [item.pk for item in document_versions]},
    )
    return standard


@transaction.atomic
def update_standard_draft(*, standard, criteria, unresolved_questions, actor) -> JobStandardVersion:
    locked = JobStandardVersion.objects.select_for_update().get(pk=standard.pk)
    if locked.status != JobStandardVersion.Status.DRAFT:
        raise ValueError("已启用或历史评分标准不可直接修改")
    allowed = _allowed_evidence_for_versions(locked.source_document_versions.all())
    locked.criteria = validate_criteria(criteria, allowed_evidence_ids=allowed, require_publishable=False)
    if not isinstance(unresolved_questions, list):
        raise ValueError("待确认问题必须是列表")
    locked.unresolved_questions = [str(item).strip() for item in unresolved_questions if str(item).strip()]
    locked.save(update_fields=["criteria", "unresolved_questions", "updated_at"])
    RecruitmentAuditLog.objects.create(
        actor=actor,
        boss_account=locked.job.boss_account,
        action="job_standard_draft_updated",
        target_id=str(locked.pk),
    )
    return locked


@transaction.atomic
def publish_standard(*, standard, actor) -> JobStandardVersion:
    locked = JobStandardVersion.objects.select_for_update().get(pk=standard.pk)
    if locked.status != JobStandardVersion.Status.DRAFT:
        raise ValueError("只有草稿可以确认并启用")
    allowed = _allowed_evidence_for_versions(locked.source_document_versions.all())
    locked.criteria = validate_criteria(locked.criteria, allowed_evidence_ids=allowed, require_publishable=True)
    JobStandardVersion.objects.filter(
        job=locked.job,
        status=JobStandardVersion.Status.PUBLISHED,
    ).update(status=JobStandardVersion.Status.SUPERSEDED, updated_at=timezone.now())
    locked.status = JobStandardVersion.Status.PUBLISHED
    locked.published_by = actor
    locked.published_at = timezone.now()
    locked.save(update_fields=["criteria", "status", "published_by", "published_at", "updated_at"])
    RecruitmentAuditLog.objects.create(
        actor=actor,
        boss_account=locked.job.boss_account,
        action="job_standard_published",
        target_id=str(locked.pk),
        detail={"version": locked.version},
    )
    return locked


def _extract_document_version(version):
    extraction, _ = FileTextExtraction.objects.get_or_create(
        source_kind=FileTextExtraction.SourceKind.JOB_DOCUMENT,
        source_id=version.pk,
        source_sha256=version.sha256,
        defaults={"method": FileTextExtraction.Method.DOCX},
    )
    if extraction.status == FileTextExtraction.Status.READY:
        return extraction
    try:
        result = extract_file(version.file.path, content_type="application/msword")
    except ExtractionError as exc:
        extraction.status = FileTextExtraction.Status.FAILED
        extraction.error_code = exc.code
        extraction.error_message = str(exc)
        extraction.save()
        raise
    prefixed = [
        {**block, "id": f"doc-{version.pk}-{block['id']}"}
        for block in result.blocks
    ]
    extraction.method = result.method
    extraction.plain_text = result.plain_text
    extraction.blocks = prefixed
    extraction.status = FileTextExtraction.Status.READY
    extraction.error_code = ""
    extraction.error_message = ""
    extraction.save()
    return extraction


def process_job_standard_task(task: AiProcessingTask):
    versions = [
        document.current_version
        for document in JobRequirementDocument.objects.filter(
            job=task.job,
            archived_at__isnull=True,
            current_version__isnull=False,
        ).select_related("current_version")
    ]
    if not versions:
        raise ExtractionError("job_documents_missing", "该职位没有可解析的岗位文档")
    for version in versions:
        _extract_document_version(version)
    standard = create_standard_draft(
        job=task.job,
        document_versions=versions,
        gateway=OpenAICompatibleGateway(task_model_credential(task)),
        actor=task.requested_by,
    )
    return {"job_standard_id": standard.pk, "_task_status": AiProcessingTask.Status.WAITING_REVIEW}
