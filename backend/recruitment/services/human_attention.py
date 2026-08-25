from django.db import transaction
from django.utils import timezone

from recruitment.models import HumanAttention, WorkflowNodeRun


def ensure_attention(
    *,
    attention_type,
    title,
    idempotency_key,
    account=None,
    job=None,
    application=None,
    workflow_run=None,
    workflow_node_run=None,
    detail=None,
    priority=0,
):
    return HumanAttention.objects.get_or_create(
        idempotency_key=idempotency_key,
        defaults={
            "attention_type": attention_type,
            "title": title,
            "boss_account": account,
            "job": job,
            "application": application,
            "workflow_run": workflow_run,
            "workflow_node_run": workflow_node_run,
            "detail": detail or {},
            "priority": priority,
        },
    )


@transaction.atomic
def resolve_attention(*, attention, actor, note="", approved=True):
    locked = HumanAttention.objects.select_for_update().select_related("workflow_node_run__run").get(pk=attention.pk)
    if locked.status != HumanAttention.Status.OPEN:
        return locked
    locked.status = HumanAttention.Status.RESOLVED
    locked.resolved_by = actor
    locked.resolution_note = note.strip()[:2000]
    locked.resolved_at = timezone.now()
    locked.save(
        update_fields=["status", "resolved_by", "resolution_note", "resolved_at", "updated_at"]
    )
    node = locked.workflow_node_run
    if node and node.status == WorkflowNodeRun.Status.WAITING_HUMAN:
        from recruitment.services.workflow_nodes import execute_workflow_node
        from recruitment.services.workflow_runtime import advance_run, decide_node

        decide_node(node, approved=approved, actor=actor, note=locked.resolution_note)
        transaction.on_commit(lambda: advance_run(node.run, executor=execute_workflow_node))
    return locked


@transaction.atomic
def archive_attention(*, attention):
    locked = HumanAttention.objects.select_for_update().get(pk=attention.pk)
    locked.status = HumanAttention.Status.ARCHIVED
    locked.archived_at = timezone.now()
    locked.save(update_fields=["status", "archived_at", "updated_at"])
    return locked
