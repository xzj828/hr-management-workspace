from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from recruitment.models import RpaTask, SearchCampaign
from recruitment.rpa.tasks import create_task


@transaction.atomic
def start_search_campaign(*, campaign, actor, workflow_node_run=None, idempotency_key=""):
    locked = SearchCampaign.objects.select_for_update().select_related("boss_account", "job").get(pk=campaign.pk)
    if locked.status not in {SearchCampaign.Status.DRAFT, SearchCampaign.Status.FAILED, SearchCampaign.Status.PAUSED}:
        raise ValidationError("当前主动寻访任务不能启动")
    if locked.max_scan_count < locked.target_resume_count:
        raise ValidationError("最大扫描人数不能小于目标简历数")
    task = create_task(
        account=locked.boss_account,
        action=RpaTask.Action.SEARCH_AND_PULL_RESUMES,
        actor=actor,
        workflow_node_run=workflow_node_run,
        request_payload={
            "campaign_id": locked.pk,
            "job": locked.job_id,
            "job_title": locked.job.title,
            "source": locked.source,
            "criteria": locked.criteria,
            "target_resume_count": locked.target_resume_count,
            "max_scan_count": locked.max_scan_count,
        },
        idempotency_key=idempotency_key or f"search-campaign:{locked.pk}:{locked.updated_at.isoformat()}",
    )
    locked.status = SearchCampaign.Status.QUEUED
    locked.stop_reason = SearchCampaign.StopReason.NONE
    locked.error_message = ""
    locked.save(update_fields=["status", "stop_reason", "error_message", "updated_at"])
    return task


@transaction.atomic
def stop_search_campaign(*, campaign):
    locked = SearchCampaign.objects.select_for_update().get(pk=campaign.pk)
    if locked.status in {SearchCampaign.Status.SUCCEEDED, SearchCampaign.Status.CANCELLED}:
        return locked
    locked.status = SearchCampaign.Status.CANCELLED
    locked.stop_reason = SearchCampaign.StopReason.USER_STOPPED
    locked.completed_at = timezone.now()
    locked.save(update_fields=["status", "stop_reason", "completed_at", "updated_at"])
    RpaTask.objects.filter(
        request_payload__campaign_id=locked.pk,
        status=RpaTask.Status.PENDING,
    ).update(status=RpaTask.Status.CANCELLED, completed_at=timezone.now())
    return locked
