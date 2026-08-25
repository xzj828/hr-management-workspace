from django.db import transaction
from django.utils import timezone

from recruitment.models import WorkflowNodeRun


EVENT_NODE_TYPES = {
    "candidate_message.received": "wait_reply",
    "resume.archived": "wait_resume",
}


@transaction.atomic
def publish_workflow_event(*, event, application, event_key, payload=None):
    node_type = EVENT_NODE_TYPES.get(event)
    if node_type is None or not event_key:
        return 0
    candidates = WorkflowNodeRun.objects.select_for_update().select_related("run").filter(
        node_type=node_type,
        status=WorkflowNodeRun.Status.WAITING_HUMAN,
        run__boss_account=application.job.boss_account,
        run__job=application.job,
    )
    changed_runs = []
    now = timezone.now()
    for node in candidates:
        application_ids = {str(value) for value in node.run.input_snapshot.get("application_ids", [])}
        if str(application.pk) not in application_ids:
            continue
        if node.config_snapshot.get("wake_event") != event:
            continue
        if node.output.get("event_key") == event_key:
            continue
        node.status = WorkflowNodeRun.Status.SUCCEEDED
        node.output = {"event": event, "event_key": event_key, **(payload or {})}
        node.completed_at = now
        node.save(update_fields=["status", "output", "completed_at", "updated_at"])
        changed_runs.append(node.run)

    if changed_runs:
        from recruitment.services.workflow_nodes import execute_workflow_node
        from recruitment.services.workflow_runtime import advance_run

        for run in {item.pk: item for item in changed_runs}.values():
            advance_run(run, executor=execute_workflow_node)
    return len(changed_runs)
