from django.contrib.auth.models import User
from django.test import TestCase

from attendance.models import AccountProfile
from recruitment.models import AutomationApproval, BossAccount, Candidate, HumanAttention, JobApplication, RecruitmentJob, RpaTask, WorkflowNodeRun, WorkflowRun, WorkflowTemplate
from recruitment.services.conversation_ingestion import ingest_conversation
from recruitment.services.workflow_nodes import execute_workflow_node, resume_workflow_for_task
from recruitment.services.workflow_runtime import advance_run, create_run, decide_node
from recruitment.services.workflows import create_version


class WorkflowNodeExecutionTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("node-executor")
        AccountProfile.objects.update_or_create(user=self.user, defaults={"role": AccountProfile.Role.HR})
        self.account = BossAccount.objects.create(name="node account", browser_profile="node-account", cdp_port=53903)
        self.account.authorized_users.add(self.user)
        self.job = RecruitmentJob.objects.create(boss_account=self.account, external_id="job", title="Vue", owner=self.user)
        template = WorkflowTemplate.objects.create(name="node graph", created_by=self.user)
        self.version = create_version(
            template=template, boss_account=self.account, actor=self.user,
            nodes=[
                {
                    "key": "source",
                    "type": "search",
                    "position": {},
                    "config": {"keyword": "Vue", "core": ["3 年经验"], "bonus": ["大厂经历"]},
                },
                {"key": "approval", "type": "human_approval", "position": {}, "config": {}},
                {"key": "greet", "type": "greet", "position": {}, "config": {"message": "您好，想和您沟通岗位。"}},
                {"key": "end", "type": "end", "position": {}, "config": {}},
            ],
            edges=[{"source": "source", "target": "approval"}, {"source": "approval", "target": "greet"}, {"source": "greet", "target": "end"}],
        )

    def test_dry_run_never_creates_rpa_or_approval_work(self):
        run = create_run(version=self.version, actor=self.user, mode=WorkflowRun.Mode.DRY_RUN, idempotency_key="node:dry", job=self.job)
        advance_run(run, executor=execute_workflow_node)
        self.assertEqual(RpaTask.objects.count(), 0)
        self.assertEqual(AutomationApproval.objects.count(), 0)

    def test_formal_source_creates_one_linked_task_and_completion_resumes(self):
        run = create_run(version=self.version, actor=self.user, mode=WorkflowRun.Mode.FORMAL, idempotency_key="node:formal", job=self.job)
        run = advance_run(run, executor=execute_workflow_node)
        task = RpaTask.objects.get()
        self.assertEqual(task.workflow_node_run.node_key, "source")
        self.assertEqual(task.request_payload["keyword"], "Vue")
        self.assertEqual(task.request_payload["core"], ["3 年经验"])
        self.assertEqual(task.request_payload["bonus"], ["大厂经历"])
        self.assertEqual(task.request_payload["job"], self.job.pk)
        self.assertEqual(task.request_payload["job_title"], self.job.title)
        self.assertEqual(run.node_runs.get(node_key="source").status, WorkflowNodeRun.Status.RUNNING)

        task.status = RpaTask.Status.SUCCEEDED
        task.result = {"sync": {"created": 2}}
        task.save(update_fields=["status", "result", "updated_at"])
        resume_workflow_for_task(task)
        run.refresh_from_db()
        self.assertEqual(run.status, WorkflowRun.Status.WAITING_HUMAN)
        self.assertEqual(RpaTask.objects.count(), 1)

    def test_communication_node_creates_draft_after_gate_not_direct_send(self):
        from recruitment.models import Candidate
        candidate = Candidate.objects.create(name="候选人", external_id="candidate")
        application = JobApplication.objects.create(candidate=candidate, job=self.job, owner=self.user)
        run = create_run(
            version=self.version, actor=self.user, mode=WorkflowRun.Mode.FORMAL,
            idempotency_key="node:message", job=self.job, input_snapshot={"application_ids": [application.pk]},
        )
        source = run.node_runs.get(node_key="source")
        source.status = WorkflowNodeRun.Status.SUCCEEDED
        source.save(update_fields=["status", "updated_at"])
        advance_run(run, executor=execute_workflow_node)
        gate = run.node_runs.get(node_key="approval")
        decide_node(gate, approved=True, actor=self.user)
        advance_run(run, executor=execute_workflow_node)

        approval = AutomationApproval.objects.get()
        self.assertEqual(approval.status, AutomationApproval.Status.DRAFT)
        self.assertEqual(run.node_runs.get(node_key="greet").status, WorkflowNodeRun.Status.WAITING_HUMAN)
        self.assertFalse(RpaTask.objects.filter(action=RpaTask.Action.GREET).exists())

    def _passive_version(self, include_request=True):
        template = WorkflowTemplate.objects.create(name=f"passive-{include_request}", created_by=self.user)
        nodes = [
            {"key": "sync", "type": "sync_messages", "position": {}, "config": {}},
            {"key": "intent", "type": "classify_intent", "position": {}, "config": {}},
        ]
        edges = [{"source": "sync", "target": "intent"}]
        if include_request:
            nodes.extend([
                {"key": "request", "type": "request_resume", "position": {}, "config": {"message": "请发送简历"}},
                {"key": "wait", "type": "wait_resume", "position": {}, "config": {"wake_event": "resume.archived"}},
            ])
            edges.extend([
                {"source": "intent", "target": "request", "condition": {"intent": "request_resume"}},
                {"source": "request", "target": "wait"},
            ])
        else:
            nodes.append({"key": "end", "type": "end", "position": {}, "config": {}})
            edges.append({"source": "intent", "target": "end"})
        return create_version(
            template=template, boss_account=self.account, actor=self.user, nodes=nodes, edges=edges,
        )

    def _candidate_message(self):
        candidate = Candidate.objects.create(identity_key=f"candidate-{self._testMethodName}", external_id="boss-1", name="程青")
        application = JobApplication.objects.create(candidate=candidate, job=self.job, owner=self.user, source="boss")
        ingest_conversation(
            application=application, account=self.account,
            messages=[{"external_id": self._testMethodName, "direction": "candidate", "content": "你好", "sent_at": "2026-08-25T09:00:00+08:00"}],
        )
        return application

    def test_passive_canvas_request_node_queues_native_resume_action(self):
        self._candidate_message()
        run = create_run(
            version=self._passive_version(True), actor=self.user, mode=WorkflowRun.Mode.FORMAL,
            idempotency_key="passive-with-request", job=self.job,
        )
        sync = run.node_runs.get(node_key="sync")
        sync.status = WorkflowNodeRun.Status.SUCCEEDED
        sync.save(update_fields=["status", "updated_at"])
        advance_run(run, executor=execute_workflow_node)

        task = RpaTask.objects.get(action=RpaTask.Action.REQUEST_RESUME)
        self.assertEqual(task.request_payload["message"], "请发送简历")
        self.assertEqual(run.node_runs.get(node_key="wait").status, WorkflowNodeRun.Status.WAITING_HUMAN)

    def test_deleting_request_node_from_canvas_prevents_resume_action(self):
        self._candidate_message()
        run = create_run(
            version=self._passive_version(False), actor=self.user, mode=WorkflowRun.Mode.FORMAL,
            idempotency_key="passive-without-request", job=self.job,
        )
        sync = run.node_runs.get(node_key="sync")
        sync.status = WorkflowNodeRun.Status.SUCCEEDED
        sync.save(update_fields=["status", "updated_at"])
        advance_run(run, executor=execute_workflow_node)

        self.assertFalse(RpaTask.objects.filter(action=RpaTask.Action.REQUEST_RESUME).exists())
        run.refresh_from_db()
        self.assertEqual(run.status, WorkflowRun.Status.SUCCEEDED)

    def test_observing_branch_creates_attention_only_when_node_exists(self):
        candidate = Candidate.objects.create(identity_key="observing-candidate", external_id="boss-observe", name="许知")
        application = JobApplication.objects.create(candidate=candidate, job=self.job, owner=self.user, source="boss")
        ingest_conversation(
            application=application, account=self.account,
            messages=[{"external_id": "observing-message", "direction": "candidate", "content": "我想先了解一下公司", "sent_at": "2026-08-25T09:00:00+08:00"}],
        )
        template = WorkflowTemplate.objects.create(name="observation branch", created_by=self.user)
        version = create_version(
            template=template, boss_account=self.account, actor=self.user,
            nodes=[
                {"key": "sync", "type": "sync_messages", "position": {}, "config": {}},
                {"key": "intent", "type": "classify_intent", "position": {}, "config": {}},
                {"key": "attention", "type": "create_attention", "position": {}, "config": {"attention_type": "observing_candidate"}},
                {"key": "end", "type": "end", "position": {}, "config": {}},
            ],
            edges=[
                {"source": "sync", "target": "intent"},
                {"source": "intent", "target": "attention", "condition": {"intent": "observing"}},
                {"source": "attention", "target": "end"},
            ],
        )
        run = create_run(version=version, actor=self.user, mode=WorkflowRun.Mode.FORMAL, idempotency_key="observing-run", job=self.job)
        run.node_runs.filter(node_key="sync").update(status=WorkflowNodeRun.Status.SUCCEEDED)
        advance_run(run, executor=execute_workflow_node)

        attention = HumanAttention.objects.get()
        self.assertEqual(attention.application, application)
        self.assertEqual(attention.attention_type, HumanAttention.Type.OBSERVING_CANDIDATE)
        self.assertFalse(RpaTask.objects.filter(action=RpaTask.Action.REQUEST_RESUME).exists())
