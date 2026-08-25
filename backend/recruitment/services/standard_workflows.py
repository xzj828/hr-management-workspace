from django.db import transaction

from recruitment.models import WorkflowTemplate
from recruitment.services.workflows import create_version


STANDARD_SCHEMES = {
    "passive_resume": {
        "name": "被动咨询与简历获取",
        "description": "同步完整会话，识别观望消息并通过 BOSS 原生动作索要附件简历。",
    },
    "active_resume_search": {
        "name": "主动搜索并拉取简历",
        "description": "按职位搜索候选人，拉取在线简历并创建待人工打招呼任务。",
    },
}


def _node(key, node_type, label, x, config=None):
    return {
        "key": key,
        "type": node_type,
        "label": label,
        "position": {"x": x, "y": 120},
        "config": config or {},
    }


def _passive_graph(config):
    reply = str(config.get("reply_message", "您好，这边是招聘岗位，方便发送一份简历进一步沟通吗？"))[:1000]
    nodes = [
        _node("start", "start", "开始", 20),
        _node("sync", "sync_messages", "同步完整消息", 210),
        _node("intent", "classify_intent", "判断消息意图", 400),
        _node("request", "request_resume", "原生求简历", 590, {"message": reply}),
        _node("attention", "create_attention", "人工介入", 590, {"attention_type": "observing_candidate"}),
        _node("stop_rejected", "stop", "候选人拒绝，停止跟进", 780),
        _node("stop_observing", "stop", "已转人工，停止自动跟进", 780),
        _node("wait", "wait_resume", "等待简历", 780, {"wake_event": "resume.archived"}),
        _node("archive_existing", "archive_resume", "归档已有简历", 970),
        _node("archive_received", "archive_resume", "归档新简历", 970),
        _node("end_existing", "end", "已有简历流程结束", 1160),
        _node("end_received", "end", "求简历流程结束", 1160),
    ]
    edges = [
        {"source": "start", "target": "sync"},
        {"source": "sync", "target": "intent"},
        {"source": "intent", "target": "archive_existing", "condition": {"intent": "resume_received"}},
        {"source": "intent", "target": "stop_rejected", "condition": {"intent": "rejected"}},
        {"source": "intent", "target": "attention", "condition": {"intent": "observing"}},
        {"source": "intent", "target": "request", "condition": {"intent": "request_resume"}},
        {"source": "attention", "target": "stop_observing"},
        {"source": "request", "target": "wait"},
        {"source": "wait", "target": "archive_received"},
        {"source": "archive_existing", "target": "end_existing"},
        {"source": "archive_received", "target": "end_received"},
    ]
    return nodes, edges


def _active_graph(config):
    search_config = {
        "source": str(config.get("source", "search")),
        "keyword": str(config.get("keyword", ""))[:120],
        "core": list(config.get("core") or []),
        "bonus": list(config.get("bonus") or []),
        "target_resume_count": int(config.get("target_resume_count", 1)),
        "max_scan_count": int(config.get("max_scan_count", 20)),
    }
    nodes = [
        _node("start", "start", "开始", 40),
        _node("search_pull", "search_and_pull_resumes", "搜索并拉取简历", 300, search_config),
        _node("attention", "create_attention", "提醒人工打招呼", 650, {"attention_type": "greeting_required"}),
        _node("end", "end", "结束", 940),
    ]
    edges = [
        {"source": "start", "target": "search_pull"},
        {"source": "search_pull", "target": "attention"},
        {"source": "attention", "target": "end"},
    ]
    return nodes, edges


@transaction.atomic
def create_standard_workflow(*, kind, account, actor, config=None):
    if kind not in STANDARD_SCHEMES:
        raise ValueError("不支持的标准自动化方案")
    scheme = STANDARD_SCHEMES[kind]
    template = WorkflowTemplate.objects.create(
        name=scheme["name"],
        description=scheme["description"],
        created_by=actor,
    )
    nodes, edges = _passive_graph(config or {}) if kind == "passive_resume" else _active_graph(config or {})
    version = create_version(
        template=template,
        boss_account=account,
        nodes=nodes,
        edges=edges,
        actor=actor,
    )
    return template, version
