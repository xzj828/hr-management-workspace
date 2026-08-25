import json

from django.db import transaction
from django.db.models import Max

from accounts.models import UserModelCredential
from accounts.services.model_gateway import ModelGatewayError, OpenAICompatibleGateway
from recruitment.models import (
    AiProcessingTask,
    FileTextExtraction,
    RecruitmentAuditLog,
    StructuredResumeVersion,
)
from recruitment.services.file_extraction import ExtractionError, extract_file


SENSITIVE_FIELDS = {"age", "birth_date", "ethnicity", "gender", "marital_status", "pregnancy", "sex"}
STRUCTURED_LIST_FIELDS = (
    "work_experiences",
    "project_experiences",
    "educations",
    "skills",
    "certificates",
    "languages",
    "achievements",
    "unknown_fields",
)


def _referenced_evidence_ids(value):
    if isinstance(value, dict):
        for key, item in value.items():
            if key in {"evidence_block_ids", "block_ids"}:
                for block_id in item or []:
                    yield str(block_id)
            else:
                yield from _referenced_evidence_ids(item)
    elif isinstance(value, list):
        for item in value:
            yield from _referenced_evidence_ids(item)


def validate_structured_payload(payload: dict, *, extraction: FileTextExtraction) -> dict:
    if not isinstance(payload, dict) or not isinstance(payload.get("data"), dict):
        raise ModelGatewayError("model_invalid_response", "模型返回的结构化简历格式无效")
    incoming = payload["data"]
    basics = incoming.get("basics") or {}
    if not isinstance(basics, dict):
        raise ModelGatewayError("model_invalid_response", "简历基础信息格式无效")
    warnings = payload.get("warnings") or []
    if not isinstance(warnings, list):
        raise ModelGatewayError("model_invalid_response", "简历警告信息格式无效")
    removed = sorted(set(basics) & SENSITIVE_FIELDS)
    for field in removed:
        basics.pop(field, None)
    if removed:
        warnings.append("已移除不参与招聘评分的敏感人口属性")
    normalized_basics = {
        key: basics.get(key)
        for key in ("name", "phone", "email", "city", "target_role")
    }
    data = {
        "basics": normalized_basics,
        "summary": incoming.get("summary"),
        "work_experiences": incoming.get("work_experiences") or [],
        "project_experiences": incoming.get("project_experiences") or [],
        "educations": incoming.get("educations") or [],
        "skills": incoming.get("skills") or [],
        "certificates": incoming.get("certificates") or [],
        "languages": incoming.get("languages") or [],
        "total_experience_months": incoming.get("total_experience_months"),
        "achievements": incoming.get("achievements") or [],
        "unknown_fields": incoming.get("unknown_fields") or [],
    }
    for field in STRUCTURED_LIST_FIELDS:
        if not isinstance(data[field], list):
            raise ModelGatewayError("model_invalid_response", f"结构化简历字段 {field} 必须是列表")
    evidence = payload.get("evidence") or []
    if not isinstance(evidence, list):
        raise ModelGatewayError("model_invalid_response", "简历证据格式无效")
    allowed = {str(block.get("id")) for block in extraction.blocks if block.get("id")}
    unknown = sorted(set(_referenced_evidence_ids({"data": data, "evidence": evidence})) - allowed)
    if unknown:
        raise ValueError(f"结构化简历引用了不存在的原文证据：{unknown[0]}")
    return {
        "data": data,
        "evidence": evidence,
        "warnings": [str(item).strip() for item in warnings if str(item).strip()],
    }


def build_resume_structure_prompt(extraction):
    system = (
        "你是简历结构化助手。只能依据原文块生成 JSON，不得推断缺失经历。"
        "无法确认的字段必须为 null 或加入 unknown_fields；不要输出性别、年龄、民族、婚育信息。"
    )
    schema = {
        "data": {
            "basics": {"name": None, "phone": None, "email": None, "city": None, "target_role": None},
            "summary": None,
            "work_experiences": [],
            "project_experiences": [],
            "educations": [],
            "skills": [],
            "certificates": [],
            "languages": [],
            "total_experience_months": None,
            "achievements": [],
            "unknown_fields": [],
        },
        "evidence": [],
        "warnings": [],
    }
    return system, json.dumps({"output_schema": schema, "resume_blocks": extraction.blocks}, ensure_ascii=False)


@transaction.atomic
def create_structured_resume(*, resume, extraction, gateway) -> StructuredResumeVersion:
    system, user = build_resume_structure_prompt(extraction)
    normalized = validate_structured_payload(gateway.complete_json(system=system, user=user).data, extraction=extraction)
    latest = StructuredResumeVersion.objects.filter(resume=resume).order_by("-version").first()
    model_name = gateway.credential.model
    if (
        latest
        and latest.extraction_id == extraction.pk
        and latest.model_name == model_name
        and latest.data == normalized["data"]
        and latest.evidence == normalized["evidence"]
        and latest.warnings == normalized["warnings"]
    ):
        return latest
    next_version = (StructuredResumeVersion.objects.filter(resume=resume).aggregate(value=Max("version"))["value"] or 0) + 1
    structured = StructuredResumeVersion.objects.create(
        resume=resume,
        version=next_version,
        extraction=extraction,
        data=normalized["data"],
        evidence=normalized["evidence"],
        warnings=normalized["warnings"],
        model_name=model_name,
    )
    RecruitmentAuditLog.objects.create(
        actor=None,
        boss_account=resume.application.job.boss_account if resume.application_id else None,
        action="resume_structured",
        target_id=str(structured.pk),
        detail={"resume_id": resume.pk, "version": structured.version, "model": model_name},
    )
    return structured


def _extract_resume(resume):
    extraction, _ = FileTextExtraction.objects.get_or_create(
        source_kind=FileTextExtraction.SourceKind.RESUME,
        source_id=resume.pk,
        source_sha256=resume.sha256,
        defaults={"method": FileTextExtraction.Method.PDF_TEXT},
    )
    if extraction.status == FileTextExtraction.Status.READY:
        return extraction
    try:
        result = extract_file(resume.file.path, content_type=resume.content_type)
    except ExtractionError as exc:
        extraction.status = FileTextExtraction.Status.FAILED
        extraction.error_code = exc.code
        extraction.error_message = str(exc)
        extraction.save()
        raise
    extraction.method = result.method
    extraction.plain_text = result.plain_text
    extraction.blocks = [{**block, "id": f"resume-{resume.pk}-{block['id']}"} for block in result.blocks]
    extraction.status = FileTextExtraction.Status.READY
    extraction.error_code = ""
    extraction.error_message = ""
    extraction.save()
    return extraction


def process_resume_structure_task(task: AiProcessingTask):
    if not task.resume_id:
        raise ExtractionError("resume_missing", "结构化任务没有关联简历")
    extraction = _extract_resume(task.resume)
    credential = UserModelCredential.objects.get(user=task.requested_by)
    structured = create_structured_resume(
        resume=task.resume,
        extraction=extraction,
        gateway=OpenAICompatibleGateway(credential),
    )
    return {"structured_resume_id": structured.pk}


def process_resume_score_task(task: AiProcessingTask):
    raise ModelGatewayError("scoring_not_ready", "简历评分服务尚未启用")
