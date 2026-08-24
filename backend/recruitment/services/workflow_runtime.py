from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from recruitment.models import WorkflowNodeRun, WorkflowRun, WorkflowRunEvent


HUMAN_NODE_TYPES = {"human_screen", "human_approval", "human_review"}
SUCCESS_STATES = {WorkflowNodeRun.Status.SUCCEEDED, WorkflowNodeRun.Status.SKIPPED}
NODE_TERMINAL_STATES = SUCCESS_STATES | {WorkflowNodeRun.Status.FAILED, WorkflowNodeRun.Status.CANCELLED}
RUN_TERMINAL_STATES = {WorkflowRun.Status.SUCCEEDED, WorkflowRun.Status.FAILED, WorkflowRun.Status.CANCELLED}


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
        {"source": edge.source.node_key, "target": edge.target.node_key, "order": edge.order}
        for edge in version.edges.select_related("source", "target").order_by("order", "id")
    ]
    return {"nodes": nodes, "edges": edges, "version_id": version.pk, "version": version.version}


@transaction.atomic
def create_run(*, version, actor, mode, idempotency_key, input_snapshot=None, job=None):
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
    )
    for node in graph["nodes"]:
        disabled = node["config"].get("enabled") is False
        status = WorkflowNodeRun.Status.SKIPPED if disabled else (
            WorkflowNodeRun.Status.READY if incoming[node["key"]] == 0 else WorkflowNodeRun.Status.BLOCKED
        )
        node_run = WorkflowNodeRun.objects.create(
            run=run, node_key=node["key"], node_type=node["type"], status=status,
            config_snapshot=node["config"], input_snapshot=run.input_snapshot,
            idempotency_key=f"{idempotency_key}:{node['key']}", completed_at=now if disabled else None,
        )
        _event(run, f"node.{status}", f"节点 {node['key']} {node_run.get_status_display()}", node=node_run)
    _event(run, "run.created", "流程运行已创建", data={"mode": mode}, actor=actor)
    return run


def _incoming(run):
    result = {node.node_key: [] for node in run.node_runs.all()}
    for edge in run.graph_snapshot.get("edges", []):
        result.setdefault(edge["target"], []).append(edge["source"])
    return result


@transaction.atomic
def advance_run(run, *, executor=None):
    locked = WorkflowRun.objects.select_for_update().get(pk=run.pk)
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
                parents = [by_key[parent] for parent in incoming.get(key, [])]
                if any(parent.status in {WorkflowNodeRun.Status.FAILED, WorkflowNodeRun.Status.CANCELLED} for parent in parents):
                    node.status = WorkflowNodeRun.Status.SKIPPED
                    node.completed_at = timezone.now()
                elif parents and all(parent.status in SUCCESS_STATES for parent in parents):
                    node.status = WorkflowNodeRun.Status.READY
                else:
                    continue
                node.save(update_fields=["status", "completed_at", "updated_at"])
                _event(locked, f"node.{node.status}", f"节点 {key} {node.get_status_display()}", node=node)
                changed = True
            if node.status != WorkflowNodeRun.Status.READY:
                continue
            if node.node_type in HUMAN_NODE_TYPES:
                node.status = WorkflowNodeRun.Status.WAITING_HUMAN
                node.started_at = node.started_at or timezone.now()
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


@transaction.atomic
def decide_node(node, *, approved, actor, note=""):
    locked = WorkflowNodeRun.objects.select_for_update().select_related("run").get(pk=node.pk)
    if locked.status != WorkflowNodeRun.Status.WAITING_HUMAN:
        raise ValidationError("该节点当前不等待人工决定")
    locked.status = WorkflowNodeRun.Status.SUCCEEDED if approved else WorkflowNodeRun.Status.SKIPPED
    locked.output = {"approved": bool(approved), "note": note}
    locked.completed_at = timezone.now()
    locked.save(update_fields=["status", "output", "completed_at", "updated_at"])
    _event(locked.run, "node.decision", "人工已通过" if approved else "人工已跳过", node=locked, data=locked.output, actor=actor)
    return locked


@transaction.atomic
def pause_run(run, *, actor):
    locked = WorkflowRun.objects.select_for_update().get(pk=run.pk)
    if locked.status in RUN_TERMINAL_STATES:
        raise ValidationError("已结束的流程不能暂停")
    locked.status = WorkflowRun.Status.PAUSED
    locked.save(update_fields=["status", "updated_at"])
    _event(locked, "run.paused", "流程已暂停", actor=actor)
    return locked


@transaction.atomic
def resume_run(run, *, actor):
    locked = WorkflowRun.objects.select_for_update().get(pk=run.pk)
    if locked.status != WorkflowRun.Status.PAUSED:
        raise ValidationError("只有暂停中的流程可以恢复")
    locked.status = WorkflowRun.Status.RUNNING
    locked.save(update_fields=["status", "updated_at"])
    _event(locked, "run.resumed", "流程已恢复", actor=actor)
    return locked


@transaction.atomic
def cancel_run(run, *, actor):
    locked = WorkflowRun.objects.select_for_update().get(pk=run.pk)
    if locked.status in RUN_TERMINAL_STATES:
        return locked
    now = timezone.now()
    locked.node_runs.filter(status__in=[WorkflowNodeRun.Status.BLOCKED, WorkflowNodeRun.Status.READY]).update(
        status=WorkflowNodeRun.Status.CANCELLED, completed_at=now, updated_at=now,
    )
    locked.status = WorkflowRun.Status.CANCELLED
    locked.completed_at = now
    locked.save(update_fields=["status", "completed_at", "updated_at"])
    _event(locked, "run.cancelled", "流程已取消", actor=actor)
    return locked


@transaction.atomic
def retry_node(node, *, actor):
    locked = WorkflowNodeRun.objects.select_for_update().select_related("run").get(pk=node.pk)
    if locked.status != WorkflowNodeRun.Status.FAILED:
        raise ValidationError("只有失败节点可以重试")
    locked.status = WorkflowNodeRun.Status.READY
    locked.attempt += 1
    locked.error_code = ""
    locked.error_message = ""
    locked.completed_at = None
    locked.save(update_fields=["status", "attempt", "error_code", "error_message", "completed_at", "updated_at"])
    locked.run.status = WorkflowRun.Status.RUNNING
    locked.run.completed_at = None
    locked.run.save(update_fields=["status", "completed_at", "updated_at"])
    _event(locked.run, "node.retry", "节点已重新就绪", node=locked, data={"attempt": locked.attempt}, actor=actor)
    return locked
