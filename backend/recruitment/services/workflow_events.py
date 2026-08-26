from django.db import transaction
from django.utils import timezone

from recruitment.models import (
    BossAccount,
    RecruitmentAutomationPlan,
    WorkflowNodeRun,
    WorkflowRun,
)
from recruitment.services.sqlite_lifecycle import serialize_sqlite_lifecycle


EVENT_NODE_TYPES = {
    "candidate_message.received": "wait_reply",
    "resume.archived": "wait_resume",
}


@serialize_sqlite_lifecycle
@transaction.atomic
def publish_workflow_event(*, event, application, event_key, payload=None):
    node_type = EVENT_NODE_TYPES.get(event)
    if node_type is None or not event_key:
        return 0
    candidate_rows = list(WorkflowNodeRun.objects.filter(
        node_type=node_type,
        status=WorkflowNodeRun.Status.WAITING_HUMAN,
        run__boss_account=application.job.boss_account,
        run__job=application.job,
    ).values("pk", "run_id", "run__automation_plan_revision_id"))
    if not candidate_rows:
        return 0

    # Stop locks Account -> Plan -> Run -> Node.  Event wake-up must use the
    # same order; locking Node first can deadlock with a concurrent stop.
    BossAccount.objects.select_for_update().get(pk=application.job.boss_account_id)
    revision_ids = sorted({
        row["run__automation_plan_revision_id"]
        for row in candidate_rows
        if row["run__automation_plan_revision_id"] is not None
    })
    if revision_ids:
        list(
            RecruitmentAutomationPlan.objects.select_for_update()
            .filter(revisions__pk__in=revision_ids)
            .order_by("pk")
        )
    run_ids = sorted({row["run_id"] for row in candidate_rows})
    list(WorkflowRun.objects.select_for_update().filter(pk__in=run_ids).order_by("pk"))
    candidates = WorkflowNodeRun.objects.select_for_update().select_related("run").filter(
        pk__in=[row["pk"] for row in candidate_rows],
        status=WorkflowNodeRun.Status.WAITING_HUMAN,
    ).order_by("pk")
    changed_runs = []
    now = timezone.now()
    for node in candidates:
        if node.run.automation_plan_revision_id is not None:
            from recruitment.services.automation_plans import plan_fence_is_current

            if not plan_fence_is_current(
                revision_id=node.run.automation_plan_revision_id,
                generation=node.run.automation_generation,
            ):
                continue
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
