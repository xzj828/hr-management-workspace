from django.contrib.auth.models import User
from django.db import IntegrityError, transaction
from django.test import TestCase
from rest_framework.test import APITestCase

from attendance.models import AccountProfile

from recruitment.models import (
    BossAccount,
    Candidate,
    JobApplication,
    RecruitmentJob,
    Resume,
    RpaTask,
    RpaTaskEvent,
    RpaWorker,
)


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

    def test_boss_account_defaults_to_chrome_and_unverified(self):
        self.assertEqual(self.account.browser_type, BossAccount.BrowserType.CHROME)
        self.assertEqual(self.account.login_status, BossAccount.LoginStatus.UNKNOWN)

    def test_account_cannot_have_two_active_tasks(self):
        RpaTask.objects.create(
            boss_account=self.account,
            action=RpaTask.Action.CHECK_STATUS,
            created_by=self.hr,
        )
        with self.assertRaises(IntegrityError), transaction.atomic():
            RpaTask.objects.create(
                boss_account=self.account,
                action=RpaTask.Action.SYNC_POSITIONS,
                created_by=self.hr,
            )

    def test_task_event_records_a_timeline_entry(self):
        worker = RpaWorker.objects.create(key="local-worker", hostname="WIN-HR")
        task = RpaTask.objects.create(
            boss_account=self.account,
            action=RpaTask.Action.CHECK_STATUS,
            created_by=self.hr,
            worker=worker,
        )
        event = RpaTaskEvent.objects.create(task=task, event="leased", message="任务已领取")
        self.assertEqual(event.task, task)

    def test_demo_job_can_exist_without_boss_account(self):
        job = RecruitmentJob.objects.create(
            boss_account=None,
            external_id="demo:job:frontend",
            title="前端工程师",
            owner=self.hr,
            is_demo=True,
        )

        self.assertIsNone(job.boss_account)
        self.assertTrue(job.is_demo)

    def test_pdf_resume_belongs_to_candidate_and_application(self):
        application = JobApplication.objects.create(
            candidate=self.candidate,
            job=self.job,
            source="demo",
            is_demo=True,
        )
        resume = Resume.objects.create(
            candidate=self.candidate,
            application=application,
            original_name="candidate.pdf",
            file="recruitment/resumes/candidate.pdf",
            content_type="application/pdf",
            file_size=128,
            source=Resume.Source.DEMO,
            is_demo=True,
        )

        self.assertEqual(resume.application, application)
        self.assertEqual(self.candidate.resumes.get(), resume)


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
        self.assertEqual(response.data["metrics"]["open_jobs"], 0)
        self.assertEqual(response.data["metrics"]["active_candidates"], 0)
        self.assertEqual(response.data["job_progress"], [])
