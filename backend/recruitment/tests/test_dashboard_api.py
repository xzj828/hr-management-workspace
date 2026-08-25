from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from attendance.models import AccountProfile
from recruitment.models import BossAccount, Candidate, JobApplication, RecruitmentJob, Resume, RpaTask


class RecruitmentDashboardApiTests(TestCase):
    def setUp(self):
        self.hr = User.objects.create_user(username="dashboard-hr")
        AccountProfile.objects.create(user=self.hr, role=AccountProfile.Role.HR)
        self.other = User.objects.create_user(username="dashboard-other")
        AccountProfile.objects.create(user=self.other, role=AccountProfile.Role.HR)
        self.account = BossAccount.objects.create(
            name="看板主账号", browser_profile="dashboard-main", cdp_port=53540,
            login_status=BossAccount.LoginStatus.READY, status=BossAccount.Status.READY,
        )
        self.account.authorized_users.add(self.hr)
        self.hidden_account = BossAccount.objects.create(
            name="不可见账号", browser_profile="dashboard-hidden", cdp_port=53541,
            status=BossAccount.Status.RISK,
        )
        self.hidden_account.authorized_users.add(self.other)
        self.job = RecruitmentJob.objects.create(
            boss_account=self.account, external_id="visible-job", title="产品经理",
            owner=self.hr, headcount=2, status=RecruitmentJob.Status.OPEN,
        )
        self.hidden_job = RecruitmentJob.objects.create(
            boss_account=self.hidden_account, external_id="hidden-job", title="隐藏职位",
            owner=self.other, headcount=1, status=RecruitmentJob.Status.OPEN,
        )
        candidate = Candidate.objects.create(identity_key="dashboard-visible", name="候选人甲")
        self.application = JobApplication.objects.create(
            candidate=candidate, job=self.job, source="boss", stage=JobApplication.Stage.WAITING_RESUME,
        )
        Resume.objects.create(
            candidate=candidate, application=self.application, original_name="甲.pdf",
            file="recruitment/resumes/demo-a.pdf", content_type="application/pdf", file_size=128,
            acquired_at=timezone.now(),
        )
        hidden_candidate = Candidate.objects.create(identity_key="dashboard-hidden", name="隐藏候选人")
        JobApplication.objects.create(
            candidate=hidden_candidate, job=self.hidden_job, source="boss", stage=JobApplication.Stage.TO_INTERVIEW,
        )
        RpaTask.objects.create(
            boss_account=self.account, action=RpaTask.Action.CHECK_STATUS,
            status=RpaTask.Status.WAITING_HUMAN, created_by=self.hr,
        )
        RpaTask.objects.create(
            boss_account=self.hidden_account, action=RpaTask.Action.CHECK_STATUS,
            status=RpaTask.Status.FAILED, created_by=self.other,
        )
        self.client = APIClient()
        self.client.force_login(self.hr)

    def test_dashboard_returns_complete_actionable_shape(self):
        response = self.client.get("/api/recruitment/dashboard/")

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(
            set(response.data),
            {"metrics", "today_actions", "alerts", "funnel", "job_progress", "trend", "recent_tasks"},
        )
        self.assertEqual(len(response.data["trend"]), 7)
        self.assertTrue(all("route" in item for item in response.data["today_actions"]))
        self.assertTrue(all({"key", "label", "count"} <= set(item) for item in response.data["funnel"]))
        self.assertEqual(response.data["recent_tasks"][0]["status"], RpaTask.Status.WAITING_HUMAN)

    def test_dashboard_is_scoped_to_authorized_accounts(self):
        response = self.client.get("/api/recruitment/dashboard/")

        metrics = response.data["metrics"]
        self.assertEqual(metrics["open_jobs"], 1)
        self.assertEqual(metrics["active_candidates"], 1)
        self.assertEqual(metrics["waiting_resumes"], 1)
        self.assertEqual(metrics["waiting_interviews"], 0)
        self.assertEqual(metrics["boss_accounts_ready"], 1)
        self.assertEqual([item["title"] for item in response.data["job_progress"]], ["产品经理"])
        progress = response.data["job_progress"][0]
        self.assertEqual(progress["route"], f"/recruitment/candidates?job={self.job.pk}")
        self.assertEqual(progress["account_name"], "看板主账号")
        self.assertEqual(progress["account_status"], BossAccount.Status.READY)
        self.assertEqual(progress["to_screen"], 0)
        self.assertEqual(progress["to_interview"], 0)
        self.assertIn("updated_at", progress)
        self.assertNotIn("不可见账号", str(response.data))

    def test_dashboard_remains_global_when_job_query_is_present(self):
        second_job = RecruitmentJob.objects.create(
            boss_account=self.account, external_id="second-visible-job", title="后端工程师",
            owner=self.hr, headcount=1, status=RecruitmentJob.Status.OPEN,
        )

        response = self.client.get(f"/api/recruitment/dashboard/?job={self.job.pk}")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["metrics"]["open_jobs"], 2)
        self.assertEqual(
            {item["id"] for item in response.data["job_progress"]},
            {self.job.pk, second_job.pk},
        )

    def test_empty_dashboard_keeps_every_section(self):
        empty_user = User.objects.create_user(username="dashboard-empty")
        AccountProfile.objects.create(user=empty_user, role=AccountProfile.Role.HR)
        self.client.force_login(empty_user)

        response = self.client.get("/api/recruitment/dashboard/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["metrics"]["open_jobs"], 0)
        self.assertEqual(response.data["job_progress"], [])
        self.assertEqual(response.data["recent_tasks"], [])
        self.assertEqual(len(response.data["trend"]), 7)
