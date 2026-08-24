from django.contrib.auth.models import User
from rest_framework.test import APITestCase

from attendance.models import AccountProfile
from recruitment.models import BossAccount, WorkflowRun, WorkflowTemplate
from recruitment.services.workflows import create_version, enable_version


class WorkflowRunApiTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user("run-api")
        AccountProfile.objects.create(user=self.user, role=AccountProfile.Role.HR)
        self.other = User.objects.create_user("run-api-other")
        AccountProfile.objects.create(user=self.other, role=AccountProfile.Role.HR)
        self.account = BossAccount.objects.create(
            name="run-api", browser_profile="run-api", cdp_port=53904,
            login_status=BossAccount.LoginStatus.READY, status=BossAccount.Status.READY,
        )
        self.account.authorized_users.add(self.user)
        template = WorkflowTemplate.objects.create(name="API run", created_by=self.user)
        self.version = create_version(
            template=template, boss_account=self.account, actor=self.user,
            nodes=[{"key": "source", "type": "search", "position": {}, "config": {}}, {"key": "gate", "type": "human_screen", "position": {}, "config": {}}, {"key": "end", "type": "end", "position": {}, "config": {}}],
            edges=[{"source": "source", "target": "gate"}, {"source": "gate", "target": "end"}],
        )
        self.client.force_authenticate(self.user)

    def test_dry_run_is_idempotent_and_supports_decision(self):
        payload = {"mode": "dry_run", "request_id": "api-dry-1", "input": {}}
        first = self.client.post(f"/api/recruitment/workflow-versions/{self.version.pk}/run/", payload, format="json")
        second = self.client.post(f"/api/recruitment/workflow-versions/{self.version.pk}/run/", payload, format="json")
        self.assertEqual(first.status_code, 201, first.data)
        self.assertEqual(second.status_code, 200, second.data)
        self.assertEqual(first.data["id"], second.data["id"])
        self.assertEqual(first.data["status"], "waiting_human")
        gate = next(node for node in first.data["node_runs"] if node["node_key"] == "gate")
        decided = self.client.post(f"/api/recruitment/workflow-runs/{first.data['id']}/decision/", {"node_id": gate["id"], "approved": True, "note": "ok"}, format="json")
        self.assertEqual(decided.status_code, 200, decided.data)
        self.assertEqual(decided.data["status"], "succeeded")

    def test_formal_run_requires_enabled_version_ready_account_and_confirmation(self):
        rejected = self.client.post(f"/api/recruitment/workflow-versions/{self.version.pk}/run/", {"mode": "formal", "request_id": "formal-1", "confirm": True}, format="json")
        self.assertEqual(rejected.status_code, 400)
        enable_version(version=self.version, actor=self.user)
        unconfirmed = self.client.post(f"/api/recruitment/workflow-versions/{self.version.pk}/run/", {"mode": "formal", "request_id": "formal-2"}, format="json")
        self.assertEqual(unconfirmed.status_code, 400)
        created = self.client.post(f"/api/recruitment/workflow-versions/{self.version.pk}/run/", {"mode": "formal", "request_id": "formal-3", "confirm": True}, format="json")
        self.assertEqual(created.status_code, 201, created.data)

    def test_controls_permissions_and_conflicts(self):
        created = self.client.post(f"/api/recruitment/workflow-versions/{self.version.pk}/run/", {"mode": "dry_run", "request_id": "controls"}, format="json")
        run_id = created.data["id"]
        paused = self.client.post(f"/api/recruitment/workflow-runs/{run_id}/pause/")
        self.assertEqual(paused.status_code, 200)
        resumed = self.client.post(f"/api/recruitment/workflow-runs/{run_id}/resume/")
        self.assertEqual(resumed.status_code, 200)
        cancelled = self.client.post(f"/api/recruitment/workflow-runs/{run_id}/cancel/")
        self.assertEqual(cancelled.status_code, 200)
        conflict = self.client.post(f"/api/recruitment/workflow-runs/{run_id}/pause/")
        self.assertEqual(conflict.status_code, 409)

        self.client.force_authenticate(self.other)
        self.assertEqual(self.client.get(f"/api/recruitment/workflow-runs/{run_id}/").status_code, 404)

