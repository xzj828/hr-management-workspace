from django.contrib.auth.models import User
from rest_framework.test import APITestCase

from attendance.models import AccountProfile
from recruitment.models import BossAccount, RecruitmentJob, RpaTask, SearchCampaign


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

    def test_create_and_start_campaign_queues_composite_task(self):
        response = self.client.post("/api/recruitment/search-campaigns/", {
            "name": "后端主动寻访", "boss_account": self.account.pk, "job": self.job.pk,
            "source": "search", "target_resume_count": 3, "max_scan_count": 20,
            "criteria": {"keyword": "Python"},
        }, format="json")
        self.assertEqual(response.status_code, 201)

        started = self.client.post(f"/api/recruitment/search-campaigns/{response.data['id']}/start/", {}, format="json")
        self.assertEqual(started.status_code, 200)
        campaign = SearchCampaign.objects.get(pk=response.data["id"])
        task = RpaTask.objects.get(pk=started.data["task_id"])
        self.assertEqual(campaign.status, SearchCampaign.Status.QUEUED)
        self.assertEqual(task.action, RpaTask.Action.SEARCH_AND_PULL_RESUMES)
        self.assertEqual(task.request_payload["target_resume_count"], 3)

    def test_rejects_scan_limit_below_target(self):
        response = self.client.post("/api/recruitment/search-campaigns/", {
            "name": "invalid", "boss_account": self.account.pk, "job": self.job.pk,
            "source": "recommend", "target_resume_count": 10, "max_scan_count": 5,
        }, format="json")
        self.assertEqual(response.status_code, 400)

