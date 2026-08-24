from django.contrib.auth.models import User
from django.db import IntegrityError, transaction
from django.test import TestCase

from recruitment.models import (
    BossAccount,
    WorkflowEdge,
    WorkflowNode,
    WorkflowNodeRun,
    WorkflowRun,
    WorkflowRunEvent,
    WorkflowTemplate,
    WorkflowVersion,
)


class WorkflowRuntimeModelTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("runtime-models")
        self.account = BossAccount.objects.create(name="runtime", browser_profile="runtime", cdp_port=53901)
        self.template = WorkflowTemplate.objects.create(name="standard", created_by=self.user)
        self.version = WorkflowVersion.objects.create(
            template=self.template, version=1, status=WorkflowVersion.Status.ENABLED,
            boss_account=self.account, created_by=self.user,
        )
        self.source = WorkflowNode.objects.create(version=self.version, node_key="source", node_type="search", position={})
        self.target = WorkflowNode.objects.create(version=self.version, node_key="end", node_type="end", position={})

    def test_edge_order_and_run_snapshots_are_persisted(self):
        edge = WorkflowEdge.objects.create(version=self.version, source=self.source, target=self.target, order=3)
        run = WorkflowRun.objects.create(
            version=self.version, boss_account=self.account, actor=self.user, mode=WorkflowRun.Mode.DRY_RUN,
            idempotency_key="run:one", graph_snapshot={"nodes": [{"key": "source"}]}, input_snapshot={"job": 2},
        )
        node = WorkflowNodeRun.objects.create(
            run=run, node_key="source", node_type="search", status=WorkflowNodeRun.Status.READY,
            config_snapshot={"keyword": "Vue"}, idempotency_key="run:one:source",
        )
        event = WorkflowRunEvent.objects.create(run=run, node_run=node, event="node.ready", message="ready", data={"edge": edge.pk})

        self.assertEqual(edge.order, 3)
        self.assertEqual(run.graph_snapshot["nodes"][0]["key"], "source")
        self.assertEqual(node.attempt, 0)
        self.assertEqual(event.data["edge"], edge.pk)

    def test_node_keys_and_idempotency_are_unique(self):
        run = WorkflowRun.objects.create(
            version=self.version, boss_account=self.account, actor=self.user,
            idempotency_key="run:unique", graph_snapshot={}, input_snapshot={},
        )
        WorkflowNodeRun.objects.create(run=run, node_key="source", node_type="search", idempotency_key="node:unique")
        with self.assertRaises(IntegrityError), transaction.atomic():
            WorkflowNodeRun.objects.create(run=run, node_key="source", node_type="search", idempotency_key="node:other")

    def test_runtime_status_choices_include_controls_and_terminal_states(self):
        self.assertTrue({"queued", "running", "waiting_human", "paused", "succeeded", "failed", "cancelled"}.issubset(dict(WorkflowRun.Status.choices)))
        self.assertTrue({"blocked", "ready", "running", "waiting_human", "succeeded", "failed", "skipped", "cancelled"}.issubset(dict(WorkflowNodeRun.Status.choices)))

