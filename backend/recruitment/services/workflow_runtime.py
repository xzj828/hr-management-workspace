from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import APIException, ValidationError

from recruitment.models import (
    AutomationApproval,
    BossAccount,
    ConversationAction,
    RecruitmentAuditLog,
    RecruitmentAutomationPlan,
    RpaTask,
    SearchCampaign,
    WorkflowNodeRun,
    WorkflowRun,
    WorkflowRunEvent,
)
from recruitment.services.sqlite_lifecycle import serialize_sqlite_lifecycle


HUMAN_NODE_TYPES = {"human_screen", "human_approval", "human_review"}
SUCCESS_STATES = {WorkflowNodeRun.Status.SUCCEEDED, WorkflowNodeRun.Status.SKIPPED}
NODE_TERMINAL_STATES = SUCCESS_STATES | {WorkflowNodeRun.Status.FAILED, WorkflowNodeRun.Status.CANCELLED}
RUN_TERMINAL_STATES = {WorkflowRun.Status.SUCCEEDED, WorkflowRun.Status.FAILED, WorkflowRun.Status.CANCELLED}


def _authorized_by_plan_start(run, node):
    return (
        run.automation_plan_revision_id is not None
        and node.node_type == "human_approval"
        and node.config_snapshot.get("authorization") == "plan_start"
        and node.config_snapshot.get("action") == "request_resume"
        and (run.input_snapshot.get("execution_authorization") or {}).get("source") == "plan_start"
        and "request_resume" in (run.input_snapshot.get("execution_authorization") or {}).get("actions", [])
    )


class WorkflowConflict(APIException):
    status_code = 409
    default_code = "workflow_state_conflict"


def _lock_run_for_update(run):
    snapshot = WorkflowRun.objects.filter(pk=run.pk).values(
        "boss_account_id", "automation_plan_revision_id"
    ).first()
    if snapshot is None:
        raise WorkflowRun.DoesNotExist
    if snapshot["automation_plan_revision_id"] is not None:
        BossAccount.objects.select_for_update().get(pk=snapshot["boss_account_id"])
        RecruitmentAutomationPlan.objects.select_for_update().get(
            revisions__pk=snapshot["automation_plan_revision_id"]
        )
    return WorkflowRun.objects.select_for_update().get(pk=run.pk)


def _event(run, event, message, *, node=None, data=None, actor=None):
    payload = dict(data or {})
    if actor is not None:
        payload["actor_id"] = actor.pk
    return WorkflowRunEvent.objects.create(run=run, node_run=node, event=event, message=message, data=payload)


def _snapshot(version):
    nodes = [
        {
            "key": node.node_key, "type": node.node_type, "label": node.label,
            "position": node.position, "config": node.config,
        }
        for node in version.nodes.order_by("id")
    ]
    edges = [
        {
            "source": edge.source.node_key,
            "target": edge.target.node_key,
            "order": edge.order,
            "condition": edge.condition,
        }
        for edge in version.edges.select_related("source", "target").order_by("order", "id")
    ]
    return {"nodes": nodes, "edges": edges, "version_id": version.pk, "version": version.version}


@serialize_sqlite_lifecycle
@transaction.atomic
def create_run(
    *,
    version,
    actor,
    mode,
    idempotency_key,
    input_snapshot=None,
    job=None,
    automation_plan_revision=None,
    automation_generation=None,
):
    existing = WorkflowRun.objects.filter(idempotency_key=idempotency_key).first()
    if existing:
        return existing
    if mode not in dict(WorkflowRun.Mode.choices):
        raise ValidationError("无效的运行模式")
    graph = _snapshot(version)
    incoming = {node["key"]: 0 for node in graph["nodes"]}
    for edge in graph["edges"]:
        incoming[edge["target"]] += 1
    now = timezone.now()
    run = WorkflowRun.objects.create(
        version=version, boss_account=version.boss_account, job=job, actor=actor, mode=mode,
        status=WorkflowRun.Status.RUNNING, idempotency_key=idempotency_key,
        graph_snapshot=graph, input_snapshot=input_snapshot or {}, started_at=now,
        automation_plan_revision=automation_plan_revision,
        automation_generation=automation_generation,
    )
    for node in graph["nodes"]:
        disabled = node["config"].get("enabled") is False
        status = WorkflowNodeRun.Status.SKIPPED if disabled else (
            WorkflowNodeRun.Status.READY if incoming[node["key"]] == 0 else WorkflowNodeRun.Status.BLOCKED
        )
        node_run = WorkflowNodeRun.objects.create(
            run=run, node_key=node["key"], node_type=node["type"], status=status,
            config_snapshot=node["config"], input_snapshot=run.input_snapshot,
            output={"skip_reason": "disabled"} if disabled else {},
            idempotency_key=f"{idempotency_key}:{node['key']}", completed_at=now if disabled else None,
        )
        _event(run, f"node.{status}", f"节点 {node['key']} {node_run.get_status_display()}", node=node_run)
    _event(run, "run.created", "流程运行已创建", data={"mode": mode}, actor=actor)
    return run


def _incoming(run):
    result = {node.node_key: [] for node in run.node_runs.all()}
    for edge in run.graph_snapshot.get("edges", []):
        result.setdefault(edge["target"], []).append(edge)
    return result


def _condition_matches(condition, output):
    def matches(actual, expected):
        return expected in actual if isinstance(actual, list) else actual == expected
    return all(matches(output.get(key), value) for key, value in (condition or {}).items())


@serialize_sqlite_lifecycle
@transaction.atomic
def advance_run(run, *, executor=None):
    locked = _lock_run_for_update(run)
    if locked.automation_plan_revision_id:
        from recruitment.services.automation_plans import plan_fence_is_current

        if not plan_fence_is_current(
            revision_id=locked.automation_plan_revision_id,
            generation=locked.automation_generation,
        ):
            return locked
    previous_status = locked.status
    if locked.status in RUN_TERMINAL_STATES | {WorkflowRun.Status.PAUSED}:
        return locked
    by_key = {node.node_key: node for node in locked.node_runs.select_for_update().all()}
    incoming = _incoming(locked)
    changed = True
    while changed:
        changed = False
        for key, node in by_key.items():
            if node.status == WorkflowNodeRun.Status.WAITING_HUMAN and executor is not None and node.node_type not in HUMAN_NODE_TYPES:
                outcome = executor(node)
                if outcome is not None and outcome[0] != node.status:
                    node.status, node.output = outcome[0], outcome[1] or {}
                    if node.status in NODE_TERMINAL_STATES:
                        node.completed_at = timezone.now()
                    node.save(update_fields=["status", "output", "completed_at", "updated_at"])
                    _event(locked, f"node.{node.status}", f"节点 {key} {node.get_status_display()}", node=node, data=node.output)
                    changed = True
                continue
            if node.status == WorkflowNodeRun.Status.BLOCKED:
                incoming_edges = incoming.get(key, [])
                parents = [by_key[edge["source"]] for edge in incoming_edges]
                has_conditions = any(edge.get("condition") for edge in incoming_edges)
                if has_conditions:
                    active_parents = [
                        by_key[edge["source"]]
                        for edge in incoming_edges
                        if _condition_matches(edge.get("condition"), by_key[edge["source"]].output)
                    ]
                    if any(parent.status in SUCCESS_STATES for parent in active_parents):
                        node.status = WorkflowNodeRun.Status.READY
                    elif parents and all(parent.status in NODE_TERMINAL_STATES for parent in parents):
                        node.status = WorkflowNodeRun.Status.SKIPPED
                        node.output = {"skip_reason": "condition_not_matched"}
                        node.completed_at = timezone.now()
                    else:
                        continue
                elif any(parent.status in {WorkflowNodeRun.Status.FAILED, WorkflowNodeRun.Status.CANCELLED} for parent in parents) or any(
                    parent.status == WorkflowNodeRun.Status.SKIPPED and parent.output.get("skip_reason") != "disabled"
                    for parent in parents
                ):
                    node.status = WorkflowNodeRun.Status.SKIPPED
                    node.output = {"skip_reason": "upstream_terminal"}
                    node.completed_at = timezone.now()
                elif parents and all(
                    parent.status == WorkflowNodeRun.Status.SUCCEEDED
                    or (parent.status == WorkflowNodeRun.Status.SKIPPED and parent.output.get("skip_reason") == "disabled")
                    for parent in parents
                ):
                    node.status = WorkflowNodeRun.Status.READY
                else:
                    continue
                node.save(update_fields=["status", "output", "completed_at", "updated_at"])
                _event(locked, f"node.{node.status}", f"节点 {key} {node.get_status_display()}", node=node)
                changed = True
            if node.status != WorkflowNodeRun.Status.READY:
                continue
            if node.node_type in HUMAN_NODE_TYPES:
                node.started_at = node.started_at or timezone.now()
                if _authorized_by_plan_start(locked, node):
                    node.status = WorkflowNodeRun.Status.SUCCEEDED
                    node.output = {
                        "approved": True,
                        "authorization": "plan_start",
                        "actor_id": locked.actor_id,
                    }
                    node.completed_at = timezone.now()
                    node.save(update_fields=["status", "output", "started_at", "completed_at", "updated_at"])
                    _event(
                        locked,
                        "node.authorized_at_plan_start",
                        f"节点 {key} 已复用开始执行授权",
                        node=node,
                        data=node.output,
                    )
                else:
                    node.status = WorkflowNodeRun.Status.WAITING_HUMAN
                    node.save(update_fields=["status", "started_at", "updated_at"])
                    _event(locked, "node.waiting_human", f"节点 {key} 等待人工决定", node=node)
                changed = True
                continue
            if executor is not None:
                outcome = executor(node)
                if outcome is None:
                    continue
                status, output = outcome
            elif locked.mode == WorkflowRun.Mode.DRY_RUN or node.node_type == "end":
                status, output = WorkflowNodeRun.Status.SUCCEEDED, {"simulated": locked.mode == WorkflowRun.Mode.DRY_RUN}
            else:
                continue
            node.status = status
            node.output = output or {}
            node.started_at = node.started_at or timezone.now()
            if status in NODE_TERMINAL_STATES:
                node.completed_at = timezone.now()
            node.save(update_fields=["status", "output", "started_at", "completed_at", "updated_at"])
            _event(locked, f"node.{status}", f"节点 {key} {node.get_status_display()}", node=node, data=node.output)
            changed = True

    statuses = [node.status for node in by_key.values()]
    now = timezone.now()
    if any(status == WorkflowNodeRun.Status.FAILED for status in statuses):
        locked.status = WorkflowRun.Status.FAILED
        locked.completed_at = now
    elif any(status == WorkflowNodeRun.Status.CANCELLED for status in statuses):
        locked.status = WorkflowRun.Status.CANCELLED
        locked.completed_at = now
    elif all(status in SUCCESS_STATES for status in statuses):
        locked.status = WorkflowRun.Status.SUCCEEDED
        locked.completed_at = now
    elif any(status == WorkflowNodeRun.Status.WAITING_HUMAN for status in statuses):
        locked.status = WorkflowRun.Status.WAITING_HUMAN
    else:
        locked.status = WorkflowRun.Status.RUNNING
    update_fields = ["status", "completed_at", "updated_at"]
    locked.save(update_fields=update_fields)
    if locked.status != previous_status:
        _event(locked, f"run.{locked.status}", locked.get_status_display())
    return locked


@serialize_sqlite_lifecycle
@transaction.atomic
def decide_node(node, *, approved, actor, note=""):
    locked = WorkflowNodeRun.objects.select_for_update().select_related("run").get(pk=node.pk)
    if locked.status != WorkflowNodeRun.Status.WAITING_HUMAN:
        raise WorkflowConflict("该节点当前不等待人工决定")
    locked.status = WorkflowNodeRun.Status.SUCCEEDED if approved else WorkflowNodeRun.Status.SKIPPED
    locked.output = {"approved": bool(approved), "note": note}
    locked.completed_at = timezone.now()
    locked.save(update_fields=["status", "output", "completed_at", "updated_at"])
    _event(locked.run, "node.decision", "人工已通过" if approved else "人工已跳过", node=locked, data=locked.output, actor=actor)
    return locked


@serialize_sqlite_lifecycle
@transaction.atomic
def pause_run(run, *, actor):
    locked = _lock_run_for_update(run)
    if locked.status in RUN_TERMINAL_STATES:
        raise WorkflowConflict("已结束的流程不能暂停")
    locked.status = WorkflowRun.Status.PAUSED
    locked.save(update_fields=["status", "updated_at"])
    _event(locked, "run.paused", "流程已暂停", actor=actor)
    return locked


@serialize_sqlite_lifecycle
@transaction.atomic
def resume_run(run, *, actor):
    locked = _lock_run_for_update(run)
    if locked.status != WorkflowRun.Status.PAUSED:
        raise WorkflowConflict("只有暂停中的流程可以恢复")
    locked.status = WorkflowRun.Status.RUNNING
    locked.save(update_fields=["status", "updated_at"])
    _event(locked, "run.resumed", "流程已恢复", actor=actor)
    return locked


@serialize_sqlite_lifecycle
@transaction.atomic
def cancel_run(run, *, actor):
    locked = _lock_run_for_update(run)
    if locked.status in RUN_TERMINAL_STATES:
        return locked
    now = timezone.now()
    nodes = list(locked.node_runs.select_for_update().all())
    node_ids = [node.pk for node in nodes]
    tasks = RpaTask.objects.select_for_update().filter(workflow_node_run_id__in=node_ids)
    active_node_ids = set(tasks.filter(
        status__in=[RpaTask.Status.LEASED, RpaTask.Status.RUNNING]
    ).values_list("workflow_node_run_id", flat=True))

    from recruitment.rpa.tasks import append_event
    from recruitment.services.approvals import reject
    from recruitment.services.communications import cancel_workflow_communication
    from recruitment.services.search_campaigns import stop_search_campaign

    communication_node_ids = set(tasks.filter(execution_batch__isnull=False).values_list(
        "workflow_node_run_id", flat=True
    ))
    for node in nodes:
        if node.pk in communication_node_ids:
            cancel_workflow_communication(workflow_node_run=node, actor=actor, now=now)

    for task in tasks.filter(status__in=[RpaTask.Status.LEASED, RpaTask.Status.RUNNING]):
        if task.workflow_node_run_id in communication_node_ids:
            continue
        if task.action == RpaTask.Action.SEARCH_AND_PULL_RESUMES:
            campaign = SearchCampaign.objects.select_for_update().filter(
                pk=task.request_payload.get("campaign_id"),
                boss_account=locked.boss_account,
            ).first()
            if campaign is not None:
                stop_search_campaign(campaign=campaign)
            continue
        if task.status == RpaTask.Status.CANCEL_REQUESTED:
            continue
        task.status = RpaTask.Status.CANCEL_REQUESTED
        task.save(update_fields=["status", "updated_at"])
        append_event(
            task=task,
            event="cancel_requested",
            message="所属流程已取消，已通知本机 Worker 中断当前任务",
            data={"status": task.status},
        )

    stopped_campaign_ids = set()
    for task in tasks.filter(status=RpaTask.Status.PENDING):
        if task.action == RpaTask.Action.SEARCH_AND_PULL_RESUMES:
            campaign = SearchCampaign.objects.select_for_update().filter(
                pk=task.request_payload.get("campaign_id"),
                boss_account=locked.boss_account,
            ).first()
            if campaign is not None:
                stop_search_campaign(campaign=campaign)
                stopped_campaign_ids.add(campaign.pk)
                continue
        if task.status != RpaTask.Status.PENDING:
            continue
        task.status = RpaTask.Status.CANCELLED
        task.error_code = "workflow_cancelled"
        task.error_message = "所属流程已取消，任务未进入外部适配器"
        task.completed_at = now
        task.lease_expires_at = None
        task.save(update_fields=[
            "status", "error_code", "error_message", "completed_at", "lease_expires_at", "updated_at",
        ])
        append_event(task=task, event="cancelled", message="所属流程已取消，任务未执行")
        RecruitmentAuditLog.objects.create(
            actor=actor,
            boss_account=locked.boss_account,
            action="workflow_task_cancelled",
            target_id=str(task.pk),
            detail={"workflow_run_id": str(locked.pk), "task_action": task.action},
        )

    approval_ids = {
        str((node.output or {}).get("approval_id"))
        for node in nodes
        if (node.output or {}).get("approval_id")
    }
    approvals = AutomationApproval.objects.select_for_update().filter(
        pk__in=approval_ids,
        boss_account=locked.boss_account,
    )
    for approval in approvals:
        if approval.status == AutomationApproval.Status.DRAFT:
            reject(approval=approval, actor=actor, note="所属流程已取消")
            ConversationAction.objects.filter(
                approval=approval,
                status__in=[ConversationAction.Status.DRAFT, ConversationAction.Status.APPROVED],
            ).update(
                status=ConversationAction.Status.CANCELLED,
                error_code="workflow_cancelled",
                error_message="所属流程已取消",
                completed_at=now,
                updated_at=now,
            )

    for node in nodes:
        if node.node_type != "search_and_pull_resumes" or node.pk in active_node_ids:
            continue
        campaign_id = (node.output or {}).get("campaign_id")
        if not campaign_id or campaign_id in stopped_campaign_ids:
            continue
        campaign = SearchCampaign.objects.select_for_update().filter(
            pk=campaign_id,
            workflow_run=locked,
        ).first()
        if campaign is not None and campaign.status not in {
            SearchCampaign.Status.SUCCEEDED,
            SearchCampaign.Status.CANCELLED,
        }:
            stop_search_campaign(campaign=campaign)

    for node in nodes:
        if node.pk in active_node_ids or node.status in NODE_TERMINAL_STATES:
            continue
        node.status = WorkflowNodeRun.Status.CANCELLED
        node.completed_at = now
        node.error_code = "workflow_cancelled"
        node.error_message = "流程已由用户取消"
        node.save(update_fields=[
            "status", "completed_at", "error_code", "error_message", "updated_at",
        ])
        _event(locked, "node.cancelled", f"节点 {node.node_key} 已取消", node=node, actor=actor)
    locked.status = WorkflowRun.Status.CANCELLED
    locked.completed_at = now
    locked.save(update_fields=["status", "completed_at", "updated_at"])
    _event(locked, "run.cancelled", "流程已取消", actor=actor)
    return locked


@serialize_sqlite_lifecycle
@transaction.atomic
def retry_node(node, *, actor):
    locked = WorkflowNodeRun.objects.select_for_update().select_related("run").get(pk=node.pk)
    if locked.status != WorkflowNodeRun.Status.FAILED:
        raise WorkflowConflict("只有失败节点可以重试")
    locked.status = WorkflowNodeRun.Status.READY
    locked.attempt += 1
    locked.output = {}
    locked.error_code = ""
    locked.error_message = ""
    locked.completed_at = None
    locked.save(update_fields=[
        "status", "attempt", "output", "error_code", "error_message", "completed_at", "updated_at",
    ])
    locked.run.status = WorkflowRun.Status.RUNNING
    locked.run.completed_at = None
    locked.run.save(update_fields=["status", "completed_at", "updated_at"])
    outgoing = {}
    for edge in locked.run.graph_snapshot.get("edges", []):
        outgoing.setdefault(edge["source"], []).append(edge["target"])
    descendants = set()
    pending = list(outgoing.get(locked.node_key, []))
    while pending:
        key = pending.pop()
        if key in descendants:
            continue
        descendants.add(key)
        pending.extend(outgoing.get(key, []))
    locked.run.node_runs.filter(
        node_key__in=descendants,
        status__in=[WorkflowNodeRun.Status.SKIPPED, WorkflowNodeRun.Status.CANCELLED],
    ).update(status=WorkflowNodeRun.Status.BLOCKED, completed_at=None, updated_at=timezone.now())
    _event(locked.run, "node.retry", "节点已重新就绪", node=locked, data={"attempt": locked.attempt}, actor=actor)
    return locked
