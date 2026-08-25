from recruitment.models import (
    AutomationApproval,
    ExecutionBatch,
    JobApplication,
    RpaTask,
    WorkflowNodeRun,
    WorkflowRun,
)
from recruitment.rpa.tasks import create_task
from recruitment.services.communications import prepare_communication


SOURCE_ACTIONS = {
    "recommend": RpaTask.Action.RECOMMEND_CANDIDATES,
    "search": RpaTask.Action.SEARCH_CANDIDATES,
    "deep_search": RpaTask.Action.DEEP_MATCH,
}
MESSAGE_ACTIONS = {"greet": "greet", "request_resume": "request_resume", "send_interview": "send_interview"}


def _task_outcome(task):
    if task.status == RpaTask.Status.SUCCEEDED:
        return WorkflowNodeRun.Status.SUCCEEDED, {"task_id": str(task.pk), "result": task.result}
    if task.status == RpaTask.Status.FAILED:
        return WorkflowNodeRun.Status.FAILED, {"task_id": str(task.pk), "error": task.error_message}
    if task.status in {RpaTask.Status.WAITING_HUMAN, RpaTask.Status.CANCELLED}:
        return WorkflowNodeRun.Status.WAITING_HUMAN, {"task_id": str(task.pk), "reason": task.error_code or task.status}
    return WorkflowNodeRun.Status.RUNNING, {"task_id": str(task.pk)}


def execute_workflow_node(node):
    run = node.run
    if run.mode == WorkflowRun.Mode.DRY_RUN:
        return WorkflowNodeRun.Status.SUCCEEDED, {"simulated": True}

    if node.node_type in SOURCE_ACTIONS:
        task = RpaTask.objects.filter(workflow_node_run=node).first()
        if task is None:
            job_id = run.job_id or run.input_snapshot.get("job")
            criteria = node.config_snapshot.get("criteria") if isinstance(node.config_snapshot.get("criteria"), dict) else {}
            job_title = run.job.title if run.job_id else str(run.input_snapshot.get("job_title", ""))
            payload = {
                "job": job_id,
                "job_title": job_title,
                "keyword": str(node.config_snapshot.get("keyword", criteria.get("keyword", ""))),
                "core": node.config_snapshot.get("core", criteria.get("core", [])),
                "bonus": node.config_snapshot.get("bonus", criteria.get("bonus", [])),
                "criteria": criteria,
            }
            task = create_task(
                account=run.boss_account, action=SOURCE_ACTIONS[node.node_type], actor=run.actor,
                request_payload=payload, workflow_node_run=node,
                idempotency_key=f"workflow-task:{node.pk}:{node.attempt}",
            )
        return _task_outcome(task)

    if node.node_type in MESSAGE_ACTIONS:
        approval_id = node.output.get("approval_id")
        if approval_id:
            approval = AutomationApproval.objects.filter(pk=approval_id).first()
            if approval is None or approval.status == AutomationApproval.Status.REJECTED:
                return WorkflowNodeRun.Status.SKIPPED, {"approval_id": approval_id, "approved": False}
            batch = ExecutionBatch.objects.filter(workflow_node_run=node).first()
            if batch:
                if batch.status == ExecutionBatch.Status.SUCCEEDED:
                    return WorkflowNodeRun.Status.SUCCEEDED, {"approval_id": approval_id, "batch_id": str(batch.pk)}
                if batch.status in {ExecutionBatch.Status.FAILED, ExecutionBatch.Status.PARTIAL}:
                    return WorkflowNodeRun.Status.FAILED, {"approval_id": approval_id, "batch_id": str(batch.pk)}
            return WorkflowNodeRun.Status.WAITING_HUMAN, {"approval_id": approval_id}

        application_ids = run.input_snapshot.get("application_ids", [])
        applications = JobApplication.objects.filter(pk__in=application_ids).select_related("candidate", "job")
        message = node.config_snapshot.get("message") or {
            "greet": "您好，我们正在招聘相关岗位，想和您进一步沟通。",
            "request_resume": "方便发送一份 PDF 简历吗？",
            "send_interview": "诚邀您参加面试，请确认时间安排。",
        }[node.node_type]
        approval = prepare_communication(
            account=run.boss_account, applications=applications, action=MESSAGE_ACTIONS[node.node_type],
            message=message, actor=run.actor, request_id=f"workflow-{node.pk}-{node.attempt}",
            invitation=node.config_snapshot.get("invitation"),
        )
        approval.payload["workflow_node_run_id"] = node.pk
        approval.save(update_fields=["payload"])
        return WorkflowNodeRun.Status.WAITING_HUMAN, {"approval_id": str(approval.pk)}

    if node.node_type in {"wait_reply", "wait_resume"}:
        return WorkflowNodeRun.Status.WAITING_HUMAN, {"reason": "waiting_external_event"}
    return WorkflowNodeRun.Status.SUCCEEDED, {"internal": True}


def resume_workflow_for_task(task):
    if not task.workflow_node_run_id:
        return None
    node = WorkflowNodeRun.objects.select_related("run").get(pk=task.workflow_node_run_id)
    status, output = _task_outcome(task)
    node.status = status
    node.output = output
    node.error_code = task.error_code
    node.error_message = task.error_message
    node.completed_at = task.completed_at if status in {WorkflowNodeRun.Status.SUCCEEDED, WorkflowNodeRun.Status.FAILED} else None
    node.save(update_fields=["status", "output", "error_code", "error_message", "completed_at", "updated_at"])
    from recruitment.services.workflow_runtime import advance_run
    return advance_run(node.run, executor=execute_workflow_node)
