from django.contrib.auth.models import User
from django.db import IntegrityError, transaction
from django.test import TestCase
from rest_framework.test import APITestCase

from attendance.models import AccountProfile

from .models import BossAccount, Candidate, JobApplication, RecruitmentJob


class RecruitmentFoundationModelTests(TestCase):
    def setUp(self):
        self.hr = User.objects.create_user(username="recruiter")
        self.account = BossAccount.objects.create(
            name="北京招聘账号",
            browser_profile="boss-beijing",
            cdp_port=53470,
            daily_contact_limit=50,
        )
        self.job = RecruitmentJob.objects.create(
            boss_account=self.account,
            external_id="boss-job-1",
            title="实施工程师",
            owner=self.hr,
        )
        self.candidate = Candidate.objects.create(
            identity_key="boss-beijing:candidate-1",
            external_id="candidate-1",
            name="测试候选人",
        )

    def test_account_cdp_port_is_unique(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            BossAccount.objects.create(name="重复端口", browser_profile="other", cdp_port=53470)

    def test_candidate_can_apply_to_multiple_jobs(self):
        first = JobApplication.objects.create(candidate=self.candidate, job=self.job, source="recommend")
        second_job = RecruitmentJob.objects.create(
            boss_account=self.account,
            external_id="boss-job-2",
            title="运维工程师",
            owner=self.hr,
        )
        second = JobApplication.objects.create(candidate=self.candidate, job=second_job, source="search")
        self.assertNotEqual(first.id, second.id)

    def test_duplicate_application_is_rejected(self):
        JobApplication.objects.create(candidate=self.candidate, job=self.job, source="recommend")
        with self.assertRaises(IntegrityError), transaction.atomic():
            JobApplication.objects.create(candidate=self.candidate, job=self.job, source="search")


class RecruitmentFoundationApiTests(APITestCase):
    def setUp(self):
        self.hr = User.objects.create_user(username="hr-api")
        AccountProfile.objects.create(user=self.hr, role=AccountProfile.Role.HR)
        self.viewer = User.objects.create_user(username="viewer-api")
        AccountProfile.objects.create(user=self.viewer, role=AccountProfile.Role.VIEWER)

    def test_hr_can_create_boss_account(self):
        self.client.force_login(self.hr)
        response = self.client.post(
            "/api/recruitment/boss-accounts/",
            {"name": "主招聘账号", "browser_profile": "main-boss", "cdp_port": 53470, "daily_contact_limit": 40},
            format="json",
        )
        self.assertEqual(response.status_code, 201)

    def test_viewer_cannot_create_boss_account(self):
        self.client.force_login(self.viewer)
        response = self.client.post(
            "/api/recruitment/boss-accounts/",
            {"name": "禁止创建", "browser_profile": "blocked", "cdp_port": 53471},
            format="json",
        )
        self.assertEqual(response.status_code, 403)

    def test_authenticated_user_can_read_empty_dashboard(self):
        self.client.force_login(self.viewer)
        response = self.client.get("/api/recruitment/dashboard/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["open_jobs"], 0)
        self.assertEqual(response.data["active_candidates"], 0)
