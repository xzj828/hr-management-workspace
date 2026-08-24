from django.contrib.auth.models import User
from rest_framework.test import APITestCase

from attendance.models import AccountProfile
from recruitment.models import BossAccount
from recruitment.tests.test_workflow_service import SAFE_EDGES, SAFE_NODES


class WorkflowApiTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user("workflow-api")
        AccountProfile.objects.update_or_create(user=self.user, defaults={"role": AccountProfile.Role.HR})
        self.client.force_authenticate(self.user)
        self.account = BossAccount.objects.create(name="流程 API", browser_profile="workflow-api", cdp_port=53526)
        self.account.authorized_users.add(self.user)

    def test_create_and_enable_workflow(self):
        template = self.client.post("/api/recruitment/workflows/", {"name": "标准招聘"}, format="json")
        self.assertEqual(template.status_code, 201)
        version = self.client.post("/api/recruitment/workflow-versions/", {
            "template": template.data["id"],
            "boss_account": self.account.pk,
            "nodes": SAFE_NODES,
            "edges": SAFE_EDGES,
        }, format="json")
        self.assertEqual(version.status_code, 201)
        enabled = self.client.post(f"/api/recruitment/workflow-versions/{version.data['id']}/enable/")
        self.assertEqual(enabled.status_code, 200)
        self.assertEqual(enabled.data["status"], "enabled")

