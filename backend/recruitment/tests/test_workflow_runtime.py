from django.contrib.auth.models import User
from django.test import TestCase

from recruitment.models import BossAccount, WorkflowNodeRun, WorkflowRun, WorkflowTemplate
from recruitment.services.workflow_runtime import (
    advance_run,
    cancel_run,
    create_run,
    decide_node,
    pause_run,
    resume_run,
    retry_node,
)
from recruitment.services.workflows import create_version


class WorkflowRuntimeTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("runtime")
        self.account = BossAccount.objects.create(name="runtime-service", browser_profile="runtime-service", cdp_port=53902)
        template = WorkflowTemplate.objects.create(name="runtime graph", created_by=self.user)
        self.version = create_version(
            template=template, boss_account=self.account, actor=self.user,
            nodes=[
                {"key": "source", "type": "search", "position": {}, "config": {}},
                {"key": "screen", "type": "human_screen", "position": {}, "config": {}},
                {"key": "disabled", "type": "import_candidate", "position": {}, "config": {"enabled": False}},
                {"key": "end", "type": "end", "position": {}, "config": {}},
            ],
            edges=[
                {"source": "source", "target": "screen", "order": 2},
                {"source": "source", "target": "disabled", "order": 1},
                {"source": "screen", "target": "end", "order": 1},
                {"source": "disabled", "target": "end", "order": 0},
            ],
        )

    def test_dry_run_uses_snapshot_stable_edges_and_waits_at_human_gate(self):
        run = create_run(version=self.version, actor=self.user, mode=WorkflowRun.Mode.DRY_RUN, idempotency_key="dry:1")
        run = advance_run(run)
        run.refresh_from_db()
        self.assertEqual([edge["order"] for edge in run.graph_snapshot["edges"]], [0, 1, 1, 2])
        self.assertEqual(run.status, WorkflowRun.Status.WAITING_HUMAN)
        self.assertEqual(run.node_runs.get(node_key="source").status, WorkflowNodeRun.Status.SUCCEEDED)
        self.assertEqual(run.node_runs.get(node_key="disabled").status, WorkflowNodeRun.Status.SKIPPED)
        self.assertEqual(run.node_runs.get(node_key="end").status, WorkflowNodeRun.Status.BLOCKED)

        decide_node(run.node_runs.get(node_key="screen"), approved=True, actor=self.user, note="looks good")
        run = advance_run(run)
        self.assertEqual(run.status, WorkflowRun.Status.SUCCEEDED)
        self.assertEqual(run.node_runs.get(node_key="end").status, WorkflowNodeRun.Status.SUCCEEDED)

    def test_creation_and_advancement_are_idempotent(self):
        first = create_run(version=self.version, actor=self.user, mode=WorkflowRun.Mode.DRY_RUN, idempotency_key="dry:same")
        second = create_run(version=self.version, actor=self.user, mode=WorkflowRun.Mode.DRY_RUN, idempotency_key="dry:same")
        self.assertEqual(first.pk, second.pk)
        advance_run(first)
        event_count = first.events.count()
        advance_run(first)
        self.assertEqual(first.events.count(), event_count)

    def test_pause_resume_cancel_and_retry_are_controlled(self):
        run = create_run(version=self.version, actor=self.user, mode=WorkflowRun.Mode.FORMAL, idempotency_key="formal:1")
        pause_run(run, actor=self.user)
        run.refresh_from_db(); self.assertEqual(run.status, WorkflowRun.Status.PAUSED)
        resume_run(run, actor=self.user)
        run.refresh_from_db(); self.assertEqual(run.status, WorkflowRun.Status.RUNNING)

        node = run.node_runs.get(node_key="source")
        node.status = WorkflowNodeRun.Status.FAILED
        node.error_code = "temporary"
        node.save(update_fields=["status", "error_code", "updated_at"])
        retry_node(node, actor=self.user)
        node.refresh_from_db()
        self.assertEqual(node.status, WorkflowNodeRun.Status.READY)
        self.assertEqual(node.attempt, 1)

        cancel_run(run, actor=self.user)
        run.refresh_from_db(); self.assertEqual(run.status, WorkflowRun.Status.CANCELLED)
        self.assertFalse(run.node_runs.filter(status__in=[WorkflowNodeRun.Status.READY, WorkflowNodeRun.Status.BLOCKED]).exists())

    def test_conditional_edges_execute_only_the_matching_branch(self):
        template = WorkflowTemplate.objects.create(name="conditional graph", created_by=self.user)
        version = create_version(
            template=template,
            boss_account=self.account,
            actor=self.user,
            nodes=[
                {"key": "source", "type": "search", "position": {}, "config": {}},
                {"key": "accepted", "type": "end", "position": {}, "config": {}},
                {"key": "rejected", "type": "end", "position": {}, "config": {}},
            ],
            edges=[
                {"source": "source", "target": "accepted", "condition": {"intent": "accepted"}},
                {"source": "source", "target": "rejected", "condition": {"intent": "rejected"}},
            ],
        )
        run = create_run(
            version=version,
            actor=self.user,
            mode=WorkflowRun.Mode.FORMAL,
            idempotency_key="conditional:1",
        )

        def executor(node):
            if node.node_key == "source":
                return WorkflowNodeRun.Status.SUCCEEDED, {"intent": "accepted"}
            return WorkflowNodeRun.Status.SUCCEEDED, {}

        run = advance_run(run, executor=executor)

        self.assertEqual(run.status, WorkflowRun.Status.SUCCEEDED)
        self.assertEqual(run.node_runs.get(node_key="accepted").status, WorkflowNodeRun.Status.SUCCEEDED)
        self.assertEqual(run.node_runs.get(node_key="rejected").status, WorkflowNodeRun.Status.SKIPPED)
