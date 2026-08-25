from unittest.mock import Mock

from django.contrib.auth.models import User
from django.test import SimpleTestCase, override_settings
from rest_framework.exceptions import ValidationError
from rest_framework.test import APITestCase

from attendance.models import AccountProfile
from recruitment.management.commands.run_rpa_worker import (
    execute_deep_match,
    execute_recommend_candidates,
    execute_search_candidates,
)
from recruitment.models import (
    AutomationApproval,
    AutomationUsage,
    BossAccount,
    CandidateDiscovery,
    RecruitmentJob,
    RpaTask,
    RpaWorker,
)
from recruitment.rpa.capabilities import REGISTRY
from recruitment.rpa.cli import CliAccountConfig
from recruitment.rpa.tasks import create_task


class CandidateWorkerContractTests(SimpleTestCase):
    def setUp(self):
        self.account = CliAccountConfig("edge.exe", "C:/profiles/a", 53470)
        self.runner = Mock()
        self.rows = [{"display_name": "林晓", "identity_quality": "fingerprint"}]

    def test_candidate_capabilities_are_declared_safely(self):
        self.assertTrue(REGISTRY["recommend_candidates"].read_only)
        self.assertFalse(REGISTRY["recommend_candidates"].requires_approval)
        self.assertEqual(REGISTRY["search_candidates"].consumes, "search")
        self.assertTrue(REGISTRY["deep_match"].requires_approval)
        self.assertEqual(REGISTRY["deep_match"].consumes, "deep_match")

    def test_worker_dispatches_candidate_runner_methods(self):
        self.runner.recommend.return_value = self.rows
        self.runner.search.return_value = self.rows
        self.runner.deep_search.return_value = self.rows

        recommended = execute_recommend_candidates(
            {"request_payload": {"job_title": "前端"}}, self.account, self.runner
        )
        searched = execute_search_candidates(
            {"request_payload": {"keyword": "Vue"}}, self.account, self.runner
        )
        deep = execute_deep_match(
            {"request_payload": {"job_title": "前端", "core": ["Vue"], "bonus": ["ToB"]}},
            self.account,
            self.runner,
        )

        self.assertEqual(recommended["result"]["candidates"], self.rows)
        self.runner.recommend.assert_called_once_with(self.account, "前端")
        self.runner.search.assert_called_once_with(self.account, "Vue")
        self.runner.deep_search.assert_called_once_with(
            self.account, job="前端", core=["Vue"], bonus=["ToB"], match=True
        )
        self.assertEqual(searched["status"], "succeeded")
        self.assertEqual(deep["status"], "succeeded")


@override_settings(RPA_WORKER_TOKEN="candidate-worker-secret")
class CandidateWorkerApiTests(APITestCase):
    header = {"HTTP_X_RPA_WORKER_TOKEN": "candidate-worker-secret"}

    def setUp(self):
        self.hr = User.objects.create_user("candidate-worker-hr")
        AccountProfile.objects.create(user=self.hr, role=AccountProfile.Role.HR)
        self.account = BossAccount.objects.create(
            name="候选人 Worker 账号",
            browser_profile="candidate-worker",
            cdp_port=53470,
        )
        self.account.authorized_users.add(self.hr)
        self.job = RecruitmentJob.objects.create(
            boss_account=self.account,
            external_id="job-worker",
            title="前端工程师",
            owner=self.hr,
        )
        self.worker = RpaWorker.objects.create(key="candidate-worker", hostname="WIN-HR")

    def test_successful_completion_upserts_discovery_rows(self):
        task = RpaTask.objects.create(
            boss_account=self.account,
            action="recommend_candidates",
            created_by=self.hr,
            worker=self.worker,
            status=RpaTask.Status.RUNNING,
            request_payload={"job": self.job.pk, "job_title": self.job.title, "criteria": {}},
        )

        response = self.client.post(
            f"/api/recruitment/worker/tasks/{task.pk}/complete/",
            {
                "worker_key": self.worker.key,
                "status": "succeeded",
                "result": {"candidates": [{
                    "display_name": "林晓",
                    "current_title": "前端工程师",
                    "city": "北京",
                    "identity_quality": "fingerprint",
                    "tags": ["Vue"],
                }]},
            },
            format="json",
            **self.header,
        )

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(CandidateDiscovery.objects.count(), 1)
        task.refresh_from_db()
        self.assertEqual(task.result["sync"]["created"], 1)
        self.assertNotIn("candidates", task.result)

    def test_idempotent_search_consumes_quota_once(self):
        first, created = create_task(
            account=self.account,
            action="search_candidates",
            actor=self.hr,
            request_payload={"job": self.job.pk, "keyword": "Vue"},
            idempotency_key="candidate-search:one",
            return_created=True,
        )
        repeated, repeated_created = create_task(
            account=self.account,
            action="search_candidates",
            actor=self.hr,
            request_payload={"job": self.job.pk, "keyword": "Vue"},
            idempotency_key="candidate-search:one",
            return_created=True,
        )

        self.assertTrue(created)
        self.assertFalse(repeated_created)
        self.assertEqual(first, repeated)
        self.assertEqual(
            AutomationUsage.objects.get(
                boss_account=self.account, metric=AutomationUsage.Metric.SEARCH
            ).used,
            1,
        )

    def test_deep_match_requires_approved_snapshot(self):
        approval = AutomationApproval.objects.create(
            action=AutomationApproval.Action.DEEP_MATCH,
            boss_account=self.account,
            created_by=self.hr,
            approved_by=self.hr,
            status=AutomationApproval.Status.APPROVED,
            payload={
                "job": self.job.pk,
                "job_title": self.job.title,
                "core": [],
                "bonus": [],
            },
        )

        task = create_task(
            account=self.account,
            action=RpaTask.Action.DEEP_MATCH,
            actor=self.hr,
            approval=approval,
            request_payload={
                "job": self.job.pk,
                "job_title": self.job.title,
                "core": [],
                "bonus": [],
            },
            idempotency_key=f"deep-match-task:{approval.pk}",
            creation_path="deep_match_approval",
        )

        self.assertEqual(task.approval, approval)
        self.assertEqual(
            AutomationUsage.objects.get(
                boss_account=self.account, metric=AutomationUsage.Metric.DEEP_MATCH
            ).used,
            1,
        )

    def test_deep_match_approved_snapshot_still_requires_dedicated_creation_path(self):
        payload = {
            "job": self.job.pk,
            "job_title": self.job.title,
            "core": [],
            "bonus": [],
        }
        approval = AutomationApproval.objects.create(
            action=AutomationApproval.Action.DEEP_MATCH,
            boss_account=self.account,
            created_by=self.hr,
            approved_by=self.hr,
            status=AutomationApproval.Status.APPROVED,
            payload=payload,
        )

        with self.assertRaisesMessage(ValidationError, "专用编排服务"):
            create_task(
                account=self.account,
                action=RpaTask.Action.DEEP_MATCH,
                actor=self.hr,
                approval=approval,
                request_payload=payload,
                idempotency_key=f"deep-match-task:{approval.pk}",
            )

        self.assertFalse(RpaTask.objects.exists())
        self.assertFalse(AutomationUsage.objects.exists())
