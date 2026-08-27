import uuid

from django.contrib.auth.models import User
from rest_framework.test import APITestCase

from attendance.models import AccountProfile
from recruitment.models import BossAccount, Candidate, JobApplication, RecruitmentJob


class CommunicationApiTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user("hr-api", password="pass")
        AccountProfile.objects.update_or_create(user=self.user, defaults={"role": AccountProfile.Role.HR})
        self.client.force_authenticate(self.user)
        self.account = BossAccount.objects.create(name="API 账号", browser_profile="api-profile", cdp_port=53524)
        self.account.authorized_users.add(self.user)
        self.job = RecruitmentJob.objects.create(
            boss_account=self.account, external_id="job-api", title="数据分析师", owner=self.user
        )
        candidate = Candidate.objects.create(identity_key="api-candidate", external_id="boss-api-1", name="顾宁")
        self.application = JobApplication.objects.create(candidate=candidate, job=self.job, source="boss")

    def test_prepare_then_approve_returns_execution_batch(self):
        prepared = self.client.post("/api/recruitment/communication-actions/prepare/", {
            "boss_account": self.account.pk,
            "application_ids": [self.application.pk],
            "action": "request_resume",
            "message": "方便发送 PDF 简历吗？",
            "request_id": str(uuid.uuid4()),
        }, format="json")
        self.assertEqual(prepared.status_code, 201)
        approval_id = prepared.data["approval_id"]
        approved = self.client.post(f"/api/recruitment/automation-approvals/{approval_id}/approve/")
        self.assertEqual(approved.status_code, 201)
        self.assertEqual(approved.data["batch"]["total_items"], 1)
        self.assertEqual(approved.data["batch"]["steps"][0]["candidate_name"], "顾宁")

        replayed = self.client.post(f"/api/recruitment/automation-approvals/{approval_id}/approve/")
        self.assertEqual(replayed.status_code, 200)
        self.assertEqual(replayed.data["batch"]["id"], approved.data["batch"]["id"])
        self.assertEqual(len(replayed.data["batch"]["steps"]), 1)

    def test_manual_pipeline_change_requires_reason(self):
        response = self.client.patch(
            f"/api/recruitment/applications/{self.application.pk}/",
            {"stage": "rejected"}, format="json",
        )
        self.assertEqual(response.status_code, 400)
        changed = self.client.patch(
            f"/api/recruitment/applications/{self.application.pk}/",
            {"stage": "rejected", "stage_reason": "岗位方向不匹配"}, format="json",
        )
        self.assertEqual(changed.status_code, 200)
        self.assertEqual(changed.data["stage"], "rejected")
        self.assertEqual(changed.data["stage_history"][0]["reason"], "岗位方向不匹配")
