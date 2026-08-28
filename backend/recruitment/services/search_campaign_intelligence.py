import uuid

from django.db import transaction
from django.utils import timezone

from recruitment.models import (
    AiProcessingTask,
    ResumeAssessment,
    SearchCampaign,
    SearchCampaignItem,
    WorkflowNodeRun,
)
from recruitment.services.ai_tasks import enqueue_resume_score, enqueue_resume_structure


AI_ACTIVE_STATUSES = {
    AiProcessingTask.Status.PENDING,
    AiProcessingTask.Status.EXTRACTING,
    AiProcessingTask.Status.OCR,
    AiProcessingTask.Status.MODEL,
}
ANALYZED_ITEM_STATUSES = {
    SearchCampaignItem.Status.QUALIFIED,
    SearchCampaignItem.Status.NOT_QUALIFIED,
}


def _score_request_id(item):
    return uuid.uuid5(
        uuid.NAMESPACE_URL,
        f"search-campaign:{item.campaign_id}:resume:{item.resume_id}:standard:{item.campaign.standard_id}",
    )


def _set_item_from_assessment(item, assessment):
    item.assessment = assessment
    item.status = (
        SearchCampaignItem.Status.QUALIFIED
        if (
            assessment.total_score >= (assessment.passing_score_snapshot or 0)
            and (assessment.system_recommendation or assessment.recommendation)
            == ResumeAssessment.Recommendation.ADVANCE
        )
        else SearchCampaignItem.Status.NOT_QUALIFIED
    )
    item.error_code = ""
    item.error_message = ""
    item.analyzed_at = timezone.now()
    item.save(update_fields=[
        "assessment", "status", "error_code", "error_message", "analyzed_at", "updated_at",
    ])


def _sync_task_state(item, task, *, active_status):
    if task.status == AiProcessingTask.Status.WAITING_CONFIG:
        item.status = SearchCampaignItem.Status.WAITING_CONFIG
        item.error_code = task.error_code or "model_not_configured"
        item.error_message = task.error_message or "等待配置可用的大模型连接"
    elif task.status == AiProcessingTask.Status.FAILED:
        item.status = SearchCampaignItem.Status.FAILED
        item.error_code = task.error_code or "ai_task_failed"
        item.error_message = task.error_message or "AI 分析失败，请重试"
    else:
        item.status = active_status
        item.error_code = ""
        item.error_message = ""
    item.save(update_fields=["status", "error_code", "error_message", "updated_at"])


def _schedule_workflow_refresh(campaign_id):
    transaction.on_commit(lambda: refresh_search_campaign_workflow(campaign_id))


@transaction.atomic
def reconcile_search_campaign(campaign_id):
    campaign = (
        SearchCampaign.objects.select_for_update()
        .select_related("standard", "workflow_run")
        .get(pk=campaign_id)
    )
    if campaign.status in {
        SearchCampaign.Status.SUCCEEDED,
        SearchCampaign.Status.FAILED,
        SearchCampaign.Status.CANCELLED,
    }:
        return campaign

    items = list(
        SearchCampaignItem.objects.select_for_update()
        .select_related(
            "resume", "structure_task", "score_task", "assessment", "campaign__standard",
        )
        .filter(campaign=campaign)
        .order_by("sequence", "id")
    )
    campaign.pulled_resume_count = len(items)

    if campaign.standard_id is None:
        campaign.status = SearchCampaign.Status.FAILED
        campaign.stop_reason = SearchCampaign.StopReason.ANALYSIS_FAILED
        campaign.error_message = "主动寻访缺少已冻结的岗位评分标准"
        campaign.completed_at = timezone.now()
        campaign.save(update_fields=[
            "status", "stop_reason", "error_message", "pulled_resume_count",
            "completed_at", "updated_at",
        ])
        _schedule_workflow_refresh(campaign.pk)
        return campaign

    # Reconcile already-linked tasks before deciding whether to schedule the next item.
    for item in items:
        if item.status in ANALYZED_ITEM_STATUSES | {SearchCampaignItem.Status.SKIPPED}:
            continue
        structure = item.resume.structured_versions.order_by("-version", "-id").first()
        if item.structure_task_id:
            item.structure_task.refresh_from_db()
            if item.structure_task.status in {
                AiProcessingTask.Status.WAITING_CONFIG,
                AiProcessingTask.Status.FAILED,
            }:
                _sync_task_state(item, item.structure_task, active_status=SearchCampaignItem.Status.STRUCTURING)
                continue
            if item.structure_task.status != AiProcessingTask.Status.SUCCEEDED and structure is None:
                _sync_task_state(item, item.structure_task, active_status=SearchCampaignItem.Status.STRUCTURING)
                continue
        if structure is None:
            continue

        assessment = (
            ResumeAssessment.objects.filter(structured_resume=structure, standard=campaign.standard)
            .order_by("-version", "-created_at", "-id")
            .first()
        )
        if assessment is not None:
            _set_item_from_assessment(item, assessment)
            continue
        if item.score_task_id:
            item.score_task.refresh_from_db()
            if item.score_task.status in {
                AiProcessingTask.Status.WAITING_CONFIG,
                AiProcessingTask.Status.FAILED,
            }:
                _sync_task_state(item, item.score_task, active_status=SearchCampaignItem.Status.SCORING)
            else:
                _sync_task_state(item, item.score_task, active_status=SearchCampaignItem.Status.SCORING)
        elif item.status != SearchCampaignItem.Status.PENDING:
            task, _ = enqueue_resume_score(
                structured_resume=structure,
                standard=campaign.standard,
                requested_by=campaign.created_by,
                request_id=_score_request_id(item),
            )
            item.score_task = task
            item.status = (
                SearchCampaignItem.Status.WAITING_CONFIG
                if task.status == AiProcessingTask.Status.WAITING_CONFIG
                else SearchCampaignItem.Status.SCORING
            )
            item.error_code = task.error_code
            item.error_message = task.error_message
            item.save(update_fields=[
                "score_task", "status", "error_code", "error_message", "updated_at",
            ])

    items = list(SearchCampaignItem.objects.select_for_update().filter(campaign=campaign).order_by("sequence", "id"))
    analyzed = sum(item.status in ANALYZED_ITEM_STATUSES for item in items)
    qualified = sum(item.status == SearchCampaignItem.Status.QUALIFIED for item in items)
    failed = sum(item.status == SearchCampaignItem.Status.FAILED for item in items)
    campaign.scanned_count = analyzed
    campaign.qualified_resume_count = qualified
    campaign.analysis_failed_count = failed

    if qualified >= campaign.target_resume_count:
        SearchCampaignItem.objects.filter(
            campaign=campaign,
            status=SearchCampaignItem.Status.PENDING,
        ).update(status=SearchCampaignItem.Status.SKIPPED, updated_at=timezone.now())
        campaign.status = SearchCampaign.Status.SUCCEEDED
        campaign.stop_reason = SearchCampaign.StopReason.TARGET_REACHED
        campaign.error_message = ""
        campaign.completed_at = timezone.now()
    else:
        blocked = next((item for item in items if item.status in {
            SearchCampaignItem.Status.WAITING_CONFIG,
            SearchCampaignItem.Status.FAILED,
        }), None)
        if blocked is not None:
            campaign.status = SearchCampaign.Status.PAUSED
            campaign.stop_reason = (
                SearchCampaign.StopReason.ANALYSIS_FAILED
                if blocked.status == SearchCampaignItem.Status.FAILED
                else SearchCampaign.StopReason.NONE
            )
            campaign.error_message = blocked.error_message
            campaign.completed_at = None
        else:
            active = next((item for item in items if item.status in {
                SearchCampaignItem.Status.STRUCTURING,
                SearchCampaignItem.Status.SCORING,
            }), None)
            if active is None:
                pending = next((item for item in items if item.status == SearchCampaignItem.Status.PENDING), None)
                if pending is not None and analyzed < campaign.max_scan_count:
                    structure = pending.resume.structured_versions.order_by("-version", "-id").first()
                    if structure is None:
                        task, _ = enqueue_resume_structure(
                            resume=pending.resume,
                            requested_by=campaign.created_by,
                            request_id=f"campaign-{campaign.pk}-item-{pending.pk}",
                        )
                        pending.structure_task = task
                        pending.status = (
                            SearchCampaignItem.Status.WAITING_CONFIG
                            if task.status == AiProcessingTask.Status.WAITING_CONFIG
                            else SearchCampaignItem.Status.STRUCTURING
                        )
                        pending.error_code = task.error_code or (
                            "model_not_configured"
                            if task.status == AiProcessingTask.Status.WAITING_CONFIG
                            else ""
                        )
                        pending.error_message = task.error_message or (
                            "等待配置可用的大模型连接"
                            if task.status == AiProcessingTask.Status.WAITING_CONFIG
                            else ""
                        )
                        pending.save(update_fields=[
                            "structure_task", "status", "error_code", "error_message", "updated_at",
                        ])
                    else:
                        task, _ = enqueue_resume_score(
                            structured_resume=structure,
                            standard=campaign.standard,
                            requested_by=campaign.created_by,
                            request_id=_score_request_id(pending),
                        )
                        pending.score_task = task
                        pending.status = (
                            SearchCampaignItem.Status.WAITING_CONFIG
                            if task.status == AiProcessingTask.Status.WAITING_CONFIG
                            else SearchCampaignItem.Status.SCORING
                        )
                        pending.error_code = task.error_code or (
                            "model_not_configured"
                            if task.status == AiProcessingTask.Status.WAITING_CONFIG
                            else ""
                        )
                        pending.error_message = task.error_message or (
                            "等待配置可用的大模型连接"
                            if task.status == AiProcessingTask.Status.WAITING_CONFIG
                            else ""
                        )
                        pending.save(update_fields=[
                            "score_task", "status", "error_code", "error_message", "updated_at",
                        ])
                    active = pending
                else:
                    campaign.status = SearchCampaign.Status.SUCCEEDED
                    campaign.stop_reason = (
                        SearchCampaign.StopReason.SCAN_LIMIT
                        if analyzed >= campaign.max_scan_count
                        else SearchCampaign.StopReason.CANDIDATES_EXHAUSTED
                    )
                    campaign.error_message = ""
                    campaign.completed_at = timezone.now()
            if active is not None:
                campaign.status = (
                    SearchCampaign.Status.PAUSED
                    if active.status == SearchCampaignItem.Status.WAITING_CONFIG
                    else SearchCampaign.Status.ANALYZING
                )
                campaign.stop_reason = SearchCampaign.StopReason.NONE
                campaign.error_message = active.error_message
                campaign.completed_at = None

    campaign.save(update_fields=[
        "status", "stop_reason", "error_message", "scanned_count", "pulled_resume_count",
        "qualified_resume_count", "analysis_failed_count", "completed_at", "updated_at",
    ])
    _schedule_workflow_refresh(campaign.pk)
    return campaign


def notify_search_campaigns_for_ai_task(task):
    campaign_ids = set(task.search_campaign_structure_items.values_list("campaign_id", flat=True))
    campaign_ids.update(task.search_campaign_score_items.values_list("campaign_id", flat=True))
    for campaign_id in sorted(campaign_ids):
        reconcile_search_campaign(campaign_id)


def refresh_search_campaign_workflow(campaign_id):
    campaign = SearchCampaign.objects.select_related("workflow_run").filter(pk=campaign_id).first()
    if campaign is None or campaign.workflow_run_id is None:
        return None
    node = (
        WorkflowNodeRun.objects.select_related("run")
        .filter(run_id=campaign.workflow_run_id, node_type="search_and_pull_resumes")
        .order_by("created_at", "id")
        .first()
    )
    if node is None:
        return None
    from recruitment.services.workflow_nodes import execute_workflow_node
    from recruitment.services.workflow_runtime import NODE_TERMINAL_STATES, advance_run

    outcome = execute_workflow_node(node)
    if outcome is None:
        return None
    node.status, node.output = outcome[0], outcome[1] or {}
    node.error_code = campaign.stop_reason if node.status in {
        WorkflowNodeRun.Status.FAILED,
        WorkflowNodeRun.Status.WAITING_HUMAN,
    } else ""
    node.error_message = campaign.error_message
    node.completed_at = timezone.now() if node.status in NODE_TERMINAL_STATES else None
    node.save(update_fields=[
        "status", "output", "error_code", "error_message", "completed_at", "updated_at",
    ])
    return advance_run(node.run, executor=execute_workflow_node)
