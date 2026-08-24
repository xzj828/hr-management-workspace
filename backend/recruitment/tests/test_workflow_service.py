from django.contrib.auth.models import User
from django.test import TestCase
from rest_framework.exceptions import ValidationError

from recruitment.models import BossAccount, WorkflowTemplate, WorkflowVersion
from recruitment.services.workflows import create_version, enable_version, validate_graph


SAFE_NODES = [
    {"key": "source", "type": "search", "label": "常规搜索", "position": {"x": 20, "y": 40}},
    {"key": "select", "type": "human_screen", "label": "人工筛选", "position": {"x": 220, "y": 40}},
    {"key": "approve", "type": "human_approval", "label": "人工确认", "position": {"x": 420, "y": 40}},
    {"key": "greet", "type": "greet", "label": "打招呼", "position": {"x": 620, "y": 40}},
    {"key": "end", "type": "end", "label": "结束", "position": {"x": 820, "y": 40}},
]
SAFE_EDGES = [
    {"source": "source", "target": "select"},
    {"source": "select", "target": "approve"},
    {"source": "approve", "target": "greet"},
    {"source": "greet", "target": "end"},
]


class WorkflowServiceTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("workflow-hr")
        self.account = BossAccount.objects.create(name="流程账号", browser_profile="workflow", cdp_port=53525)
        self.template = WorkflowTemplate.objects.create(name="标准招聘", created_by=self.user)

    def test_safe_graph_is_accepted_and_enabled_version_is_immutable(self):
        validate_graph(nodes=SAFE_NODES, edges=SAFE_EDGES, boss_account=self.account)
        version = create_version(
            template=self.template, boss_account=self.account, nodes=SAFE_NODES, edges=SAFE_EDGES, actor=self.user
        )
        enable_version(version=version, actor=self.user)
        version.refresh_from_db()
        self.template.refresh_from_db()
        self.assertEqual(version.status, WorkflowVersion.Status.ENABLED)
        self.assertEqual(self.template.active_version, version)

    def test_cycle_arbitrary_node_and_unconfirmed_send_are_rejected(self):
        with self.assertRaises(ValidationError):
            validate_graph(nodes=SAFE_NODES, edges=SAFE_EDGES + [{"source": "end", "target": "source"}], boss_account=self.account)
        with self.assertRaises(ValidationError):
            validate_graph(nodes=SAFE_NODES + [{"key": "script", "type": "script"}], edges=SAFE_EDGES, boss_account=self.account)
        without_approval = [edge for edge in SAFE_EDGES if edge["source"] != "approve" and edge["target"] != "approve"]
        without_approval.append({"source": "select", "target": "greet"})
        with self.assertRaises(ValidationError):
            validate_graph(nodes=[node for node in SAFE_NODES if node["key"] != "approve"], edges=without_approval, boss_account=self.account)

    def test_automation_graph_requires_account_and_source(self):
        with self.assertRaises(ValidationError):
            validate_graph(nodes=SAFE_NODES, edges=SAFE_EDGES, boss_account=None)
        with self.assertRaises(ValidationError):
            validate_graph(nodes=SAFE_NODES[1:], edges=SAFE_EDGES[1:], boss_account=self.account)

