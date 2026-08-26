from datetime import timedelta
import json
import tempfile
import uuid
from pathlib import Path
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APIClient, APITestCase

from attendance.models import AccountProfile
from recruitment.models import (
    AutomationApproval,
    AutomationEvidence,
    BossAccount,
    Candidate,
    CandidateDiscovery,
    CandidateExternalIdentity,
    ConversationAction,
    ConversationMessage,
    HumanAttention,
    JobApplication,
    RecruitmentAuditLog,
    RecruitmentJob,
    Resume,
    RpaTask,
    RpaWorker,
    SearchCampaign,
    WorkflowNodeRun,
    WorkflowRun,
    WorkflowTemplate,
    WorkflowVersion,
)
from recruitment.services.discovery import _fingerprint
from recruitment.services.resumes import archive_online_resume_image as real_archive_online_resume_image
from recruitment.services.search_campaigns import _campaign_snapshot


class LeaseAwareWorkerClient(APIClient):
    """Make legacy happy-path fixtures speak the current per-lease protocol."""

    def post(self, path, data=None, format=None, content_type=None, follow=False, **extra):
        payload = dict(data) if isinstance(data, dict) else data
        if (
            isinstance(payload, dict)
            and "/worker/tasks/" in str(path)
            and (str(path).endswith("/event/") or str(path).endswith("/complete/"))
            and "lease_token" not in payload
        ):
            task_id = str(path).split("/worker/tasks/", 1)[1].split("/", 1)[0]
            task = RpaTask.objects.filter(pk=task_id).select_related("worker").first()
            if (
                task is not None
                and task.worker_id is not None
                and task.worker.key == payload.get("worker_key")
                and task.lease_token is not None
            ):
                payload["lease_token"] = str(task.lease_token)
                payload["lease_generation"] = task.lease_generation
        return super().post(
            path, data=payload, format=format, content_type=content_type, follow=follow, **extra
        )


@override_settings(RPA_WORKER_TOKEN="test-worker-secret")
class WorkerApiTests(APITestCase):
    client_class = LeaseAwareWorkerClient
    token_header = {"HTTP_X_RPA_WORKER_TOKEN": "test-worker-secret"}

    def setUp(self):
        self.hr = User.objects.create_user(username="worker-task-owner")
        self.account = BossAccount.objects.create(
            name="Worker 测试账号",
            browser_profile="boss-worker-test",
            browser_type="edge",
            browser_executable="C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe",
            user_data_dir="C:/hr/profiles/boss-worker-test",
            cdp_port=53470,
        )
        self.task = RpaTask.objects.create(
            boss_account=self.account,
            action=RpaTask.Action.CHECK_STATUS,
            created_by=self.hr,
            request_payload={"open_login": True},
        )

    def heartbeat(self):
        return self.client.post(
            "/api/recruitment/worker/heartbeat/",
            {"worker_key": "local-worker", "hostname": "WIN-HR", "version": "0.6.6", "capabilities": {"boss_cli": True}},
            format="json",
            **self.token_header,
        )

    def test_worker_endpoint_rejects_missing_token(self):
        response = self.client.post("/api/recruitment/worker/heartbeat/", {}, format="json")

        self.assertEqual(response.status_code, 403)

    def test_heartbeat_upserts_worker(self):
        response = self.heartbeat()

        self.assertEqual(response.status_code, 200, response.data)
        worker = RpaWorker.objects.get(key="local-worker")
        self.assertEqual(worker.status, RpaWorker.Status.ONLINE)
        self.assertTrue(worker.capabilities["boss_cli"])

    def test_worker_leases_oldest_pending_task(self):
        self.heartbeat()

        response = self.client.post(
            "/api/recruitment/worker/tasks/lease/",
            {"worker_key": "local-worker"},
            format="json",
            **self.token_header,
        )

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["task"]["id"], str(self.task.id))
        self.assertEqual(response.data["task"]["browser"]["type"], "edge")
        self.task.refresh_from_db()
        self.assertEqual(self.task.status, RpaTask.Status.LEASED)

    def test_worker_never_leases_task_from_cancelled_workflow(self):
        template = WorkflowTemplate.objects.create(name="cancelled lease", created_by=self.hr)
        version = WorkflowVersion.objects.create(
            template=template,
            version=1,
            boss_account=self.account,
            created_by=self.hr,
        )

    @staticmethod
    def lease_credentials(lease):
        return {
            "lease_token": lease.data["task"]["lease_token"],
            "lease_generation": lease.data["task"]["lease_generation"],
        }
        run = WorkflowRun.objects.create(
            version=version,
            boss_account=self.account,
            actor=self.hr,
            status=WorkflowRun.Status.CANCELLED,
            idempotency_key="cancelled-workflow-lease",
            graph_snapshot={"nodes": [], "edges": []},
            completed_at=timezone.now(),
        )
        node = WorkflowNodeRun.objects.create(
            run=run,
            node_key="deep",
            node_type="deep_search",
            status=WorkflowNodeRun.Status.RUNNING,
            idempotency_key="cancelled-workflow-node-lease",
        )
        self.task.workflow_node_run = node
        self.task.save(update_fields=["workflow_node_run", "updated_at"])
        self.heartbeat()

        response = self.client.post(
            "/api/recruitment/worker/tasks/lease/",
            {"worker_key": "local-worker"},
            format="json",
            **self.token_header,
        )

        self.assertEqual(response.status_code, 200, response.data)
        self.assertIsNone(response.data["task"])
        self.task.refresh_from_db()
        self.assertEqual(self.task.status, RpaTask.Status.PENDING)

    def test_expired_lease_can_be_reclaimed(self):
        self.heartbeat()
        worker = RpaWorker.objects.get(key="local-worker")
        old_token = uuid.uuid4()
        self.task.status = RpaTask.Status.LEASED
        self.task.worker = worker
        self.task.lease_expires_at = timezone.now() - timedelta(seconds=1)
        self.task.lease_token = old_token
        self.task.lease_generation = 1
        self.task.save()

        response = self.client.post(
            "/api/recruitment/worker/tasks/lease/",
            {"worker_key": "local-worker"},
            format="json",
            **self.token_header,
        )

        self.assertEqual(response.status_code, 200, response.data)
        self.task.refresh_from_db()
        self.assertEqual(self.task.worker.key, "local-worker")

        stale_event = self.client.post(
            f"/api/recruitment/worker/tasks/{self.task.pk}/event/",
            {
                "worker_key": "local-worker", "event": "started", "message": "迟到的旧租约",
                "lease_token": str(old_token), "lease_generation": 1,
            },
            format="json",
            **self.token_header,
        )

        self.assertEqual(stale_event.status_code, 409, stale_event.data)
        stale_complete = self.client.post(
            f"/api/recruitment/worker/tasks/{self.task.pk}/complete/",
            {
                "worker_key": "local-worker", "status": "succeeded", "result": {},
                "lease_token": str(old_token), "lease_generation": 1,
            },
            format="json",
            **self.token_header,
        )
        self.assertEqual(stale_complete.status_code, 409, stale_complete.data)
        self.task.refresh_from_db()
        self.assertEqual(self.task.worker.key, "local-worker")
        self.assertEqual(self.task.status, RpaTask.Status.LEASED)

    def test_expired_but_not_reassigned_completion_is_rejected(self):
        worker = RpaWorker.objects.create(key="slow-worker", hostname="SLOW")
        lease_token = uuid.uuid4()
        self.task.status = RpaTask.Status.RUNNING
        self.task.worker = worker
        self.task.lease_expires_at = timezone.now() - timedelta(seconds=1)
        self.task.lease_token = lease_token
        self.task.lease_generation = 1
        self.task.save(update_fields=[
            "status", "worker", "lease_expires_at", "lease_token", "lease_generation",
        ])

        response = self.client.post(
            f"/api/recruitment/worker/tasks/{self.task.pk}/complete/",
            {
                "worker_key": worker.key,
                "lease_token": str(lease_token),
                "lease_generation": 1,
                "status": "succeeded",
                "result": {"login_status": "ready", "verification_status": "none", "detail": ""},
            },
            format="json",
            **self.token_header,
        )

        self.assertEqual(response.status_code, 409, response.data)
        self.task.refresh_from_db()
        self.assertEqual(self.task.status, RpaTask.Status.RUNNING)

    def test_worker_can_append_event_and_complete(self):
        self.heartbeat()
        lease = self.client.post(
            "/api/recruitment/worker/tasks/lease/",
            {"worker_key": "local-worker"}, format="json", **self.token_header,
        )
        task_id = lease.data["task"]["id"]

        event = self.client.post(
            f"/api/recruitment/worker/tasks/{task_id}/event/",
            {
                **self.lease_credentials(lease),
                "worker_key": "local-worker", "event": "browser_checked", "message": "浏览器状态已检查",
            },
            format="json", **self.token_header,
        )
        complete = self.client.post(
            f"/api/recruitment/worker/tasks/{task_id}/complete/",
            {
                **self.lease_credentials(lease),
                "worker_key": "local-worker", "status": "waiting_human", "result": {"login_status": "token_invalid"},
            },
            format="json", **self.token_header,
        )

        self.assertEqual(event.status_code, 201, event.data)
        self.assertEqual(complete.status_code, 200, complete.data)
        self.task.refresh_from_db()
        self.account.refresh_from_db()
        self.assertEqual(self.task.status, RpaTask.Status.WAITING_HUMAN)
        self.assertEqual(self.account.verification_status, "token_invalid")
        self.assertEqual(self.account.status, BossAccount.Status.RISK)

        replay = self.client.post(
            f"/api/recruitment/worker/tasks/{task_id}/complete/",
            {
                **self.lease_credentials(lease),
                "worker_key": "local-worker", "status": "succeeded", "result": {},
            },
            format="json", **self.token_header,
        )
        self.assertEqual(replay.status_code, 409)

    def test_worker_reads_cancel_control_and_late_success_becomes_cancelled(self):
        self.heartbeat()
        lease = self.client.post(
            "/api/recruitment/worker/tasks/lease/",
            {"worker_key": "local-worker"}, format="json", **self.token_header,
        )
        task_id = lease.data["task"]["id"]
        RpaTask.objects.filter(pk=task_id).update(status="cancel_requested")

        control = self.client.get(
            f"/api/recruitment/worker/tasks/{task_id}/control/",
            {"worker_key": "local-worker", **self.lease_credentials(lease)},
            **self.token_header,
        )
        complete = self.client.post(
            f"/api/recruitment/worker/tasks/{task_id}/complete/",
            {
                "worker_key": "local-worker",
                **self.lease_credentials(lease),
                "status": "succeeded",
                "result": {"ignored": True},
            },
            format="json", **self.token_header,
        )

        self.assertEqual(control.status_code, 200, control.data)
        self.assertTrue(control.data["cancel_requested"])
        self.assertEqual(complete.status_code, 200, complete.data)
        self.assertEqual(complete.data["status"], "cancelled")
        self.task.refresh_from_db()
        self.assertEqual(self.task.status, RpaTask.Status.CANCELLED)
        self.assertEqual(self.task.result, {})

    def test_progress_event_renews_running_task_lease(self):
        self.heartbeat()
        lease = self.client.post(
            "/api/recruitment/worker/tasks/lease/",
            {"worker_key": "local-worker"}, format="json", **self.token_header,
        )
        task_id = lease.data["task"]["id"]
        self.task.refresh_from_db()
        old_expiry = self.task.lease_expires_at

        response = self.client.post(
            f"/api/recruitment/worker/tasks/{task_id}/event/",
            {
                **self.lease_credentials(lease),
                "worker_key": "local-worker", "event": "progress", "message": "仍在执行",
            },
            format="json", **self.token_header,
        )

        self.assertEqual(response.status_code, 201, response.data)
        self.task.refresh_from_db()
        self.assertEqual(self.task.status, RpaTask.Status.RUNNING)
        self.assertGreater(self.task.lease_expires_at, old_expiry)

    def test_successful_position_task_persists_only_normalized_jobs(self):
        self.task.action = RpaTask.Action.SYNC_POSITIONS
        self.task.save(update_fields=["action"])
        self.heartbeat()
        lease = self.client.post(
            "/api/recruitment/worker/tasks/lease/",
            {"worker_key": "local-worker"}, format="json", **self.token_header,
        )

        response = self.client.post(
            f"/api/recruitment/worker/tasks/{lease.data['task']['id']}/complete/",
            {
                "worker_key": "local-worker",
                "status": "succeeded",
                "result": {"positions": [{
                    "external_id": "job-201", "title": "测试工程师", "status": "open", "raw": "原始 CLI 行"
                }]},
            },
            format="json", **self.token_header,
        )

        self.assertEqual(response.status_code, 200, response.data)
        self.assertTrue(RecruitmentJob.objects.filter(boss_account=self.account, external_id="job-201").exists())
        self.task.refresh_from_db()
        self.assertEqual(self.task.result["sync"]["created"], 1)
        self.assertNotIn("positions", self.task.result)

    def test_individual_resume_bare_verified_result_never_archives(self):
        application, target = self.configure_online_resume_task(suffix="missing-id")
        self.heartbeat()
        lease = self.client.post(
            "/api/recruitment/worker/tasks/lease/",
            {"worker_key": "local-worker"},
            format="json",
            **self.token_header,
        )

        response = self.client.post(
            f"/api/recruitment/worker/tasks/{lease.data['task']['id']}/complete/",
            {
                "worker_key": "local-worker",
                "status": "succeeded",
                "result": {
                    "verified": True,
                    "identity_fingerprint": target["fingerprint"],
                    "image_path": "must-not-be-read.png",
                },
            },
            format="json",
            **self.token_header,
        )

        self.assertEqual(response.status_code, 200, response.data)
        self.task.refresh_from_db()
        application.refresh_from_db()
        self.assertEqual(self.task.status, RpaTask.Status.WAITING_HUMAN)
        self.assertEqual(self.task.error_code, "target_identity_unverifiable")
        self.assertEqual(application.stage, JobApplication.Stage.NEW)
        self.assertFalse(Resume.objects.exists())

    def test_individual_resume_wrong_observed_external_id_never_archives(self):
        application, target = self.configure_online_resume_task(suffix="wrong-id")
        self.heartbeat()
        lease = self.client.post(
            "/api/recruitment/worker/tasks/lease/",
            {"worker_key": "local-worker"},
            format="json",
            **self.token_header,
        )

        response = self.client.post(
            f"/api/recruitment/worker/tasks/{lease.data['task']['id']}/complete/",
            {
                "worker_key": "local-worker",
                "status": "succeeded",
                "result": {
                    "verified": True,
                    "expected_external_id": target["external_id"],
                    "observed_external_id": "boss-wrong-id",
                    "identity_fingerprint": target["fingerprint"],
                    "image_path": "must-not-be-read.png",
                },
            },
            format="json",
            **self.token_header,
        )

        self.assertEqual(response.status_code, 200, response.data)
        self.task.refresh_from_db()
        application.refresh_from_db()
        self.assertEqual(self.task.status, RpaTask.Status.WAITING_HUMAN)
        self.assertEqual(application.stage, JobApplication.Stage.NEW)
        self.assertFalse(Resume.objects.exists())

    def test_conversation_completion_persists_all_messages_and_observation_attention(self):
        job = RecruitmentJob.objects.create(
            boss_account=self.account,
            external_id="conversation-job",
            title="产品经理",
            owner=self.hr,
        )
        candidate = Candidate.objects.create(identity_key="conversation-worker", name="林然")
        JobApplication.objects.create(candidate=candidate, job=job, source="boss")
        self.task.action = RpaTask.Action.SYNC_CONVERSATIONS
        self.task.request_payload = {"job": job.pk, "job_title": job.title}
        self.task.save(update_fields=["action", "request_payload"])
        self.heartbeat()
        lease = self.client.post(
            "/api/recruitment/worker/tasks/lease/",
            {"worker_key": "local-worker"}, format="json", **self.token_header,
        )

        response = self.client.post(
            f"/api/recruitment/worker/tasks/{lease.data['task']['id']}/complete/",
            {
                "worker_key": "local-worker",
                "status": "succeeded",
                "result": {"conversations": [{
                    "name": "林然",
                    "messages": [
                        {"direction": "candidate", "content": "你好", "sent_at": "2026-08-25T09:00:00+08:00"},
                        {"direction": "hr", "content": "您好", "sent_at": "2026-08-25T09:01:00+08:00"},
                        {"direction": "candidate", "content": "我想先了解一下公司", "sent_at": "2026-08-25T09:02:00+08:00"},
                    ],
                    "attachments": [],
                }]},
            },
            format="json",
            **self.token_header,
        )

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(ConversationMessage.objects.count(), 3)
        self.assertEqual(HumanAttention.objects.get().attention_type, HumanAttention.Type.OBSERVING_CANDIDATE)

    def test_ordinary_candidate_message_creates_draft_resume_request_confirmation(self):
        AccountProfile.objects.create(user=self.hr, role=AccountProfile.Role.HR)
        self.account.authorized_users.add(self.hr)
        job = RecruitmentJob.objects.create(
            boss_account=self.account,
            external_id="resume-request-job",
            title="测试工程师",
            owner=self.hr,
        )
        candidate = Candidate.objects.create(
            identity_key="resume-request-candidate",
            external_id="boss-candidate-1",
            name="周青",
        )
        JobApplication.objects.create(candidate=candidate, job=job, source="boss")
        self.task.action = RpaTask.Action.SYNC_CONVERSATIONS
        self.task.request_payload = {"job": job.pk, "job_title": job.title}
        self.task.save(update_fields=["action", "request_payload"])
        self.heartbeat()
        lease = self.client.post(
            "/api/recruitment/worker/tasks/lease/",
            {"worker_key": "local-worker"}, format="json", **self.token_header,
        )

        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(
                f"/api/recruitment/worker/tasks/{lease.data['task']['id']}/complete/",
                {
                    "worker_key": "local-worker",
                    "status": "succeeded",
                    "result": {"conversations": [{
                        "name": "周青",
                        "messages": [{
                            "direction": "candidate",
                            "content": "你好",
                            "sent_at": "2026-08-25T09:00:00+08:00",
                        }],
                        "attachments": [],
                    }]},
                },
                format="json",
                **self.token_header,
            )

        self.assertEqual(response.status_code, 200, response.data)
        self.assertFalse(RpaTask.objects.exclude(pk=self.task.pk).filter(action=RpaTask.Action.REQUEST_RESUME).exists())
        approval = AutomationApproval.objects.get(action=AutomationApproval.Action.REQUEST_RESUME)
        self.assertEqual(approval.status, AutomationApproval.Status.DRAFT)
        self.assertTrue(approval.payload["items"][0]["first_contact"])
        action = ConversationAction.objects.get(approval=approval)
        self.assertEqual(action.target_snapshot["name"], "周青")

    def test_stable_conversation_creates_real_application_and_resume_request_from_zero(self):
        AccountProfile.objects.create(user=self.hr, role=AccountProfile.Role.HR)
        self.account.authorized_users.add(self.hr)
        job = RecruitmentJob.objects.create(
            boss_account=self.account,
            external_id="new-applicant-job",
            title="前置部署工程师",
            owner=self.hr,
        )
        self.task.action = RpaTask.Action.SYNC_CONVERSATIONS
        self.task.request_payload = {"job": job.pk, "job_title": job.title}
        self.task.save(update_fields=["action", "request_payload"])
        self.heartbeat()
        lease = self.client.post(
            "/api/recruitment/worker/tasks/lease/",
            {"worker_key": "local-worker"}, format="json", **self.token_header,
        )

        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(
                f"/api/recruitment/worker/tasks/{lease.data['task']['id']}/complete/",
                {
                    "worker_key": "local-worker",
                    "status": "succeeded",
                    "result": {"conversations": [{
                        "name": "新候选人",
                        "external_id": "conversation-new-101",
                        "application_id": 999999,
                        "job_title": job.title,
                        "messages": [{
                            "direction": "candidate",
                            "content": "您好，我已经投递了这个岗位",
                            "sent_at": "2026-08-26T09:00:00+08:00",
                        }],
                        "attachments": [],
                    }]},
                },
                format="json",
                **self.token_header,
            )

        self.assertEqual(response.status_code, 200, response.data)
        application = JobApplication.objects.get(job=job)
        identity = CandidateExternalIdentity.objects.get(candidate=application.candidate)
        self.assertEqual(identity.external_id, "conversation-new-101")
        self.assertEqual(ConversationMessage.objects.get().content, "您好，我已经投递了这个岗位")
        approval = AutomationApproval.objects.get(action=AutomationApproval.Action.REQUEST_RESUME)
        self.assertEqual(approval.payload["items"][0]["external_id"], "conversation-new-101")
        self.assertTrue(approval.payload["items"][0]["first_contact"])
        self.task.refresh_from_db()
        self.assertEqual(self.task.result["sync"]["created_applications"], 1)

    def test_stable_conversation_archives_received_pdf_instead_of_requesting_again(self):
        AccountProfile.objects.create(user=self.hr, role=AccountProfile.Role.HR)
        self.account.authorized_users.add(self.hr)
        job = RecruitmentJob.objects.create(
            boss_account=self.account,
            external_id="received-resume-job",
            title="前置部署工程师",
            owner=self.hr,
        )
        self.task.action = RpaTask.Action.SYNC_CONVERSATIONS
        self.task.request_payload = {"job": job.pk, "job_title": job.title}
        self.task.save(update_fields=["action", "request_payload"])
        self.heartbeat()
        lease = self.client.post(
            "/api/recruitment/worker/tasks/lease/",
            {"worker_key": "local-worker"}, format="json", **self.token_header,
        )

        with tempfile.TemporaryDirectory() as media_root:
            incoming = Path(media_root) / "rpa-incoming"
            incoming.mkdir()
            downloaded = incoming / "received-resume.pdf"
            downloaded.write_bytes(b"%PDF-1.4\nreceived resume")
            with self.settings(MEDIA_ROOT=media_root), self.captureOnCommitCallbacks(execute=True):
                response = self.client.post(
                    f"/api/recruitment/worker/tasks/{lease.data['task']['id']}/complete/",
                    {
                        "worker_key": "local-worker",
                        "status": "succeeded",
                        "result": {"conversations": [{
                            "name": "已发简历候选人",
                            "external_id": "conversation-resume-101",
                            "job_title": job.title,
                            "messages": [{
                                "direction": "candidate",
                                "content": "简历已发，请查收",
                                "sent_at": "2026-08-26T09:00:00+08:00",
                            }],
                            "attachments": [{
                                "path": str(downloaded),
                                "filename": "候选人简历.pdf",
                            }],
                        }]},
                    },
                    format="json",
                    **self.token_header,
                )

            self.assertEqual(response.status_code, 200, response.data)
            application = JobApplication.objects.get(job=job)
            resume = Resume.objects.get(application=application)
            self.assertEqual(resume.source, Resume.Source.BOSS)
            self.assertFalse(downloaded.exists())
            self.assertFalse(
                AutomationApproval.objects.filter(action=AutomationApproval.Action.REQUEST_RESUME).exists()
            )
            self.task.refresh_from_db()
            self.assertEqual(self.task.result["sync"]["attachments_archived"], 1)

    def test_search_campaign_completion_returns_applications_for_next_workflow_node(self):
        job = RecruitmentJob.objects.create(
            boss_account=self.account, external_id="search-pull-job", title="数据工程师", owner=self.hr,
        )
        campaign = SearchCampaign.objects.create(
            name="数据岗位主动寻访", boss_account=self.account, job=job, source="search",
            status=SearchCampaign.Status.RUNNING, target_resume_count=1, max_scan_count=10,
            criteria={"keyword": "Python"}, created_by=self.hr,
        )
        self.task.action = RpaTask.Action.SEARCH_AND_PULL_RESUMES
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
        self.task.approval = approval
        self.task.request_payload = payload
        self.task.idempotency_key = f"search-campaign:{campaign.pk}:approval:{approval.pk}"
        self.task.save(update_fields=["action", "approval", "request_payload", "idempotency_key"])

        with tempfile.TemporaryDirectory() as media_root, self.settings(MEDIA_ROOT=media_root):
            incoming = Path(media_root) / "rpa-incoming"
            incoming.mkdir(parents=True)
            image_path = incoming / "resume.png"
            image_path.write_bytes(b"\x89PNG\r\n\x1a\nresume-image")
            self.heartbeat()
            lease = self.client.post(
                "/api/recruitment/worker/tasks/lease/", {"worker_key": "local-worker"},
                format="json", **self.token_header,
            )
            row = {
                "display_name": "顾宁", "external_id": "boss-candidate-gu-ning",
                "current_title": "数据开发", "city": "北京",
            }
            identity = {
                "name": "顾宁",
                "external_id": row["external_id"],
                "fingerprint": _fingerprint(self.account.pk, row),
                "verified": True,
                "expected_external_id": row["external_id"],
                "observed_external_id": row["external_id"],
            }
            response = self.client.post(
                f"/api/recruitment/worker/tasks/{lease.data['task']['id']}/complete/",
                {
                    "worker_key": "local-worker", "status": "succeeded",
                    "result": {
                        "candidates": [row], "scanned_count": 1,
                        "view_attempt_count": 1, "resume_view_budget": payload["resume_view_budget"],
                        "attempts": [{
                            "sequence": 1, "timestamp": "2026-08-25T00:00:00+00:00",
                            "name": "顾宁", "fingerprint": identity["fingerprint"],
                            "verified": True, "preview_attempted": True,
                            "outcome": "preview_succeeded", "error_code": "",
                            "expected_external_id": row["external_id"],
                            "observed_external_id": row["external_id"], "error": "",
                        }],
                        "resumes": [{
                            "candidate": row, "identity_snapshot": identity,
                            "path": str(image_path), "filename": "顾宁-在线简历.png",
                        }],
                    },
                }, format="json", **self.token_header,
            )

            self.assertEqual(response.status_code, 200, response.data)
            resume = Resume.objects.get()
            self.assertEqual(resume.source, Resume.Source.BOSS_ONLINE)
            self.assertEqual(resume.content_type, "image/png")
            self.assertFalse(HumanAttention.objects.exists())
            self.task.refresh_from_db()
            self.assertEqual(self.task.result["application_ids"], [resume.application_id])
            campaign.refresh_from_db()
            self.assertEqual(campaign.status, SearchCampaign.Status.SUCCEEDED)
            self.assertEqual(campaign.pulled_resume_count, 1)
            attempts = AutomationEvidence.objects.get(task=self.task, kind="resume_preview_attempts")
            self.assertEqual(attempts.metadata["attempts"][0]["outcome"], "preview_succeeded")
            serialized_evidence = json.dumps(attempts.metadata, ensure_ascii=False)
            self.assertNotIn(row["display_name"], serialized_evidence)
            self.assertNotIn(identity["fingerprint"], serialized_evidence)
            self.assertNotIn(row["external_id"], serialized_evidence)
            self.assertNotIn(str(image_path), serialized_evidence)
            self.assertNotIn("error_message", serialized_evidence)
            self.assertEqual(attempts.metadata["attempts"][0]["sequence"], 1)
            self.assertTrue(attempts.metadata["attempts"][0]["external_id_hash"])
            usage = AutomationEvidence.objects.get(task=self.task, kind="resume_view_usage")
            self.assertEqual(usage.metadata["reserved"], payload["resume_view_budget"])
            self.assertEqual(usage.metadata["actual"], 1)
            self.assertEqual(usage.metadata["unused"], payload["resume_view_budget"] - 1)
            self.assertEqual(usage.metadata["unused_disposition"], "retained_no_refund")

    def test_batch_preview_with_composite_fingerprint_and_empty_platform_id_is_rejected(self):
        job = RecruitmentJob.objects.create(
            boss_account=self.account,
            external_id="search-pull-no-platform-id",
            title="组合指纹负例",
            owner=self.hr,
        )
        campaign = SearchCampaign.objects.create(
            name="组合指纹不得归档",
            boss_account=self.account,
            job=job,
            source="search",
            status=SearchCampaign.Status.RUNNING,
            target_resume_count=1,
            max_scan_count=1,
            criteria={"keyword": "安全"},
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
        self.task.action = RpaTask.Action.SEARCH_AND_PULL_RESUMES
        self.task.approval = approval
        self.task.request_payload = payload
        self.task.idempotency_key = f"search-campaign:{campaign.pk}:approval:{approval.pk}"
        self.task.save(update_fields=["action", "approval", "request_payload", "idempotency_key"])
        self.heartbeat()
        lease = self.client.post(
            "/api/recruitment/worker/tasks/lease/",
            {"worker_key": "local-worker"},
            format="json",
            **self.token_header,
        )
        row = {"display_name": "仅组合指纹", "current_title": "开发", "city": "北京"}
        fingerprint = _fingerprint(self.account.pk, row)

        response = self.client.post(
            f"/api/recruitment/worker/tasks/{lease.data['task']['id']}/complete/",
            {
                "worker_key": "local-worker",
                "status": "succeeded",
                "result": {
                    "candidates": [row],
                    "scanned_count": 1,
                    "view_attempt_count": 1,
                    "resume_view_budget": 1,
                    "attempts": [{
                        "sequence": 1,
                        "timestamp": "2026-08-25T00:00:00+00:00",
                        "name": row["display_name"],
                        "fingerprint": fingerprint,
                        "verified": True,
                        "preview_attempted": True,
                        "outcome": "preview_succeeded",
                        "error_code": "",
                        "expected_external_id": "",
                        "observed_external_id": "",
                        "error": "",
                    }],
                    "resumes": [{
                        "candidate": row,
                        "identity_snapshot": {
                            "name": row["display_name"],
                            "external_id": "",
                            "fingerprint": fingerprint,
                            "verified": True,
                            "expected_external_id": "",
                            "observed_external_id": "",
                        },
                        "path": "must-not-be-read.png",
                        "filename": "must-not-be-created.png",
                    }],
                },
            },
            format="json",
            **self.token_header,
        )

        self.assertEqual(response.status_code, 200, response.data)
        self.task.refresh_from_db()
        campaign.refresh_from_db()
        self.assertEqual(self.task.status, RpaTask.Status.FAILED)
        self.assertEqual(campaign.status, SearchCampaign.Status.FAILED)
        self.assertFalse(Resume.objects.exists())
        self.assertFalse(JobApplication.objects.exists())

    def test_name_only_preview_adapter_preserves_search_results_and_waits_for_human(self):
        job = RecruitmentJob.objects.create(
            boss_account=self.account,
            external_id="search-pull-manual",
            title="平台身份安全",
            owner=self.hr,
        )
        campaign = SearchCampaign.objects.create(
            name="转人工主动寻访",
            boss_account=self.account,
            job=job,
            source="search",
            status=SearchCampaign.Status.RUNNING,
            target_resume_count=1,
            max_scan_count=2,
            criteria={"keyword": "安全"},
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
        self.task.action = RpaTask.Action.SEARCH_AND_PULL_RESUMES
        self.task.approval = approval
        self.task.request_payload = payload
        self.task.idempotency_key = f"search-campaign:{campaign.pk}:approval:{approval.pk}"
        self.task.save(update_fields=["action", "approval", "request_payload", "idempotency_key"])
        self.heartbeat()
        lease = self.client.post(
            "/api/recruitment/worker/tasks/lease/",
            {"worker_key": "local-worker"},
            format="json",
            **self.token_header,
        )
        row = {
            "display_name": "人工复核候选人",
            "external_id": "boss-manual-1",
            "current_title": "安全工程师",
            "city": "北京",
        }
        fingerprint = _fingerprint(self.account.pk, row)

        response = self.client.post(
            f"/api/recruitment/worker/tasks/{lease.data['task']['id']}/complete/",
            {
                "worker_key": "local-worker",
                "status": "waiting_human",
                "error_code": "stable_identity_action_unavailable",
                "error_message": "当前适配器只能按姓名查看在线简历",
                "result": {
                    "candidates": [row],
                    "resumes": [],
                    "scanned_count": 1,
                    "view_attempt_count": 0,
                    "resume_view_budget": payload["resume_view_budget"],
                    "attempts": [{
                        "sequence": 1, "timestamp": "2026-08-25T00:00:00+00:00",
                        "name": row["display_name"],
                        "fingerprint": fingerprint,
                        "verified": True,
                        "preview_attempted": False,
                        "outcome": "stable_action_unavailable",
                        "error_code": "stable_action_unavailable",
                        "expected_external_id": row["external_id"],
                        "observed_external_id": row["external_id"],
                        "error": "当前适配器只能按姓名查看在线简历",
                    }],
                },
            },
            format="json",
            **self.token_header,
        )

        self.assertEqual(response.status_code, 200, response.data)
        self.task.refresh_from_db()
        campaign.refresh_from_db()
        self.assertEqual(self.task.status, RpaTask.Status.WAITING_HUMAN)
        self.assertEqual(campaign.status, SearchCampaign.Status.PAUSED)
        self.assertEqual(CandidateDiscovery.objects.count(), 1)
        self.assertEqual(Resume.objects.count(), 0)
        attempts = AutomationEvidence.objects.get(task=self.task, kind="resume_preview_attempts")
        self.assertNotIn("name", attempts.metadata["attempts"][0])
        self.assertNotIn("fingerprint", attempts.metadata["attempts"][0])
        self.assertEqual(attempts.metadata["attempts"][0]["outcome"], "stable_action_unavailable")
        usage = AutomationEvidence.objects.get(task=self.task, kind="resume_view_usage")
        self.assertEqual(usage.metadata["reserved"], 2)
        self.assertEqual(usage.metadata["actual"], 0)
        self.assertEqual(usage.metadata["unused"], 2)
        self.assertEqual(usage.metadata["unused_disposition"], "retained_no_refund")

    def configure_online_resume_task(self, *, suffix):
        job = RecruitmentJob.objects.create(
            boss_account=self.account,
            external_id=f"online-resume-{suffix}",
            title="在线简历安全测试",
            owner=self.hr,
        )
        candidate = Candidate.objects.create(
            identity_key=f"online-resume-candidate-{suffix}",
            external_id=f"boss-online-{suffix}",
            name="在线候选人",
        )
        application = JobApplication.objects.create(candidate=candidate, job=job, source="boss")
        row = {
            "display_name": candidate.name,
            "external_id": candidate.external_id,
            "current_title": "测试工程师",
            "city": "北京",
        }
        target = {
            "boss_account_id": self.account.pk,
            "candidate_id": candidate.pk,
            "application_id": application.pk,
            "name": candidate.name,
            "external_id": candidate.external_id,
            "fingerprint": _fingerprint(self.account.pk, row),
            "job_id": job.pk,
            "job_title": job.title,
            "verification": {"source": "search", "criteria": {"keyword": "测试"}},
        }
        approval = AutomationApproval.objects.create(
            action=AutomationApproval.Action.VIEW_ONLINE_RESUME,
            boss_account=self.account,
            created_by=self.hr,
            approved_by=self.hr,
            status=AutomationApproval.Status.APPROVED,
            payload={"application_id": application.pk, "target": target},
        )
        self.task.action = RpaTask.Action.VIEW_ONLINE_RESUME
        self.task.approval = approval
        self.task.request_payload = {"application_id": application.pk, "target": target}
        self.task.idempotency_key = f"online-resume-task:{approval.pk}"
        self.task.save(update_fields=["action", "approval", "request_payload", "idempotency_key"])
        return application, target

    def configure_search_pull_task(self, *, suffix, max_scan_count=2):
        job = RecruitmentJob.objects.create(
            boss_account=self.account,
            external_id=f"search-ledger-{suffix}",
            title="主动寻访账本测试",
            owner=self.hr,
        )
        campaign = SearchCampaign.objects.create(
            name=f"主动寻访账本-{suffix}",
            boss_account=self.account,
            job=job,
            source="search",
            status=SearchCampaign.Status.RUNNING,
            target_resume_count=1,
            max_scan_count=max_scan_count,
            criteria={"keyword": "安全"},
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
        self.task.action = RpaTask.Action.SEARCH_AND_PULL_RESUMES
        self.task.approval = approval
        self.task.request_payload = payload
        self.task.idempotency_key = f"search-campaign:{campaign.pk}:approval:{approval.pk}"
        self.task.save(update_fields=["action", "approval", "request_payload", "idempotency_key"])
        return campaign, payload

    def test_search_checkpoint_stop_is_cancelled_not_reported_as_natural_success(self):
        campaign, payload = self.configure_search_pull_task(suffix="checkpoint-stopped")
        self.heartbeat()
        lease = self.client.post(
            "/api/recruitment/worker/tasks/lease/",
            {"worker_key": "local-worker"},
            format="json",
            **self.token_header,
        )

        response = self.client.post(
            f"/api/recruitment/worker/tasks/{lease.data['task']['id']}/complete/",
            {
                "worker_key": "local-worker",
                "status": "succeeded",
                "result": {
                    "candidates": [],
                    "resumes": [],
                    "scanned_count": 0,
                    "view_attempt_count": 0,
                    "resume_view_budget": payload["resume_view_budget"],
                    "attempts": [],
                    "checkpoint_stopped": True,
                },
            },
            format="json",
            **self.token_header,
        )

        self.assertEqual(response.status_code, 200, response.data)
        self.task.refresh_from_db()
        campaign.refresh_from_db()
        self.assertEqual(self.task.status, RpaTask.Status.CANCELLED)
        self.assertEqual(campaign.status, SearchCampaign.Status.CANCELLED)
        self.assertEqual(campaign.stop_reason, SearchCampaign.StopReason.USER_STOPPED)
        self.assertEqual(self.task.result["pulled_resume_count"], 0)

    def test_worker_reported_search_failure_persists_unknown_safe_quota_ledger(self):
        campaign, payload = self.configure_search_pull_task(suffix="worker-failed")
        self.heartbeat()
        lease = self.client.post(
            "/api/recruitment/worker/tasks/lease/",
            {"worker_key": "local-worker"},
            format="json",
            **self.token_header,
        )
        secret_name = "不得持久化的候选人姓名"
        secret_path = "C:/private/incoming/secret-resume.png"

        response = self.client.post(
            f"/api/recruitment/worker/tasks/{lease.data['task']['id']}/complete/",
            {
                "worker_key": "local-worker",
                "status": "failed",
                "error_code": "raw-worker-error",
                "error_message": "Worker 执行失败",
                "result": {
                    "candidates": [{"display_name": secret_name}],
                    "attempts": [{"name": secret_name, "path": secret_path}],
                    "view_attempt_count": 99,
                },
            },
            format="json",
            **self.token_header,
        )

        self.assertEqual(response.status_code, 200, response.data)
        self.task.refresh_from_db()
        campaign.refresh_from_db()
        self.assertEqual(self.task.status, RpaTask.Status.FAILED)
        self.assertEqual(self.task.error_code, "worker_reported_failure")
        self.assertEqual(campaign.status, SearchCampaign.Status.FAILED)
        usage = AutomationEvidence.objects.get(task=self.task, kind="resume_view_usage")
        attempts = AutomationEvidence.objects.get(task=self.task, kind="resume_preview_attempts")
        self.assertEqual(usage.metadata["reserved"], payload["resume_view_budget"])
        self.assertFalse(usage.metadata["actual_known"])
        self.assertTrue(usage.metadata["actual_unknown"])
        self.assertIsNone(usage.metadata["actual"])
        self.assertIsNone(usage.metadata["unused"])
        self.assertEqual(usage.metadata["unused_disposition"], "retained_no_refund")
        self.assertEqual(usage.metadata["failure_code"], "worker_reported_failure")
        self.assertTrue(usage.metadata["evidence_untrusted"])
        self.assertEqual(attempts.metadata["attempts"], [])
        serialized = json.dumps([usage.metadata, attempts.metadata], ensure_ascii=False)
        self.assertNotIn(secret_name, serialized)
        self.assertNotIn(secret_path, serialized)
        self.assertNotIn("raw-worker-error", serialized)

    def test_invalid_search_result_before_safe_context_persists_unknown_ledger(self):
        campaign, payload = self.configure_search_pull_task(suffix="invalid-result")
        self.heartbeat()
        lease = self.client.post(
            "/api/recruitment/worker/tasks/lease/",
            {"worker_key": "local-worker"},
            format="json",
            **self.token_header,
        )
        secret_name = "不可信回执姓名"
        secret_path = "C:/private/incoming/untrusted.png"

        response = self.client.post(
            f"/api/recruitment/worker/tasks/{lease.data['task']['id']}/complete/",
            {
                "worker_key": "local-worker",
                "status": "succeeded",
                "result": {
                    "candidates": "not-a-list",
                    "resumes": [],
                    "attempts": [{"name": secret_name, "path": secret_path}],
                    "scanned_count": 0,
                    "view_attempt_count": 0,
                    "resume_view_budget": payload["resume_view_budget"],
                },
            },
            format="json",
            **self.token_header,
        )

        self.assertEqual(response.status_code, 200, response.data)
        self.task.refresh_from_db()
        campaign.refresh_from_db()
        self.assertEqual(self.task.status, RpaTask.Status.FAILED)
        self.assertEqual(self.task.error_code, "search_pull_result_invalid")
        self.assertEqual(campaign.status, SearchCampaign.Status.FAILED)
        usage = AutomationEvidence.objects.get(task=self.task, kind="resume_view_usage")
        attempts = AutomationEvidence.objects.get(task=self.task, kind="resume_preview_attempts")
        self.assertEqual(usage.metadata["reserved"], payload["resume_view_budget"])
        self.assertFalse(usage.metadata["actual_known"])
        self.assertIsNone(usage.metadata["actual"])
        self.assertIsNone(usage.metadata["unused"])
        self.assertEqual(usage.metadata["failure_code"], "search_pull_result_invalid")
        self.assertTrue(usage.metadata["evidence_untrusted"])
        self.assertEqual(attempts.metadata["attempts"], [])
        serialized = json.dumps([usage.metadata, attempts.metadata], ensure_ascii=False)
        self.assertNotIn(secret_name, serialized)
        self.assertNotIn(secret_path, serialized)

    def test_search_campaign_completion_rejects_unverified_resume_identity(self):
        job = RecruitmentJob.objects.create(
            boss_account=self.account, external_id="search-pull-invalid", title="安全测试", owner=self.hr,
        )
        campaign = SearchCampaign.objects.create(
            name="身份复核", boss_account=self.account, job=job, source="search",
            status=SearchCampaign.Status.RUNNING, target_resume_count=1, max_scan_count=2,
            criteria={"keyword": "安全"}, created_by=self.hr,
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
        self.task.action = RpaTask.Action.SEARCH_AND_PULL_RESUMES
        self.task.approval = approval
        self.task.request_payload = payload
        self.task.idempotency_key = f"search-campaign:{campaign.pk}:approval:{approval.pk}"
        self.task.save(update_fields=["action", "approval", "request_payload", "idempotency_key"])
        self.heartbeat()
        lease = self.client.post(
            "/api/recruitment/worker/tasks/lease/",
            {"worker_key": "local-worker"}, format="json", **self.token_header,
        )
        row = {
            "display_name": "同名候选人", "external_id": "boss-invalid-identity",
            "current_title": "开发", "city": "北京",
        }
        fingerprint = _fingerprint(self.account.pk, row)

        response = self.client.post(
            f"/api/recruitment/worker/tasks/{lease.data['task']['id']}/complete/",
            {
                "worker_key": "local-worker", "status": "succeeded",
                "result": {
                    "candidates": [row], "scanned_count": 1,
                    "view_attempt_count": 1, "resume_view_budget": payload["resume_view_budget"],
                    "attempts": [{
                        "sequence": 1, "timestamp": "2026-08-25T00:00:00+00:00",
                        "name": "同名候选人", "fingerprint": fingerprint,
                        "verified": True, "preview_attempted": True,
                        "outcome": "preview_succeeded", "error_code": "",
                        "expected_external_id": row["external_id"],
                        "observed_external_id": row["external_id"], "error": "",
                    }],
                    "resumes": [{
                        "candidate": row,
                        "identity_snapshot": {
                            "name": "同名候选人", "external_id": row["external_id"],
                            "expected_external_id": row["external_id"],
                            "observed_external_id": "boss-wrong-observed-id",
                            "fingerprint": fingerprint, "verified": True,
                        },
                        "path": "ignored.png", "filename": "ignored.png",
                    }],
                },
            },
            format="json",
            **self.token_header,
        )

        self.assertEqual(response.status_code, 200)
        campaign.refresh_from_db()
        self.task.refresh_from_db()
        self.assertEqual(campaign.status, SearchCampaign.Status.FAILED)
        self.assertEqual(self.task.status, RpaTask.Status.FAILED)
        self.assertFalse(Resume.objects.exists())

    def test_search_campaign_second_archive_failure_rolls_back_every_business_write(self):
        job = RecruitmentJob.objects.create(
            boss_account=self.account,
            external_id="search-pull-rollback",
            title="事务安全测试",
            owner=self.hr,
        )
        campaign = SearchCampaign.objects.create(
            name="批量归档回滚",
            boss_account=self.account,
            job=job,
            source="search",
            status=SearchCampaign.Status.RUNNING,
            target_resume_count=2,
            max_scan_count=2,
            criteria={"keyword": "事务"},
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
        self.task.action = RpaTask.Action.SEARCH_AND_PULL_RESUMES
        self.task.approval = approval
        self.task.request_payload = payload
        self.task.idempotency_key = f"search-campaign:{campaign.pk}:approval:{approval.pk}"
        self.task.save(update_fields=["action", "approval", "request_payload", "idempotency_key"])
        rows = [
            {
                "display_name": "候选人甲", "external_id": "boss-rollback-1",
                "current_title": "后端工程师", "city": "北京",
            },
            {
                "display_name": "候选人乙", "external_id": "boss-rollback-2",
                "current_title": "后端工程师", "city": "上海",
            },
        ]
        fingerprints = [_fingerprint(self.account.pk, row) for row in rows]

        with tempfile.TemporaryDirectory() as media_root, self.settings(MEDIA_ROOT=media_root):
            incoming = Path(media_root) / "rpa-incoming"
            incoming.mkdir(parents=True)
            paths = [incoming / "first.png", incoming / "second.png"]
            paths[0].write_bytes(b"\x89PNG\r\n\x1a\nfirst")
            paths[1].write_bytes(b"\x89PNG\r\n\x1a\nsecond")
            self.heartbeat()
            lease = self.client.post(
                "/api/recruitment/worker/tasks/lease/",
                {"worker_key": "local-worker"},
                format="json",
                **self.token_header,
            )
            archive_calls = 0

            def fail_second_archive(**kwargs):
                nonlocal archive_calls
                archive_calls += 1
                if archive_calls == 2:
                    raise RuntimeError("injected second archive failure")
                return real_archive_online_resume_image(**kwargs)

            result = {
                "candidates": rows,
                "scanned_count": 2,
                "view_attempt_count": 2,
                "resume_view_budget": payload["resume_view_budget"],
                "attempts": [
                    {
                        "sequence": index,
                        "timestamp": f"2026-08-25T00:00:0{index}+00:00",
                        "name": row["display_name"],
                        "fingerprint": fingerprint,
                        "verified": True,
                        "preview_attempted": True,
                        "outcome": "preview_succeeded",
                        "error_code": "",
                        "expected_external_id": row["external_id"],
                        "observed_external_id": row["external_id"],
                        "error": "",
                    }
                    for index, (row, fingerprint) in enumerate(zip(rows, fingerprints), start=1)
                ],
                "resumes": [
                    {
                        "candidate": row,
                        "identity_snapshot": {
                            "name": row["display_name"],
                            "external_id": row["external_id"],
                            "expected_external_id": row["external_id"],
                            "observed_external_id": row["external_id"],
                            "fingerprint": fingerprint,
                            "verified": True,
                        },
                        "path": str(path),
                        "filename": f"{row['display_name']}-在线简历.png",
                    }
                    for row, fingerprint, path in zip(rows, fingerprints, paths)
                ],
            }
            with patch(
                "recruitment.worker_api.archive_online_resume_image",
                side_effect=fail_second_archive,
            ):
                response = self.client.post(
                    f"/api/recruitment/worker/tasks/{lease.data['task']['id']}/complete/",
                    {"worker_key": "local-worker", "status": "succeeded", "result": result},
                    format="json",
                    **self.token_header,
                )

            self.assertEqual(response.status_code, 200, response.data)
            self.assertEqual(response.data["status"], RpaTask.Status.FAILED)
            self.task.refresh_from_db()
            campaign.refresh_from_db()
            self.assertEqual(self.task.status, RpaTask.Status.FAILED)
            self.assertEqual(campaign.status, SearchCampaign.Status.FAILED)
            self.assertEqual(CandidateDiscovery.objects.count(), 0)
            self.assertEqual(CandidateExternalIdentity.objects.count(), 0)
            self.assertEqual(Candidate.objects.count(), 0)
            self.assertEqual(JobApplication.objects.count(), 0)
            self.assertEqual(Resume.objects.count(), 0)
            self.assertEqual(RecruitmentAuditLog.objects.count(), 0)
            archived_root = Path(media_root) / "recruitment" / "resumes"
            self.assertEqual(list(archived_root.rglob("*.png")) if archived_root.exists() else [], [])
            self.assertTrue(all(path.exists() for path in paths))
            self.assertTrue(self.task.events.filter(event="failed").exists())
            attempts = AutomationEvidence.objects.get(task=self.task, kind="resume_preview_attempts")
            self.assertEqual(len(attempts.metadata["attempts"]), 2)
            usage = AutomationEvidence.objects.get(task=self.task, kind="resume_view_usage")
            self.assertEqual(usage.metadata["reserved"], 2)
            self.assertEqual(usage.metadata["actual"], 2)
            self.assertEqual(usage.metadata["unused"], 0)
            self.assertEqual(usage.metadata["unused_disposition"], "retained_no_refund")

            replay = self.client.post(
                f"/api/recruitment/worker/tasks/{lease.data['task']['id']}/complete/",
                {"worker_key": "local-worker", "status": "succeeded", "result": result},
                format="json",
                **self.token_header,
            )
            self.assertEqual(replay.status_code, 409)
            self.assertEqual(AutomationEvidence.objects.filter(task=self.task).count(), 2)
