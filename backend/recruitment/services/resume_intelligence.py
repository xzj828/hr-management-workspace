import json
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.db.models import Max

from accounts.models import UserModelCredential
from accounts.services.model_gateway import ModelGatewayError, OpenAICompatibleGateway
from recruitment.models import (
    AiProcessingTask,
    FileTextExtraction,
    JobStandardVersion,
    RecruitmentAuditLog,
    ResumeAssessment,
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


def validate_assessment_payload(*, payload: dict, standard: JobStandardVersion, structured: StructuredResumeVersion) -> dict:
    if not isinstance(payload, dict) or not isinstance(payload.get("dimension_scores"), list):
        raise ModelGatewayError("model_invalid_response", "模型返回的简历评分格式无效")
    criteria = {str(item.get("key")): item for item in standard.criteria.get("dimensions", [])}
    if not criteria:
        raise ValueError("评分标准没有可用维度")
    allowed_blocks = {str(block.get("id")) for block in structured.extraction.blocks if block.get("id")}
    normalized_scores = []
    seen = set()
    total = Decimal("0")
    allowed_statuses = {"supported", "not_supported", "information_missing"}
    for item in payload["dimension_scores"]:
        if not isinstance(item, dict):
            raise ModelGatewayError("model_invalid_response", "评分维度结果必须是对象")
        key = str(item.get("criterion_key") or "")
        if key not in criteria or key in seen:
            raise ValueError("评分结果包含未知或重复的评分维度")
        seen.add(key)
        criterion = criteria[key]
        try:
            score = Decimal(str(item.get("score")))
            maximum = Decimal(str(criterion.get("weight")))
        except (InvalidOperation, TypeError, ValueError) as exc:
            raise ValueError("维度得分必须是数字") from exc
        if score < 0 or score > maximum:
            raise ValueError("维度得分超出评分标准权重")
        status_value = str(item.get("status") or "")
        if status_value not in allowed_statuses:
            raise ValueError("评分维度状态无效")
        evidence_ids = [str(value) for value in item.get("resume_evidence_block_ids", []) or []]
        unknown = sorted(set(evidence_ids) - allowed_blocks)
        if unknown:
            raise ValueError(f"评分引用了不存在的简历证据：{unknown[0]}")
        if score > 0 and not evidence_ids:
            raise ValueError("非零得分必须提供简历原文证据")
        if status_value == "information_missing" and score != 0:
            raise ValueError("信息不足的维度得分必须为 0")
        total += score
        normalized_scores.append(
            {
                "criterion_key": key,
                "score": float(score) if score % 1 else int(score),
                "max_score": float(maximum) if maximum % 1 else int(maximum),
                "status": status_value,
                "reason": str(item.get("reason") or "").strip(),
                "resume_evidence_block_ids": evidence_ids,
            }
        )
    if seen != set(criteria):
        raise ValueError("评分结果缺少部分评分维度")
    hard_criteria = {
        str(item.get("key")): item for item in standard.criteria.get("hard_requirements", [])
    }
    hard_results = payload.get("hard_requirement_results") or []
    if not isinstance(hard_results, list):
        raise ModelGatewayError("model_invalid_response", "硬性指标判断格式无效")
    hard_seen = set()
    normalized_hard = []
    for item in hard_results:
        if not isinstance(item, dict):
            raise ModelGatewayError("model_invalid_response", "硬性指标判断必须是对象")
        key = str(item.get("criterion_key") or "")
        if key not in hard_criteria or key in hard_seen:
            raise ValueError("硬性指标判断包含未知或重复项目")
        status_value = str(item.get("status") or "")
        if status_value not in {"met", "not_met", "information_missing"}:
            raise ValueError("硬性指标判断状态无效")
        evidence_ids = [str(value) for value in item.get("resume_evidence_block_ids", []) or []]
        unknown = sorted(set(evidence_ids) - allowed_blocks)
        if unknown:
            raise ValueError(f"硬性指标引用了不存在的简历证据：{unknown[0]}")
        if status_value in {"met", "not_met"} and not evidence_ids:
            raise ValueError("硬性指标的明确结论必须提供简历原文证据")
        hard_seen.add(key)
        normalized_hard.append({
            "criterion_key": key,
            "text": str(hard_criteria[key].get("text") or ""),
            "status": status_value,
            "reason": str(item.get("reason") or "").strip(),
            "resume_evidence_block_ids": evidence_ids,
        })
    if hard_seen != set(hard_criteria):
        raise ValueError("硬性指标判断缺少部分项目")
    evidence = payload.get("evidence") or []
    if not isinstance(evidence, list):
        raise ModelGatewayError("model_invalid_response", "评分证据格式无效")
    unknown = sorted(set(_referenced_evidence_ids(evidence)) - allowed_blocks)
    if unknown:
        raise ValueError(f"评分证据引用了不存在的原文块：{unknown[0]}")
    try:
        confidence = Decimal(str(payload.get("confidence")))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError("模型置信度必须是 0 到 1 之间的数字") from exc
    if confidence < 0 or confidence > 1:
        raise ValueError("模型置信度必须是 0 到 1 之间的数字")
    recommendation = str(payload.get("recommendation") or "")
    if recommendation not in ResumeAssessment.Recommendation.values:
        raise ValueError("筛选建议无效")
    hard_failures = [item for item in normalized_hard if item["status"] == "not_met"]
    if hard_failures:
        recommendation = ResumeAssessment.Recommendation.HOLD
    gaps = payload.get("gaps") or []
    questions = payload.get("verification_questions") or []
    if not isinstance(gaps, list) or not isinstance(questions, list):
        raise ModelGatewayError("model_invalid_response", "缺口或核实问题格式无效")
    return {
        "total_score": float(total) if total % 1 else int(total),
        "dimension_scores": normalized_scores,
        "hard_failures": hard_failures,
        "evidence": evidence,
        "gaps": [str(item).strip() for item in gaps if str(item).strip()],
        "verification_questions": [str(item).strip() for item in questions if str(item).strip()],
        "confidence": confidence,
        "recommendation": recommendation,
    }


def build_assessment_prompt(*, standard, structured):
    system = (
        "你是招聘简历初筛助手。只能按已确认评分标准和简历证据评分。"
        "没有原文证据必须标记 information_missing 且得分为 0；结论仅供 HR 复核。"
    )
    user = json.dumps(
        {
            "criteria": standard.criteria,
            "structured_resume": structured.data,
            "resume_blocks": structured.extraction.blocks,
            "allowed_recommendations": list(ResumeAssessment.Recommendation.values),
            "hard_requirements": standard.criteria.get("hard_requirements", []),
            "hard_requirement_rule": "只有简历原文明确证明不满足时返回 not_met；没写或无法判断必须返回 information_missing",
            "required_dimension_fields": [
                "criterion_key", "score", "max_score", "status", "reason", "resume_evidence_block_ids"
            ],
        },
        ensure_ascii=False,
    )
    return system, user


@transaction.atomic
def create_assessment(*, structured, standard, gateway, request_id, actor=None) -> ResumeAssessment:
    existing = ResumeAssessment.objects.filter(request_id=request_id).first()
    if existing:
        if existing.structured_resume_id != structured.pk or existing.standard_id != standard.pk:
            raise ValueError("评分请求标识已被其他简历使用")
        return existing
    if standard.status != JobStandardVersion.Status.PUBLISHED:
        raise ValueError("请先确认并启用评分标准")
    if structured.resume.application_id and structured.resume.application.job_id != standard.job_id:
        raise ValueError("简历与评分标准不属于同一职位")
    system, user = build_assessment_prompt(standard=standard, structured=structured)
    normalized = validate_assessment_payload(
        payload=gateway.complete_json(system=system, user=user).data,
        standard=standard,
        structured=structured,
    )
    version = (
        ResumeAssessment.objects.filter(structured_resume=structured, standard=standard)
        .aggregate(value=Max("version"))["value"]
        or 0
    ) + 1
    assessment = ResumeAssessment.objects.create(
        structured_resume=structured,
        standard=standard,
        version=version,
        request_id=request_id,
        total_score=normalized["total_score"],
        dimension_scores=normalized["dimension_scores"],
        hard_failures=normalized["hard_failures"],
        evidence=normalized["evidence"],
        gaps=normalized["gaps"],
        verification_questions=normalized["verification_questions"],
        confidence=normalized["confidence"],
        recommendation=normalized["recommendation"],
        model_name=gateway.credential.model,
    )
    if (
        assessment.hard_failures
        and standard.criteria.get("auto_reject_on_hard_fail") is True
        and structured.resume.application_id
    ):
        from recruitment.services.stages import reject_for_hard_requirements
        assessment.auto_rejected = reject_for_hard_requirements(
            application=structured.resume.application,
            actor=actor,
            failure_keys=[item["criterion_key"] for item in assessment.hard_failures],
        )
        assessment.save(update_fields=["auto_rejected"])
    RecruitmentAuditLog.objects.create(
        actor=None,
        boss_account=standard.job.boss_account,
        action="resume_assessed",
        target_id=str(assessment.pk),
        detail={
            "resume_id": structured.resume_id,
            "standard_id": standard.pk,
            "standard_version": standard.version,
            "assessment_version": version,
            "model": assessment.model_name,
        },
    )
    return assessment


def process_resume_score_task(task: AiProcessingTask):
    if not task.resume_id or not task.standard_id:
        raise ValueError("评分任务缺少简历或评分标准")
    if task.standard.status != JobStandardVersion.Status.PUBLISHED:
        raise ValueError("评分标准尚未启用")
    structured = task.resume.structured_versions.order_by("-version").first()
    if not structured:
        raise ValueError("简历尚未完成结构化")
    credential = UserModelCredential.objects.get(user=task.requested_by)
    assessment = create_assessment(
        structured=structured,
        standard=task.standard,
        gateway=OpenAICompatibleGateway(credential),
        request_id=task.pk,
        actor=task.requested_by,
    )
    return {"resume_assessment_id": assessment.pk}
