from django.contrib.auth.models import User
from django.test import TestCase
from rest_framework.exceptions import ValidationError
from rest_framework.test import APITestCase

from attendance.models import AccountProfile
from recruitment.models import BossAccount, WorkflowTemplate
from recruitment.services.standard_workflows import create_standard_workflow
from recruitment.services.workflows import validate_graph


class StandardWorkflowTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("standard-workflow-hr")
        self.account = BossAccount.objects.create(
            name="标准方案账号",
            browser_profile="standard-workflow",
            cdp_port=53994,
        )

    def test_passive_scheme_compiles_to_an_editable_ordinary_version(self):
        template, version = create_standard_workflow(
            kind="passive_resume",
            account=self.account,
            actor=self.user,
            config={"reply_message": "您好，方便发送一份简历吗？"},
        )

        self.assertIsInstance(template, WorkflowTemplate)
        self.assertEqual(version.template, template)
        self.assertEqual(
            set(version.nodes.values_list("node_type", flat=True)),
            {
                "start", "sync_messages", "classify_intent", "request_resume",
                "create_attention", "stop", "wait_resume", "archive_resume", "human_approval", "end",
            },
        )
        self.assertGreater(version.edges.count(), 0)
        self.assertTrue(
            any(edge.condition for edge in version.edges.filter(source__node_type="classify_intent"))
        )

    def test_active_scheme_contains_one_search_and_pull_business_step(self):
        _, version = create_standard_workflow(
            kind="active_resume_search",
            account=self.account,
            actor=self.user,
            config={"target_resume_count": 3, "max_scan_count": 20, "source": "search"},
        )

        business = version.nodes.get(node_type="search_and_pull_resumes")
        self.assertEqual(business.config["target_resume_count"], 3)
        self.assertEqual(business.config["max_scan_count"], 20)
        self.assertTrue(version.nodes.filter(node_type="create_attention").exists())

    def test_validation_rejects_disconnected_and_unconfigured_wait_nodes(self):
        nodes = [
            {"key": "start", "type": "start", "config": {}},
            {"key": "wait", "type": "wait_resume", "config": {}},
            {"key": "end", "type": "end", "config": {}},
        ]
        with self.assertRaisesMessage(ValidationError, "唤醒事件"):
            validate_graph(
                nodes=nodes,
                edges=[{"source": "start", "target": "wait"}, {"source": "wait", "target": "end"}],
                boss_account=self.account,
            )

        with self.assertRaisesMessage(ValidationError, "未连接"):
            validate_graph(
                nodes=[
                    {"key": "source", "type": "search", "config": {}},
                    {"key": "end", "type": "end", "config": {}},
                ],
                edges=[],
                boss_account=self.account,
            )


class StandardWorkflowApiTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user("standard-api-hr")
        AccountProfile.objects.create(user=self.user, role=AccountProfile.Role.HR)
        self.account = BossAccount.objects.create(
            name="标准 API 账号",
            browser_profile="standard-api-workflow",
            cdp_port=53995,
        )
        self.account.authorized_users.add(self.user)
        self.client.force_login(self.user)

    def test_creates_standard_scheme_through_regular_workflow_api(self):
        response = self.client.post(
            "/api/recruitment/workflows/standard/",
            {
                "kind": "active_resume_search",
                "boss_account": self.account.pk,
                "config": {"source": "search", "target_resume_count": 2, "max_scan_count": 10},
            },
            format="json",
        )

        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data["template"]["name"], "主动搜索并拉取简历")
        self.assertTrue(
            any(node["type"] == "search_and_pull_resumes" for node in response.data["version"]["nodes"])
        )
