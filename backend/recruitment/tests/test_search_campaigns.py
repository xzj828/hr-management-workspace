from datetime import timedelta

from django.contrib.auth.models import User
from django.utils import timezone
from rest_framework.test import APITestCase

from attendance.models import AccountProfile
from recruitment.models import AutomationApproval, AutomationEvidence, AutomationUsage, BossAccount, RecruitmentJob, RpaTask, SearchCampaign


class SearchCampaignApiTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user("campaign-user", password="test")
        AccountProfile.objects.create(user=self.user, role=AccountProfile.Role.HR)
        self.client.force_authenticate(self.user)
        self.account = BossAccount.objects.create(name="Campaign account", browser_profile="campaign", cdp_port=53991)
        self.account.authorized_users.add(self.user)
        self.job = RecruitmentJob.objects.create(
            boss_account=self.account, external_id="campaign-job", title="Python 工程师", owner=self.user,
        )

    def test_start_prepares_snapshot_and_approval_atomically_reserves_view_budget(self):
        response = self.client.post("/api/recruitment/search-campaigns/", {
            "name": "后端主动寻访", "boss_account": self.account.pk, "job": self.job.pk,
            "source": "search", "target_resume_count": 3, "max_scan_count": 20,
            "criteria": {"keyword": "Python"},
        }, format="json")
        self.assertEqual(response.status_code, 201)

        started = self.client.post(f"/api/recruitment/search-campaigns/{response.data['id']}/start/", {}, format="json")
        self.assertEqual(started.status_code, 200)
        campaign = SearchCampaign.objects.get(pk=response.data["id"])
        approval = AutomationApproval.objects.get(pk=started.data["approval_id"])
        self.assertEqual(campaign.status, SearchCampaign.Status.DRAFT)
        self.assertEqual(approval.status, AutomationApproval.Status.DRAFT)
        self.assertEqual(approval.payload["criteria"], {"keyword": "Python"})
        self.assertEqual(approval.payload["resume_view_budget"], 20)
        self.assertFalse(RpaTask.objects.exists())

        approved = self.client.post(
            f"/api/recruitment/automation-approvals/{approval.pk}/approve/",
            {},
            format="json",
        )
        self.assertEqual(approved.status_code, 201, approved.data)
        campaign.refresh_from_db()
        task = RpaTask.objects.get(pk=approved.data["task_id"])
        self.assertEqual(campaign.status, SearchCampaign.Status.QUEUED)
        self.assertEqual(task.action, RpaTask.Action.SEARCH_AND_PULL_RESUMES)
        self.assertEqual(task.request_payload["target_resume_count"], 3)
        self.assertEqual(task.approval, approval)
        self.assertEqual(
            AutomationUsage.objects.get(boss_account=self.account, metric=AutomationUsage.Metric.SEARCH).used,
            1,
        )
        self.assertEqual(
            AutomationUsage.objects.get(boss_account=self.account, metric=AutomationUsage.Metric.RESUME_VIEW).used,
            20,
        )

    def test_approval_rolls_back_when_resume_view_budget_exceeds_daily_limit(self):
        self.account.daily_resume_view_limit = 2
        self.account.save(update_fields=["daily_resume_view_limit"])
        campaign = SearchCampaign.objects.create(
            name="额度受限", boss_account=self.account, job=self.job, source="search",
            target_resume_count=2, max_scan_count=3, criteria={"keyword": "Python"}, created_by=self.user,
        )
        prepared = self.client.post(f"/api/recruitment/search-campaigns/{campaign.pk}/start/", {}, format="json")

        response = self.client.post(
            f"/api/recruitment/automation-approvals/{prepared.data['approval_id']}/approve/",
            {},
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        approval = AutomationApproval.objects.get(pk=prepared.data["approval_id"])
        self.assertEqual(approval.status, AutomationApproval.Status.DRAFT)
        self.assertFalse(RpaTask.objects.exists())
        self.assertFalse(AutomationUsage.objects.exists())

    def test_expired_approval_api_persists_expired_status_after_400(self):
        campaign = SearchCampaign.objects.create(
            name="过期确认",
            boss_account=self.account,
            job=self.job,
            source="search",
            target_resume_count=1,
            max_scan_count=2,
            created_by=self.user,
        )
        prepared = self.client.post(f"/api/recruitment/search-campaigns/{campaign.pk}/start/")
        approval = AutomationApproval.objects.get(pk=prepared.data["approval_id"])
        approval.expires_at = timezone.now() - timedelta(seconds=1)
        approval.save(update_fields=["expires_at"])

        response = self.client.post(
            f"/api/recruitment/automation-approvals/{approval.pk}/approve/",
            {},
            format="json",
        )

        self.assertEqual(response.status_code, 400, response.data)
        approval.refresh_from_db()
        self.assertEqual(approval.status, AutomationApproval.Status.EXPIRED)
        self.assertFalse(RpaTask.objects.exists())

    def test_generic_task_cancel_dispatches_search_campaign_stop_and_persists_ledger(self):
        campaign = SearchCampaign.objects.create(
            name="执行前停止",
            boss_account=self.account,
            job=self.job,
            source="search",
            target_resume_count=1,
            max_scan_count=3,
            criteria={"keyword": "Python"},
            created_by=self.user,
        )
        prepared = self.client.post(
            f"/api/recruitment/search-campaigns/{campaign.pk}/start/",
            {},
            format="json",
        )
        approved = self.client.post(
            f"/api/recruitment/automation-approvals/{prepared.data['approval_id']}/approve/",
            {},
            format="json",
        )
        task = RpaTask.objects.get(pk=approved.data["task_id"])

        response = self.client.post(
            f"/api/recruitment/rpa-tasks/{task.pk}/cancel/",
            {},
            format="json",
        )

        self.assertEqual(response.status_code, 200, response.data)
        task.refresh_from_db()
        campaign.refresh_from_db()
        self.assertEqual(task.status, RpaTask.Status.CANCELLED)
        self.assertEqual(campaign.status, SearchCampaign.Status.CANCELLED)
        usage = AutomationEvidence.objects.get(task=task, kind="resume_view_usage")
        self.assertEqual(usage.metadata["reserved"], 3)
        self.assertEqual(usage.metadata["actual"], 0)
        self.assertEqual(usage.metadata["unused"], 3)
        self.assertEqual(usage.metadata["unused_disposition"], "retained_no_refund")
        self.assertEqual(
            AutomationUsage.objects.get(
                boss_account=self.account,
                metric=AutomationUsage.Metric.RESUME_VIEW,
            ).used,
            3,
        )
        replay = self.client.post(
            f"/api/recruitment/rpa-tasks/{task.pk}/cancel/",
            {},
            format="json",
        )
        self.assertEqual(replay.status_code, 400, replay.data)
        self.assertEqual(AutomationEvidence.objects.filter(task=task).count(), 2)

    def test_stop_refuses_to_claim_cancellation_after_browser_execution_started(self):
        campaign = SearchCampaign.objects.create(
            name="执行中停止",
            boss_account=self.account,
            job=self.job,
            source="search",
            target_resume_count=1,
            max_scan_count=2,
            criteria={"keyword": "Python"},
            created_by=self.user,
        )
        prepared = self.client.post(
            f"/api/recruitment/search-campaigns/{campaign.pk}/start/",
            {},
            format="json",
        )
        approved = self.client.post(
            f"/api/recruitment/automation-approvals/{prepared.data['approval_id']}/approve/",
            {},
            format="json",
        )
        task = RpaTask.objects.get(pk=approved.data["task_id"])
        task.status = RpaTask.Status.LEASED
        task.save(update_fields=["status", "updated_at"])

        response = self.client.post(
            f"/api/recruitment/search-campaigns/{campaign.pk}/stop/",
            {},
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        campaign.refresh_from_db()
        task.refresh_from_db()
        self.assertEqual(campaign.status, SearchCampaign.Status.QUEUED)
        self.assertEqual(task.status, RpaTask.Status.LEASED)
        self.assertFalse(AutomationEvidence.objects.filter(task=task).exists())

    def test_paused_campaign_cannot_pretend_to_restart_over_waiting_task(self):
        campaign = SearchCampaign.objects.create(
            name="已转人工的主动寻访",
            boss_account=self.account,
            job=self.job,
            source="search",
            status=SearchCampaign.Status.PAUSED,
            target_resume_count=1,
            max_scan_count=2,
            criteria={"keyword": "Python"},
            created_by=self.user,
        )
        old_task = RpaTask.objects.create(
            boss_account=self.account,
            action=RpaTask.Action.SEARCH_AND_PULL_RESUMES,
            created_by=self.user,
            status=RpaTask.Status.WAITING_HUMAN,
            request_payload={"campaign_id": campaign.pk, "resume_view_budget": 2},
        )

        response = self.client.post(
            f"/api/recruitment/search-campaigns/{campaign.pk}/start/",
            {},
            format="json",
        )

        self.assertEqual(response.status_code, 400, response.data)
        self.assertIn("不支持恢复", str(response.data))
        old_task.refresh_from_db()
        campaign.refresh_from_db()
        self.assertEqual(old_task.status, RpaTask.Status.WAITING_HUMAN)
        self.assertEqual(campaign.status, SearchCampaign.Status.PAUSED)
        self.assertFalse(AutomationApproval.objects.exists())

    def test_rejects_scan_limit_below_target(self):
        response = self.client.post("/api/recruitment/search-campaigns/", {
            "name": "invalid", "boss_account": self.account.pk, "job": self.job.pk,
            "source": "recommend", "target_resume_count": 10, "max_scan_count": 5,
        }, format="json")
        self.assertEqual(response.status_code, 400)

