from datetime import timedelta

from django.utils import timezone

from recruitment.models import (
    AutomationApproval,
    ExecutionBatch,
    JobApplication,
    RpaTask,
    Resume,
    SearchCampaign,
    WorkflowNodeRun,
    WorkflowRun,
)
from recruitment.rpa.tasks import create_task
from recruitment.services.communications import prepare_communication
from recruitment.services.search_campaigns import prepare_search_campaign
from recruitment.services.conversation_ingestion import process_pending_messages
from recruitment.services.human_attention import ensure_attention


SOURCE_ACTIONS = {
    "recommend": RpaTask.Action.RECOMMEND_CANDIDATES,
    "search": RpaTask.Action.SEARCH_CANDIDATES,
    "sync_messages": RpaTask.Action.SYNC_CONVERSATIONS,
}
MESSAGE_ACTIONS = {"greet": "greet", "request_resume": "request_resume", "send_interview": "send_interview"}


def _task_outcome(task):
    if task.status == RpaTask.Status.SUCCEEDED:
        return WorkflowNodeRun.Status.SUCCEEDED, {"task_id": str(task.pk), "result": task.result}
    if task.status == RpaTask.Status.FAILED:
        return WorkflowNodeRun.Status.FAILED, {"task_id": str(task.pk), "error": task.error_message}
    if task.status == RpaTask.Status.WAITING_HUMAN:
        return WorkflowNodeRun.Status.WAITING_HUMAN, {"task_id": str(task.pk), "reason": task.error_code or task.status}
    if task.status == RpaTask.Status.CANCELLED:
        return WorkflowNodeRun.Status.CANCELLED, {"task_id": str(task.pk), "reason": task.error_code or task.status}
    return WorkflowNodeRun.Status.RUNNING, {"task_id": str(task.pk)}


def _parent_outputs(node):
    parents = []
    for edge in node.run.graph_snapshot.get("edges", []):
        if edge.get("target") == node.node_key:
            parent = node.run.node_runs.filter(node_key=edge.get("source")).first()
            if parent:
                parents.append(parent.output or {})
    return parents


def _application_ids_for_intent(node, intent=None):
    values = []
    for candidate_node in node.run.node_runs.all():
        output = candidate_node.output or {}
        if intent:
            values.extend((output.get("applications_by_intent") or {}).get(intent, []))
        values.extend(output.get("application_ids", []))
        values.extend((output.get("result") or {}).get("application_ids", []))
        resume_id = output.get("resume_id")
        if resume_id:
            application_id = Resume.objects.filter(pk=resume_id).values_list("application_id", flat=True).first()
            if application_id:
                values.append(application_id)
    return list(dict.fromkeys(int(value) for value in values if str(value).isdigit()))


def execute_workflow_node(node):
    run = node.run
    if run.mode == WorkflowRun.Mode.DRY_RUN:
        return WorkflowNodeRun.Status.SUCCEEDED, {"simulated": True}

    if node.node_type == "deep_search":
        config = node.config_snapshot
        criteria = config.get("criteria") if isinstance(config.get("criteria"), dict) else {}
        payload = {
            "job": run.job_id or run.input_snapshot.get("job"),
            "job_title": run.job.title if run.job_id else str(run.input_snapshot.get("job_title", "")),
            "core": config.get("core", criteria.get("core", [])),
            "bonus": config.get("bonus", criteria.get("bonus", [])),
            "request_id": f"workflow-{node.pk}-{node.attempt}",
            "estimated_consumption": 1,
            "workflow_node_run_id": node.pk,
            "workflow_node_attempt": node.attempt,
        }
        approval_key = f"workflow-deep-match:{node.pk}:{node.attempt}"
        approval_id = (node.output or {}).get("approval_id")
        approval = (
            AutomationApproval.objects.filter(pk=approval_id, idempotency_key=approval_key).first()
            if approval_id
            else AutomationApproval.objects.filter(idempotency_key=approval_key).first()
        )
        task = (
            RpaTask.objects.filter(workflow_node_run=node, approval=approval).first()
            if approval is not None
            else None
        )
        if task is not None:
            return _task_outcome(task)
        if approval is not None and approval.status == AutomationApproval.Status.REJECTED:
            return WorkflowNodeRun.Status.SKIPPED, {
                "approval_id": str(approval.pk),
                "approved": False,
            }
        if approval is None:
            approval, _ = AutomationApproval.objects.get_or_create(
                idempotency_key=approval_key,
                defaults={
                    "action": AutomationApproval.Action.DEEP_MATCH,
                    "boss_account": run.boss_account,
                    "created_by": run.actor,
                    "payload": payload,
                    "item_count": 1,
                    "expires_at": timezone.now() + timedelta(minutes=15),
                },
            )
        return WorkflowNodeRun.Status.WAITING_HUMAN, {
            "approval_id": str(approval.pk),
            "estimated_consumption": approval.item_count,
        }

    if node.node_type in SOURCE_ACTIONS:
        task_key = f"workflow-task:{node.pk}:{node.attempt}"
        task = RpaTask.objects.filter(workflow_node_run=node, idempotency_key=task_key).first()
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
                "workflow_managed": node.node_type == "sync_messages",
            }
            task = create_task(
                account=run.boss_account, action=SOURCE_ACTIONS[node.node_type], actor=run.actor,
                request_payload=payload, workflow_node_run=node,
                idempotency_key=task_key,
            )
        return _task_outcome(task)

    if node.node_type == "classify_intent":
        applications = JobApplication.objects.filter(
            job=run.job, job__boss_account=run.boss_account,
        ).select_related("candidate", "job")
        grouped = {}
        messages = {}
        for application in applications:
            decision = process_pending_messages(
                application=application, account=run.boss_account, actor=run.actor,
                schedule_actions=False, create_attentions=False,
            )
            intent = str(decision.intent)
            if intent == "ignore":
                continue
            grouped.setdefault(intent, []).append(application.pk)
            if decision.message:
                messages[str(application.pk)] = decision.message.pk
        return WorkflowNodeRun.Status.SUCCEEDED, {
            "intent": list(grouped), "applications_by_intent": grouped, "message_ids": messages,
        }

    if node.node_type == "create_attention":
        attention_type = str(node.config_snapshot.get("attention_type", "other"))
        intent = "observing" if attention_type == "observing_candidate" else None
        application_ids = _application_ids_for_intent(node, intent)
        for application in JobApplication.objects.filter(pk__in=application_ids).select_related("candidate", "job"):
            ensure_attention(
                attention_type=attention_type,
                title=(f"{application.candidate.name} 希望进一步了解公司或岗位" if intent else f"请 HR 处理 {application.candidate.name}"),
                idempotency_key=f"workflow-attention:{node.pk}:{application.pk}",
                account=run.boss_account, job=application.job, application=application,
                workflow_run=run, workflow_node_run=node, detail={"source": "workflow"}, priority=10,
            )
        return WorkflowNodeRun.Status.SUCCEEDED, {"application_ids": application_ids, "created": len(application_ids)}

    if node.node_type == "archive_resume":
        application_ids = _application_ids_for_intent(node, "resume_received")
        archived = JobApplication.objects.filter(pk__in=application_ids, resumes__archived_at__isnull=True).distinct().count()
        return WorkflowNodeRun.Status.SUCCEEDED, {"application_ids": application_ids, "archived": archived}

    if node.node_type == "search_and_pull_resumes":
        task = RpaTask.objects.filter(workflow_node_run=node).order_by("-created_at").first()
        if task is not None:
            return _task_outcome(task)
        campaign_id = node.output.get("campaign_id")
        campaign = SearchCampaign.objects.filter(pk=campaign_id, workflow_run=run).first()
        if campaign is None:
            config = node.config_snapshot
            criteria = {
                "keyword": str(config.get("keyword", "")),
                "core": config.get("core") if isinstance(config.get("core"), list) else [],
                "bonus": config.get("bonus") if isinstance(config.get("bonus"), list) else [],
                "workflow_node_id": node.pk,
            }
            campaign = SearchCampaign.objects.create(
                name=f"{run.job.title if run.job_id else '职位'}主动寻访",
                boss_account=run.boss_account,
                job=run.job,
                workflow_run=run,
                source=str(config.get("source", "search")),
                target_resume_count=int(config.get("target_resume_count", 1)),
                max_scan_count=int(config.get("max_scan_count", 20)),
                criteria=criteria,
                created_by=run.actor,
            )
        approval_id = node.output.get("approval_id")
        approval = AutomationApproval.objects.filter(pk=approval_id).first() if approval_id else None
        if approval is not None and approval.status == AutomationApproval.Status.REJECTED:
            return WorkflowNodeRun.Status.SKIPPED, {
                "campaign_id": campaign.pk,
                "approval_id": str(approval.pk),
                "approved": False,
            }
        if approval is None:
            approval = prepare_search_campaign(
                campaign=campaign,
                actor=run.actor,
                workflow_node_run=node,
            )
        return WorkflowNodeRun.Status.WAITING_HUMAN, {
            "campaign_id": campaign.pk,
            "approval_id": str(approval.pk),
            "resume_view_budget": approval.item_count,
        }

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
                if batch.status in {ExecutionBatch.Status.PENDING, ExecutionBatch.Status.RUNNING}:
                    return WorkflowNodeRun.Status.RUNNING, {"approval_id": approval_id, "batch_id": str(batch.pk)}
            return WorkflowNodeRun.Status.WAITING_HUMAN, {"approval_id": approval_id}

        application_ids = (
            _application_ids_for_intent(node, "request_resume")
            if node.node_type == "request_resume"
            else run.input_snapshot.get("application_ids", [])
        )
        applications = JobApplication.objects.filter(pk__in=application_ids).select_related("candidate", "job")
        message = node.config_snapshot.get("message") or {
            "greet": "您好，我们正在招聘相关岗位，想和您进一步沟通。",
            "request_resume": "方便发送一份 PDF 简历吗？",
            "send_interview": "诚邀您参加面试，请确认时间安排。",
        }[node.node_type]
        item_contexts = None
        if node.node_type == "request_resume":
            message_ids = {}
            for candidate_node in run.node_runs.all():
                message_ids.update((candidate_node.output or {}).get("message_ids") or {})
            item_contexts = {
                application.pk: {
                    "first_contact": not application.conversation_state.messages.filter(direction="hr").exists(),
                    "source_message_id": message_ids.get(str(application.pk)),
                }
                for application in applications
            }
        approval = prepare_communication(
            account=run.boss_account, applications=applications, action=MESSAGE_ACTIONS[node.node_type],
            message=message, actor=run.actor, request_id=f"workflow-{node.pk}-{node.attempt}",
            invitation=node.config_snapshot.get("invitation"), item_contexts=item_contexts,
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
    node.completed_at = task.completed_at if status in {
        WorkflowNodeRun.Status.SUCCEEDED,
        WorkflowNodeRun.Status.FAILED,
        WorkflowNodeRun.Status.CANCELLED,
    } else None
    node.save(update_fields=["status", "output", "error_code", "error_message", "completed_at", "updated_at"])
    from recruitment.services.workflow_runtime import advance_run
    return advance_run(node.run, executor=execute_workflow_node)
