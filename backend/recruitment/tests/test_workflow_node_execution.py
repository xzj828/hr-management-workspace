from django.contrib.auth.models import User
from django.test import TestCase

from attendance.models import AccountProfile
from recruitment.models import AutomationApproval, BossAccount, JobApplication, RecruitmentJob, RpaTask, WorkflowNodeRun, WorkflowRun, WorkflowTemplate
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
                {"key": "source", "type": "search", "position": {}, "config": {}},
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

