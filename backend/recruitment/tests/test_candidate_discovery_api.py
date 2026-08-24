from datetime import timedelta

from django.contrib.auth.models import User
from django.utils import timezone
from rest_framework.test import APITestCase

from attendance.models import AccountProfile
from recruitment.models import (
    AutomationApproval,
    BossAccount,
    Candidate,
    CandidateDiscovery,
    RecruitmentJob,
    RpaTask,
)


class CandidateDiscoveryApiTests(APITestCase):
    def setUp(self):
        self.hr = User.objects.create_user("discovery-api-hr", password="pass")
        AccountProfile.objects.create(user=self.hr, role=AccountProfile.Role.HR)
        self.other = User.objects.create_user("other-discovery-api-hr")
        AccountProfile.objects.create(user=self.other, role=AccountProfile.Role.HR)
        self.account = BossAccount.objects.create(
            name="发现 API 账号",
            browser_profile="discovery-api",
            cdp_port=53470,
        )
        self.account.authorized_users.add(self.hr)
        self.job = RecruitmentJob.objects.create(
            boss_account=self.account,
            external_id="api-job",
            title="前端工程师",
            owner=self.hr,
        )
        self.discovery = CandidateDiscovery.objects.create(
            boss_account=self.account,
            job=self.job,
            source=CandidateDiscovery.Source.RECOMMEND,
            fingerprint="d" * 64,
            identity_quality=CandidateDiscovery.IdentityQuality.FINGERPRINT,
            display_name="林晓",
            current_title="前端工程师",
            city="北京",
            expires_at=timezone.now() + timedelta(days=7),
        )
        self.client.force_authenticate(self.hr)

    def test_recommend_search_creates_idempotent_task(self):
        payload = {
            "boss_account": self.account.pk,
            "job": self.job.pk,
            "mode": "recommend",
            "keyword": "",
            "request_id": "11111111-1111-4111-8111-111111111111",
        }

        first = self.client.post("/api/recruitment/candidate-discoveries/search/", payload, format="json")
        repeated = self.client.post("/api/recruitment/candidate-discoveries/search/", payload, format="json")

        self.assertEqual(first.status_code, 201, first.data)
        self.assertEqual(repeated.status_code, 200, repeated.data)
        self.assertEqual(first.data["task_id"], repeated.data["task_id"])
        self.assertEqual(RpaTask.objects.get().action, RpaTask.Action.RECOMMEND_CANDIDATES)

    def test_job_must_belong_to_selected_account(self):
        other_account = BossAccount.objects.create(
            name="其他账号", browser_profile="other-account", cdp_port=53471
        )
        other_job = RecruitmentJob.objects.create(
            boss_account=other_account,
            external_id="other-job",
            title="后端工程师",
            owner=self.hr,
        )

        response = self.client.post(
            "/api/recruitment/candidate-discoveries/search/",
            {
                "boss_account": self.account.pk,
                "job": other_job.pk,
                "mode": "search",
                "keyword": "Python",
                "request_id": "22222222-2222-4222-8222-222222222222",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 400)

    def test_deep_match_is_draft_until_explicit_approval(self):
        prepared = self.client.post(
            "/api/recruitment/candidate-discoveries/prepare-deep-match/",
            {
                "boss_account": self.account.pk,
                "job": self.job.pk,
                "core": ["Vue 3"],
                "bonus": ["ToB"],
                "request_id": "33333333-3333-4333-8333-333333333333",
            },
            format="json",
        )

        self.assertEqual(prepared.status_code, 201, prepared.data)
        self.assertEqual(RpaTask.objects.count(), 0)
        approval = AutomationApproval.objects.get()
        self.assertEqual(approval.status, AutomationApproval.Status.DRAFT)
        self.assertEqual(approval.payload["estimated_consumption"], 1)

        approved = self.client.post(
            f"/api/recruitment/automation-approvals/{approval.pk}/approve/",
            {},
            format="json",
        )

        self.assertEqual(approved.status_code, 201, approved.data)
        approval.refresh_from_db()
        self.assertEqual(approval.status, AutomationApproval.Status.APPROVED)
        self.assertEqual(RpaTask.objects.get().action, RpaTask.Action.DEEP_MATCH)

    def test_import_selected_creates_candidate_and_application(self):
        response = self.client.post(
            "/api/recruitment/candidate-discoveries/import-selected/",
            {"ids": [str(self.discovery.pk)]},
            format="json",
        )

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["created_candidates"], 1)
        self.assertEqual(Candidate.objects.get().name, "林晓")
        self.discovery.refresh_from_db()
        self.assertIsNotNone(self.discovery.imported_candidate)

    def test_deep_approval_rolls_back_when_account_is_busy(self):
        prepared = self.client.post(
            "/api/recruitment/candidate-discoveries/prepare-deep-match/",
            {
                "boss_account": self.account.pk,
                "job": self.job.pk,
                "core": ["Vue"],
                "bonus": [],
                "request_id": "44444444-4444-4444-8444-444444444444",
            },
            format="json",
        )
        approval = AutomationApproval.objects.get(pk=prepared.data["id"])
        RpaTask.objects.create(
            boss_account=self.account,
            action=RpaTask.Action.CHECK_STATUS,
            created_by=self.hr,
        )

        response = self.client.post(
            f"/api/recruitment/automation-approvals/{approval.pk}/approve/", {}, format="json"
        )

        self.assertEqual(response.status_code, 400)
        approval.refresh_from_db()
        self.assertEqual(approval.status, AutomationApproval.Status.DRAFT)

    def test_other_hr_cannot_list_or_import_discovery(self):
        self.client.force_authenticate(self.other)

        listed = self.client.get("/api/recruitment/candidate-discoveries/")
        imported = self.client.post(
            "/api/recruitment/candidate-discoveries/import-selected/",
            {"ids": [str(self.discovery.pk)]},
            format="json",
        )

        self.assertEqual(listed.status_code, 200)
        self.assertEqual(listed.data["count"], 0)
        self.assertIn(imported.status_code, {400, 403})
