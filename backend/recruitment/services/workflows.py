from collections import defaultdict, deque

from django.db import transaction
from django.db.models import Max
from rest_framework.exceptions import ValidationError

from recruitment.models import RecruitmentAuditLog, WorkflowEdge, WorkflowNode, WorkflowVersion


ALLOWED_NODE_TYPES = {
    "start", "sync_messages", "classify_intent", "create_attention", "stop",
    "archive_resume", "search_and_pull_resumes",
    "recommend", "search", "deep_search", "human_screen", "import_candidate",
    "human_approval", "greet", "wait_reply", "request_resume", "wait_resume",
    "human_review", "send_interview", "end",
}
SOURCE_TYPES = {"recommend", "search", "deep_search", "sync_messages", "search_and_pull_resumes"}
SEND_TYPES = {"greet", "request_resume", "send_interview"}
WAIT_EVENTS = {"wait_reply": "candidate_message.received", "wait_resume": "resume.archived"}


def validate_graph(*, nodes, edges, boss_account):
    if not isinstance(nodes, list) or not isinstance(edges, list) or not nodes:
        raise ValidationError("流程节点和连线不能为空")
    if len(nodes) > 40 or len(edges) > 80:
        raise ValidationError("单个流程最多 40 个节点和 80 条连线")
    by_key = {}
    for node in nodes:
        key = str(node.get("key", "")).strip()
        node_type = str(node.get("type", "")).strip()
        if not key or key in by_key:
            raise ValidationError("流程节点标识不能为空或重复")
        if node_type not in ALLOWED_NODE_TYPES:
            raise ValidationError(f"不允许的流程节点：{node_type or '空'}")
        config = node.get("config") if isinstance(node.get("config"), dict) else {}
        if node_type in WAIT_EVENTS and config.get("wake_event") != WAIT_EVENTS[node_type]:
            raise ValidationError(f"节点 {key} 必须配置正确的唤醒事件")
        if node_type == "search_and_pull_resumes":
            if int(config.get("target_resume_count", 0) or 0) < 1 or int(config.get("max_scan_count", 0) or 0) < 1:
                raise ValidationError(f"节点 {key} 必须配置目标合格简历数和 AI 最大分析份数")
        by_key[key] = node
    if not any(node["type"] in SOURCE_TYPES for node in nodes):
        raise ValidationError("流程必须包含候选人来源节点")
    if boss_account is None:
        raise ValidationError("自动化流程必须绑定 BOSS 账号")
    adjacency = defaultdict(list)
    indegree = {key: 0 for key in by_key}
    reverse = defaultdict(list)
    seen_edges = set()
    for edge in edges:
        source, target = str(edge.get("source", "")), str(edge.get("target", ""))
        if source not in by_key or target not in by_key or source == target:
            raise ValidationError("流程连线引用了无效节点")
        if (source, target) in seen_edges:
            raise ValidationError("流程存在重复连线")
        seen_edges.add((source, target))
        adjacency[source].append(target)
        reverse[target].append(source)
        indegree[target] += 1
    if len(nodes) > 1:
        disconnected = [key for key in by_key if not adjacency[key] and not reverse[key]]
        if disconnected:
            raise ValidationError(f"流程存在未连接节点：{', '.join(disconnected)}")
        roots = [key for key, degree in indegree.items() if degree == 0]
        if len(roots) != 1:
            raise ValidationError("流程必须只有一个起始入口")
    queue = deque(key for key, degree in indegree.items() if degree == 0)
    visited = []
    while queue:
        key = queue.popleft()
        visited.append(key)
        for target in adjacency[key]:
            indegree[target] -= 1
            if indegree[target] == 0:
                queue.append(target)
    if len(visited) != len(nodes):
        raise ValidationError("流程禁止循环连线")
    for key, node in by_key.items():
        if node["type"] not in SEND_TYPES:
            continue
        ancestors = set()
        pending = list(reverse[key])
        while pending:
            parent = pending.pop()
            if parent in ancestors:
                continue
            ancestors.add(parent)
            pending.extend(reverse[parent])
        if not any(by_key[parent]["type"] == "human_approval" for parent in ancestors):
            raise ValidationError("所有发送节点前必须经过人工确认")
    return True


@transaction.atomic
def create_version(*, template, boss_account, nodes, edges, actor):
    validate_graph(nodes=nodes, edges=edges, boss_account=boss_account)
    next_version = (template.versions.aggregate(value=Max("version"))["value"] or 0) + 1
    version = WorkflowVersion.objects.create(
        template=template, version=next_version, boss_account=boss_account, created_by=actor
    )
    node_models = {}
    for item in nodes:
        node_models[item["key"]] = WorkflowNode.objects.create(
            version=version,
            node_key=item["key"],
            node_type=item["type"],
            label=str(item.get("label", ""))[:120],
            position=item.get("position") if isinstance(item.get("position"), dict) else {},
            config=item.get("config") if isinstance(item.get("config"), dict) else {},
        )
    for index, item in enumerate(edges):
        WorkflowEdge.objects.create(
            version=version, source=node_models[item["source"]], target=node_models[item["target"]],
            order=max(0, int(item.get("order", index))),
            condition=item.get("condition") if isinstance(item.get("condition"), dict) else {},
        )
    return version


@transaction.atomic
def enable_version(*, version, actor):
    locked = WorkflowVersion.objects.select_for_update().select_related("template", "boss_account").get(pk=version.pk)
    if locked.status != WorkflowVersion.Status.DRAFT:
        raise ValidationError("只有草稿版本可以启用")
    nodes = [
        {"key": node.node_key, "type": node.node_type, "label": node.label, "position": node.position, "config": node.config}
        for node in locked.nodes.all()
    ]
    edges = [
        {"source": edge.source.node_key, "target": edge.target.node_key, "condition": edge.condition}
        for edge in locked.edges.select_related("source", "target")
    ]
    validate_graph(nodes=nodes, edges=edges, boss_account=locked.boss_account)
    WorkflowVersion.objects.filter(template=locked.template, status=WorkflowVersion.Status.ENABLED).update(
        status=WorkflowVersion.Status.DISABLED
    )
    locked.status = WorkflowVersion.Status.ENABLED
    locked.save(update_fields=["status"])
    locked.template.active_version = locked
    locked.template.save(update_fields=["active_version", "updated_at"])
    RecruitmentAuditLog.objects.create(
        actor=actor, boss_account=locked.boss_account, action="workflow_enabled", target_id=str(locked.pk),
        detail={"template_id": locked.template_id, "version": locked.version},
    )
    return locked

