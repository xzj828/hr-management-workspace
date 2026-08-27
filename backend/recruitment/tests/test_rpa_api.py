from datetime import timedelta
from concurrent.futures import ThreadPoolExecutor

from django.contrib.auth.models import User
from django.test import TransactionTestCase
from django.utils import timezone
from rest_framework.test import APITestCase

from attendance.models import AccountProfile
from recruitment.models import (
    AutomationApproval,
    AutomationUsage,
    BossAccount,
    Candidate,
    CandidateDiscovery,
    CandidateExternalIdentity,
    ConversationAction,
    JobApplication,
    RecruitmentAuditLog,
    RecruitmentJob,
    RpaTask,
    RpaWorker,
    SearchCampaign,
)
from recruitment.services.search_campaigns import _campaign_snapshot
from recruitment.services.approvals import approve
from recruitment.services.communications import materialize_communication_batch, prepare_communication
from recruitment.rpa.tasks import create_task


class RpaTaskApiTests(APITestCase):
    def setUp(self):
        self.hr = User.objects.create_user(username="task-hr")
        AccountProfile.objects.create(user=self.hr, role=AccountProfile.Role.HR)
        self.other_hr = User.objects.create_user(username="other-task-hr")
        AccountProfile.objects.create(user=self.other_hr, role=AccountProfile.Role.HR)
        self.viewer = User.objects.create_user(username="task-viewer")
        AccountProfile.objects.create(user=self.viewer, role=AccountProfile.Role.VIEWER)
        self.account = BossAccount.objects.create(
            name="任务测试账号",
            browser_profile="boss-task-test",
            cdp_port=53470,
            browser_executable="C:/Program Files/Google/Chrome/Application/chrome.exe",
            user_data_dir="C:/hr-test/profiles/boss-task-test",
        )
        self.account.authorized_users.add(self.hr)
        self.worker = RpaWorker.objects.create(
            key="rpa-api-worker",
            hostname="localhost",
            status=RpaWorker.Status.ONLINE,
            last_seen_at=timezone.now(),
            capabilities={"boss_cli": True},
        )

    def create_task(self, action="check_status", payload=None):
        self.client.force_login(self.hr)
        body = {"boss_account": self.account.id, "action": action}
        if payload is not None:
            body["request_payload"] = payload
        return self.client.post("/api/recruitment/rpa-tasks/", body, format="json")

    def test_hr_can_create_check_status_task(self):
        response = self.create_task(payload={"open_login": True})

        self.assertEqual(response.status_code, 201, response.data)
        task = RpaTask.objects.get(pk=response.data["id"])
        self.assertEqual(task.created_by, self.hr)
        self.assertEqual(task.events.get().event, "created")
        self.assertTrue(RecruitmentAuditLog.objects.filter(target_id=str(task.pk), action="task_created").exists())

    def test_open_login_is_rejected_when_worker_heartbeat_is_stale(self):
        self.worker.last_seen_at = timezone.now() - timedelta(minutes=5)
        self.worker.save(update_fields=["last_seen_at"])

        response = self.create_task(payload={"open_login": True})

        self.assertEqual(response.status_code, 409, response.data)
        self.assertIn("Worker", str(response.data))
        self.assertFalse(RpaTask.objects.exists())

    def test_sync_positions_is_rejected_when_runtime_is_offline(self):
        self.worker.last_seen_at = timezone.now() - timedelta(minutes=5)
        self.worker.save(update_fields=["last_seen_at"])

        response = self.create_task(action=RpaTask.Action.SYNC_POSITIONS)

        self.assertEqual(response.status_code, 409, response.data)
        self.assertFalse(RpaTask.objects.exists())

    def test_duplicate_open_login_reuses_pending_task(self):
        first = self.create_task(payload={"open_login": True})
        second = self.create_task(payload={"open_login": True})

        self.assertEqual(first.status_code, 201, first.data)
        self.assertEqual(second.status_code, 200, second.data)
        self.assertEqual(first.data["id"], second.data["id"])
        self.assertEqual(RpaTask.objects.count(), 1)

    def test_viewer_cannot_create_task(self):
        self.client.force_login(self.viewer)
        response = self.client.post(
            "/api/recruitment/rpa-tasks/",
            {"boss_account": self.account.id, "action": "sync_positions"},
            format="json",
        )

        self.assertEqual(response.status_code, 403)

    def test_unapproved_action_is_rejected(self):
        response = self.create_task(action="send_message")

        self.assertEqual(response.status_code, 400)

    def test_write_action_without_approval_is_rejected_with_policy_message(self):
        response = self.create_task(action="greet", payload={"candidate_ids": [1]})

        self.assertEqual(response.status_code, 400)
        self.assertIn("专用", str(response.data))

    def test_generic_endpoint_rejects_reused_approved_action_with_blank_idempotency(self):
        approval = AutomationApproval.objects.create(
            action=AutomationApproval.Action.DEEP_MATCH,
            boss_account=self.account,
            created_by=self.hr,
            approved_by=self.hr,
            status=AutomationApproval.Status.APPROVED,
            payload={"job": 1, "job_title": "测试", "core": [], "bonus": []},
        )
        self.client.force_login(self.hr)
        body = {
            "boss_account": self.account.pk,
            "action": RpaTask.Action.DEEP_MATCH,
            "approval": str(approval.pk),
            "idempotency_key": "",
            "request_payload": approval.payload,
        }

        first = self.client.post("/api/recruitment/rpa-tasks/", body, format="json")
        second = self.client.post("/api/recruitment/rpa-tasks/", body, format="json")

        self.assertEqual(first.status_code, 400)
        self.assertEqual(second.status_code, 400)
        self.assertFalse(RpaTask.objects.exists())
        self.assertFalse(AutomationUsage.objects.exists())

    def test_generic_endpoint_cannot_bypass_search_campaign_start_service(self):
        job = RecruitmentJob.objects.create(
            boss_account=self.account,
            external_id="generic-search-pull",
            title="后端工程师",
            owner=self.hr,
        )
        campaign = SearchCampaign.objects.create(
            name="禁止直建",
            boss_account=self.account,
            job=job,
            source="search",
            target_resume_count=1,
            max_scan_count=3,
            created_by=self.hr,
        )
        payload = _campaign_snapshot(campaign)
        approval = AutomationApproval.objects.create(
            action=AutomationApproval.Action.SEARCH_AND_PULL_RESUMES,
            boss_account=self.account,
            created_by=self.hr,
            approved_by=self.hr,
            status=AutomationApproval.Status.APPROVED,
            payload=payload,
            item_count=payload["resume_view_budget"],
        )
        self.client.force_login(self.hr)

        response = self.client.post(
            "/api/recruitment/rpa-tasks/",
            {
                "boss_account": self.account.pk,
                "action": RpaTask.Action.SEARCH_AND_PULL_RESUMES,
                "approval": str(approval.pk),
                "request_payload": payload,
            },
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        campaign.refresh_from_db()
        self.assertEqual(campaign.status, SearchCampaign.Status.DRAFT)
        self.assertFalse(RpaTask.objects.exists())
        self.assertFalse(AutomationUsage.objects.exists())

    def test_idempotency_key_returns_the_existing_task(self):
        self.client.force_login(self.hr)
        body = {
            "boss_account": self.account.id,
            "action": "sync_positions",
            "idempotency_key": "sync-click-1",
        }

        first = self.client.post("/api/recruitment/rpa-tasks/", body, format="json")
        second = self.client.post("/api/recruitment/rpa-tasks/", body, format="json")

        self.assertEqual(first.status_code, 201, first.data)
        self.assertEqual(second.status_code, 200, second.data)
        self.assertEqual(first.data["id"], second.data["id"])
        self.assertEqual(RpaTask.objects.count(), 1)

    def test_unassigned_hr_cannot_operate_account(self):
        self.client.force_login(self.other_hr)
        response = self.client.post(
            "/api/recruitment/rpa-tasks/",
            {"boss_account": self.account.id, "action": "check_status"},
            format="json",
        )

        self.assertEqual(response.status_code, 403)

    def test_superuser_can_create_safe_task_without_account_assignment(self):
        admin = User.objects.create_superuser(username="task-admin", email="task-admin@example.com")
        self.client.force_login(admin)

        response = self.client.post(
            "/api/recruitment/rpa-tasks/",
            {"boss_account": self.account.pk, "action": RpaTask.Action.CHECK_STATUS},
            format="json",
        )

        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(RpaTask.objects.get(pk=response.data["id"]).created_by, admin)

    def test_multiple_pending_tasks_are_queued_for_serial_execution(self):
        self.assertEqual(self.create_task().status_code, 201)

        response = self.create_task(action="sync_positions")

        self.assertEqual(response.status_code, 201)
        self.assertEqual(RpaTask.objects.count(), 2)

    def test_pending_task_can_be_cancelled(self):
        task_id = self.create_task().data["id"]

        response = self.client.post(f"/api/recruitment/rpa-tasks/{task_id}/cancel/")

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["status"], "cancelled")

    def test_running_task_requests_worker_cancellation_idempotently(self):
        task_id = self.create_task(action=RpaTask.Action.SYNC_POSITIONS).data["id"]
        RpaTask.objects.filter(pk=task_id).update(
            status=RpaTask.Status.RUNNING,
            worker=self.worker,
            started_at=timezone.now(),
        )

        first = self.client.post(f"/api/recruitment/rpa-tasks/{task_id}/cancel/")
        second = self.client.post(f"/api/recruitment/rpa-tasks/{task_id}/cancel/")

        self.assertEqual(first.status_code, 200, first.data)
        self.assertEqual(first.data["status"], "cancel_requested")
        self.assertEqual(second.status_code, 200, second.data)
        self.assertEqual(second.data["status"], "cancel_requested")
        task = RpaTask.objects.get(pk=task_id)
        self.assertIsNone(task.completed_at)
        self.assertEqual(task.events.filter(event="cancel_requested").count(), 1)

    def test_pending_communication_task_cannot_be_cancelled_outside_its_domain_batch(self):
        job = RecruitmentJob.objects.create(
            boss_account=self.account,
            external_id="communication-cancel",
            title="产品经理",
            owner=self.hr,
        )
        candidate = Candidate.objects.create(
            identity_key="communication-cancel-candidate",
            external_id="boss-communication-cancel",
            name="候选人",
        )
        CandidateExternalIdentity.objects.create(
            boss_account=self.account,
            candidate=candidate,
            external_id="boss-communication-cancel",
            fingerprint="c" * 64,
            identity_quality=CandidateDiscovery.IdentityQuality.PLATFORM,
        )
        application = JobApplication.objects.create(candidate=candidate, job=job, source="boss")
        approval = prepare_communication(
            account=self.account,
            applications=[application],
            action=ConversationAction.Action.GREET,
            message="你好",
            actor=self.hr,
            request_id="communication-cancel-request",
        )
        approve(approval=approval, actor=self.hr)
        batch = materialize_communication_batch(approval=approval, actor=self.hr)
        task = batch.rpa_tasks.get()
        action = ConversationAction.objects.get(approval=approval)
        self.client.force_login(self.hr)

        response = self.client.post(f"/api/recruitment/rpa-tasks/{task.pk}/cancel/")

        self.assertEqual(response.status_code, 400)
        task.refresh_from_db()
        batch.refresh_from_db()
        action.refresh_from_db()
        action.step.refresh_from_db()
        self.assertEqual(task.status, RpaTask.Status.PENDING)
        self.assertEqual(action.status, ConversationAction.Status.PENDING)
        self.assertEqual(action.step.status, "pending")

    def test_failed_task_can_be_retried(self):
        old_task = RpaTask.objects.create(
            boss_account=self.account,
            action=RpaTask.Action.CHECK_STATUS,
            status=RpaTask.Status.FAILED,
            created_by=self.hr,
            completed_at=timezone.now(),
        )
        self.client.force_login(self.hr)

        response = self.client.post(f"/api/recruitment/rpa-tasks/{old_task.pk}/retry/")

        self.assertEqual(response.status_code, 201, response.data)
        self.assertNotEqual(response.data["id"], str(old_task.pk))

    def test_approved_task_cannot_be_retried_through_generic_endpoint(self):
        approval = AutomationApproval.objects.create(
            action=AutomationApproval.Action.DEEP_MATCH,
            boss_account=self.account,
            created_by=self.hr,
            approved_by=self.hr,
            status=AutomationApproval.Status.APPROVED,
            payload={"job": 1, "job_title": "测试", "core": [], "bonus": []},
        )
        old_task = RpaTask.objects.create(
            boss_account=self.account,
            action=RpaTask.Action.DEEP_MATCH,
            status=RpaTask.Status.FAILED,
            created_by=self.hr,
            approval=approval,
            idempotency_key=f"deep-match-task:{approval.pk}",
            request_payload=approval.payload,
            completed_at=timezone.now(),
        )
        self.client.force_login(self.hr)

        response = self.client.post(f"/api/recruitment/rpa-tasks/{old_task.pk}/retry/")

        self.assertEqual(response.status_code, 400)
        self.assertEqual(RpaTask.objects.count(), 1)

    def test_summary_reads_persisted_worker_state(self):
        RpaWorker.objects.filter(pk=self.worker.pk).update(
            hostname="WIN-HR",
            version="0.6.6",
            last_seen_at=timezone.now() + timedelta(seconds=1),
        )
        self.client.force_login(self.hr)

        response = self.client.get("/api/recruitment/automation/summary/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["worker"]["version"], "0.6.6")
        self.assertTrue(response.data["cli_available"])

    def test_summary_treats_stale_worker_heartbeat_as_offline(self):
        RpaWorker.objects.filter(pk=self.worker.pk).update(
            last_seen_at=timezone.now() - timedelta(minutes=5),
        )
        self.client.force_login(self.hr)

        response = self.client.get("/api/recruitment/automation/summary/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["worker"]["status"], RpaWorker.Status.OFFLINE)
        self.assertFalse(response.data["cli_available"])


class ConcurrentCheckStatusCreationTests(TransactionTestCase):
    reset_sequences = True

    def setUp(self):
        self.hr = User.objects.create_user(username="concurrent-task-hr")
        AccountProfile.objects.create(user=self.hr, role=AccountProfile.Role.HR)
        self.account = BossAccount.objects.create(
            name="并发任务账号",
            browser_profile="concurrent-task-account",
            cdp_port=53492,
            browser_executable="C:/Program Files/Google/Chrome/Application/chrome.exe",
            user_data_dir="C:/hr-test/profiles/concurrent-task-account",
        )
        self.account.authorized_users.add(self.hr)
        RpaWorker.objects.create(
            key="concurrent-worker",
            hostname="localhost",
            status=RpaWorker.Status.ONLINE,
            last_seen_at=timezone.now(),
            capabilities={"boss_cli": True},
        )

    def test_concurrent_open_login_calls_return_one_active_task(self):
        def create():
            return create_task(
                account=BossAccount.objects.get(pk=self.account.pk),
                action=RpaTask.Action.CHECK_STATUS,
                actor=User.objects.get(pk=self.hr.pk),
                request_payload={"open_login": True},
                creation_path="generic",
            ).pk

        with ThreadPoolExecutor(max_workers=2) as pool:
            task_ids = list(pool.map(lambda _: create(), range(2)))

        self.assertEqual(task_ids[0], task_ids[1])
        self.assertEqual(RpaTask.objects.count(), 1)
