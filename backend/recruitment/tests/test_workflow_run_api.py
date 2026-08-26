from django.contrib.auth.models import User
from django.utils import timezone
from rest_framework.test import APITestCase

from attendance.models import AccountProfile
from recruitment.models import (
    AutomationApproval,
    AutomationUsage,
    BossAccount,
    Candidate,
    ConversationAction,
    ExecutionBatch,
    JobApplication,
    RecruitmentAuditLog,
    RecruitmentJob,
    RpaTask,
    RpaWorker,
    SearchCampaign,
    WorkflowNodeRun,
    WorkflowRun,
    WorkflowTemplate,
)
from recruitment.services.conversation_ingestion import ingest_conversation
from recruitment.services.workflow_nodes import execute_workflow_node, resume_workflow_for_task
from recruitment.services.workflow_runtime import advance_run, create_run
from recruitment.services.workflows import create_version, enable_version


class WorkflowRunApiTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user("run-api")
        AccountProfile.objects.create(user=self.user, role=AccountProfile.Role.HR)
        self.other = User.objects.create_user("run-api-other")
        AccountProfile.objects.create(user=self.other, role=AccountProfile.Role.HR)
        self.account = BossAccount.objects.create(
            name="run-api", browser_profile="run-api", cdp_port=53904,
            login_status=BossAccount.LoginStatus.READY, status=BossAccount.Status.READY,
        )
        self.account.authorized_users.add(self.user)
        template = WorkflowTemplate.objects.create(name="API run", created_by=self.user)
        self.version = create_version(
            template=template, boss_account=self.account, actor=self.user,
            nodes=[{"key": "source", "type": "search", "position": {}, "config": {}}, {"key": "gate", "type": "human_screen", "position": {}, "config": {}}, {"key": "end", "type": "end", "position": {}, "config": {}}],
            edges=[{"source": "source", "target": "gate"}, {"source": "gate", "target": "end"}],
        )
        self.client.force_authenticate(self.user)

    def _create_message_approval_run(self):
        job = RecruitmentJob.objects.create(
            boss_account=self.account,
            external_id=f"message-{RecruitmentJob.objects.count()}",
            title="测试工程师",
            owner=self.user,
        )
        candidate = Candidate.objects.create(
            identity_key=f"message-candidate-{Candidate.objects.count()}",
            external_id="boss-message-candidate",
            name="周青",
        )
        application = JobApplication.objects.create(candidate=candidate, job=job, source="boss")
        ingest_conversation(
            application=application,
            account=self.account,
            messages=[{"external_id": "message-1", "direction": "candidate", "content": "你好"}],
        )
        template = WorkflowTemplate.objects.create(name="求简历审批", created_by=self.user)
        version = create_version(
            template=template,
            boss_account=self.account,
            actor=self.user,
            nodes=[
                {"key": "sync", "type": "sync_messages", "position": {}, "config": {}},
                {"key": "intent", "type": "classify_intent", "position": {}, "config": {}},
                {"key": "gate", "type": "human_approval", "position": {}, "config": {}},
                {"key": "request", "type": "request_resume", "position": {}, "config": {"message": "请发送简历"}},
                {"key": "end", "type": "end", "position": {}, "config": {}},
            ],
            edges=[
                {"source": "sync", "target": "intent"},
                {"source": "intent", "target": "gate", "condition": {"intent": "request_resume"}},
                {"source": "gate", "target": "request"},
                {"source": "request", "target": "end"},
            ],
        )
        run = create_run(
            version=version,
            actor=self.user,
            mode=WorkflowRun.Mode.FORMAL,
            idempotency_key=f"message-run-{version.pk}",
            job=job,
        )
        run.node_runs.filter(node_key="sync").update(status=WorkflowNodeRun.Status.SUCCEEDED)
        return advance_run(run, executor=execute_workflow_node)

    def _create_search_approval_run(self):
        job = RecruitmentJob.objects.create(
            boss_account=self.account,
            external_id=f"search-{RecruitmentJob.objects.count()}",
            title="数据工程师",
            owner=self.user,
        )
        template = WorkflowTemplate.objects.create(name="主动寻访审批", created_by=self.user)
        version = create_version(
            template=template,
            boss_account=self.account,
            actor=self.user,
            nodes=[
                {"key": "start", "type": "start", "position": {}, "config": {}},
                {
                    "key": "search_pull",
                    "type": "search_and_pull_resumes",
                    "position": {},
                    "config": {
                        "source": "search", "keyword": "Python",
                        "target_resume_count": 1, "max_scan_count": 2,
                    },
                },
                {"key": "end", "type": "end", "position": {}, "config": {}},
            ],
            edges=[
                {"source": "start", "target": "search_pull"},
                {"source": "search_pull", "target": "end"},
            ],
        )
        run = create_run(
            version=version,
            actor=self.user,
            mode=WorkflowRun.Mode.FORMAL,
            idempotency_key=f"search-run-{version.pk}",
            job=job,
        )
        return advance_run(run, executor=execute_workflow_node)

    def _create_deep_match_approval_run(self):
        job = RecruitmentJob.objects.create(
            boss_account=self.account,
            external_id=f"deep-{RecruitmentJob.objects.count()}",
            title="算法工程师",
            owner=self.user,
        )
        template = WorkflowTemplate.objects.create(name="深度匹配审批", created_by=self.user)
        version = create_version(
            template=template,
            boss_account=self.account,
            actor=self.user,
            nodes=[
                {"key": "start", "type": "start", "position": {}, "config": {}},
                {
                    "key": "deep",
                    "type": "deep_search",
                    "position": {},
                    "config": {"core": ["Python"], "bonus": ["推荐系统"]},
                },
                {"key": "end", "type": "end", "position": {}, "config": {}},
            ],
            edges=[
                {"source": "start", "target": "deep"},
                {"source": "deep", "target": "end"},
            ],
        )
        run = create_run(
            version=version,
            actor=self.user,
            mode=WorkflowRun.Mode.FORMAL,
            idempotency_key=f"deep-run-{version.pk}",
            job=job,
        )
        return advance_run(run, executor=execute_workflow_node)

    def test_dry_run_is_idempotent_and_supports_decision(self):
        payload = {"mode": "dry_run", "request_id": "api-dry-1", "input": {}}
        first = self.client.post(f"/api/recruitment/workflow-versions/{self.version.pk}/run/", payload, format="json")
        second = self.client.post(f"/api/recruitment/workflow-versions/{self.version.pk}/run/", payload, format="json")
        self.assertEqual(first.status_code, 201, first.data)
        self.assertEqual(second.status_code, 200, second.data)
        self.assertEqual(first.data["id"], second.data["id"])
        self.assertEqual(first.data["status"], "waiting_human")
        gate = next(node for node in first.data["node_runs"] if node["node_key"] == "gate")
        decided = self.client.post(f"/api/recruitment/workflow-runs/{first.data['id']}/decision/", {"node_id": gate["id"], "approved": True, "note": "ok"}, format="json")
        self.assertEqual(decided.status_code, 200, decided.data)
        self.assertEqual(decided.data["status"], "succeeded")

    def test_formal_run_requires_enabled_version_ready_account_and_confirmation(self):
        rejected = self.client.post(f"/api/recruitment/workflow-versions/{self.version.pk}/run/", {"mode": "formal", "request_id": "formal-1", "confirm": True}, format="json")
        self.assertEqual(rejected.status_code, 400)
        enable_version(version=self.version, actor=self.user)
        unconfirmed = self.client.post(f"/api/recruitment/workflow-versions/{self.version.pk}/run/", {"mode": "formal", "request_id": "formal-2"}, format="json")
        self.assertEqual(unconfirmed.status_code, 400)
        created = self.client.post(f"/api/recruitment/workflow-versions/{self.version.pk}/run/", {"mode": "formal", "request_id": "formal-3", "confirm": True}, format="json")
        self.assertEqual(created.status_code, 201, created.data)

    def test_controls_permissions_and_conflicts(self):
        created = self.client.post(f"/api/recruitment/workflow-versions/{self.version.pk}/run/", {"mode": "dry_run", "request_id": "controls"}, format="json")
        run_id = created.data["id"]
        paused = self.client.post(f"/api/recruitment/workflow-runs/{run_id}/pause/")
        self.assertEqual(paused.status_code, 200)
        resumed = self.client.post(f"/api/recruitment/workflow-runs/{run_id}/resume/")
        self.assertEqual(resumed.status_code, 200)
        cancelled = self.client.post(f"/api/recruitment/workflow-runs/{run_id}/cancel/")
        self.assertEqual(cancelled.status_code, 200)
        conflict = self.client.post(f"/api/recruitment/workflow-runs/{run_id}/pause/")
        self.assertEqual(conflict.status_code, 409)

        self.client.force_authenticate(self.other)
        self.assertEqual(self.client.get(f"/api/recruitment/workflow-runs/{run_id}/").status_code, 404)

    def test_action_decision_approves_communication_snapshot_and_is_idempotent(self):
        run = self._create_message_approval_run()
        gate = run.node_runs.get(node_key="gate")
        gated = self.client.post(
            f"/api/recruitment/workflow-runs/{run.pk}/decision/",
            {"node_id": gate.pk, "approved": True},
            format="json",
        )
        self.assertEqual(gated.status_code, 200, gated.data)
        request_node = run.node_runs.get(node_key="request")
        request_node.refresh_from_db()
        approval = AutomationApproval.objects.get(pk=request_node.output["approval_id"])
        self.assertEqual(approval.status, AutomationApproval.Status.DRAFT)

        approved = self.client.post(
            f"/api/recruitment/workflow-runs/{run.pk}/decision/",
            {"node_id": request_node.pk, "approved": True},
            format="json",
        )

        self.assertEqual(approved.status_code, 200, approved.data)
        request_node.refresh_from_db()
        approval.refresh_from_db()
        self.assertEqual(request_node.status, WorkflowNodeRun.Status.RUNNING)
        self.assertEqual(approval.status, AutomationApproval.Status.APPROVED)
        self.assertEqual(ExecutionBatch.objects.filter(approval=approval).count(), 1)
        self.assertEqual(RpaTask.objects.filter(approval=approval).count(), 1)
        repeated = self.client.post(
            f"/api/recruitment/workflow-runs/{run.pk}/decision/",
            {"node_id": request_node.pk, "approved": True},
            format="json",
        )
        self.assertEqual(repeated.status_code, 409)
        self.assertEqual(ExecutionBatch.objects.filter(approval=approval).count(), 1)
        self.assertEqual(RpaTask.objects.filter(approval=approval).count(), 1)

    def test_deep_search_waits_for_frozen_approval_then_creates_linked_task(self):
        run = self._create_deep_match_approval_run()
        node = run.node_runs.get(node_key="deep")
        approval = AutomationApproval.objects.get(pk=node.output["approval_id"])

        self.assertEqual(run.status, WorkflowRun.Status.WAITING_HUMAN)
        self.assertEqual(node.status, WorkflowNodeRun.Status.WAITING_HUMAN)
        self.assertEqual(approval.status, AutomationApproval.Status.DRAFT)
        self.assertEqual(approval.payload["workflow_node_run_id"], node.pk)
        self.assertEqual(approval.payload["job"], run.job_id)
        self.assertFalse(RpaTask.objects.filter(action=RpaTask.Action.DEEP_MATCH).exists())

        approved = self.client.post(
            f"/api/recruitment/workflow-runs/{run.pk}/decision/",
            {"node_id": node.pk, "approved": True},
            format="json",
        )

        self.assertEqual(approved.status_code, 200, approved.data)
        node.refresh_from_db()
        approval.refresh_from_db()
        task = RpaTask.objects.get(approval=approval)
        self.assertEqual(approval.status, AutomationApproval.Status.APPROVED)
        self.assertEqual(task.action, RpaTask.Action.DEEP_MATCH)
        self.assertEqual(task.workflow_node_run, node)
        self.assertEqual(task.idempotency_key, f"deep-match-task:{approval.pk}")
        self.assertEqual(node.status, WorkflowNodeRun.Status.RUNNING)
        repeated = self.client.post(
            f"/api/recruitment/workflow-runs/{run.pk}/decision/",
            {"node_id": node.pk, "approved": True},
            format="json",
        )
        self.assertEqual(repeated.status_code, 409)
        self.assertEqual(RpaTask.objects.filter(approval=approval).count(), 1)

    def test_search_action_decision_starts_real_task_once_and_skip_rejects_snapshot(self):
        run = self._create_search_approval_run()
        node = run.node_runs.get(node_key="search_pull")
        approval = AutomationApproval.objects.get(pk=node.output["approval_id"])

        approved = self.client.post(
            f"/api/recruitment/workflow-runs/{run.pk}/decision/",
            {"node_id": node.pk, "approved": True},
            format="json",
        )

        self.assertEqual(approved.status_code, 200, approved.data)
        node.refresh_from_db()
        approval.refresh_from_db()
        self.assertEqual(node.status, WorkflowNodeRun.Status.RUNNING)
        self.assertEqual(approval.status, AutomationApproval.Status.APPROVED)
        self.assertEqual(RpaTask.objects.filter(approval=approval).count(), 1)
        self.assertEqual(AutomationUsage.objects.get(metric="search").used, 1)
        self.assertEqual(AutomationUsage.objects.get(metric="resume_view").used, 2)
        repeated = self.client.post(
            f"/api/recruitment/workflow-runs/{run.pk}/decision/",
            {"node_id": node.pk, "approved": True},
            format="json",
        )
        self.assertEqual(repeated.status_code, 409)
        self.assertEqual(RpaTask.objects.filter(approval=approval).count(), 1)

        skipped_run = self._create_search_approval_run()
        skipped_node = skipped_run.node_runs.get(node_key="search_pull")
        skipped_approval = AutomationApproval.objects.get(pk=skipped_node.output["approval_id"])
        skipped = self.client.post(
            f"/api/recruitment/workflow-runs/{skipped_run.pk}/decision/",
            {"node_id": skipped_node.pk, "approved": False, "note": "不执行本次寻访"},
            format="json",
        )
        self.assertEqual(skipped.status_code, 200, skipped.data)
        skipped_node.refresh_from_db()
        skipped_approval.refresh_from_db()
        self.assertEqual(skipped_node.status, WorkflowNodeRun.Status.SKIPPED)
        self.assertEqual(skipped_approval.status, AutomationApproval.Status.REJECTED)
        self.assertFalse(RpaTask.objects.filter(approval=skipped_approval).exists())
        self.assertTrue(RecruitmentAuditLog.objects.filter(
            action="automation_approval_rejected", target_id=str(skipped_approval.pk),
        ).exists())

    def test_cancelling_workflow_search_task_terminates_node_and_run_after_commit(self):
        run = self._create_search_approval_run()
        node = run.node_runs.get(node_key="search_pull")
        approved = self.client.post(
            f"/api/recruitment/workflow-runs/{run.pk}/decision/",
            {"node_id": node.pk, "approved": True},
            format="json",
        )
        self.assertEqual(approved.status_code, 200, approved.data)
        task = RpaTask.objects.get(workflow_node_run=node)
        campaign = SearchCampaign.objects.get(workflow_run=run)

        with self.captureOnCommitCallbacks(execute=True):
            rejected = self.client.post(
                f"/api/recruitment/rpa-tasks/{task.pk}/cancel/",
                {},
                format="json",
            )
            cancelled = self.client.post(
                f"/api/recruitment/workflow-runs/{run.pk}/cancel/",
                {},
                format="json",
            )

        self.assertEqual(rejected.status_code, 409, rejected.data)
        self.assertEqual(cancelled.status_code, 200, cancelled.data)
        task.refresh_from_db()
        campaign.refresh_from_db()
        node.refresh_from_db()
        run.refresh_from_db()
        self.assertEqual(task.status, RpaTask.Status.CANCELLED)
        self.assertEqual(campaign.status, SearchCampaign.Status.CANCELLED)
        self.assertEqual(node.status, WorkflowNodeRun.Status.CANCELLED)
        self.assertEqual(run.status, WorkflowRun.Status.CANCELLED)

    def test_cancelling_waiting_deep_search_rejects_approval_and_blocks_later_execution(self):
        run = self._create_deep_match_approval_run()
        node = run.node_runs.get(node_key="deep")
        approval = AutomationApproval.objects.get(pk=node.output["approval_id"])

        cancelled = self.client.post(f"/api/recruitment/workflow-runs/{run.pk}/cancel/")

        self.assertEqual(cancelled.status_code, 200, cancelled.data)
        run.refresh_from_db()
        node.refresh_from_db()
        approval.refresh_from_db()
        self.assertEqual(run.status, WorkflowRun.Status.CANCELLED)
        self.assertEqual(node.status, WorkflowNodeRun.Status.CANCELLED)
        self.assertIsNotNone(node.completed_at)
        self.assertEqual(approval.status, AutomationApproval.Status.REJECTED)
        late_approval = self.client.post(
            f"/api/recruitment/automation-approvals/{approval.pk}/approve/",
            {},
            format="json",
        )
        self.assertEqual(late_approval.status_code, 400)
        self.assertFalse(RpaTask.objects.filter(approval=approval).exists())

    def test_cancelling_approved_deep_search_cancels_pending_task_before_lease(self):
        run = self._create_deep_match_approval_run()
        node = run.node_runs.get(node_key="deep")
        approved = self.client.post(
            f"/api/recruitment/workflow-runs/{run.pk}/decision/",
            {"node_id": node.pk, "approved": True},
            format="json",
        )
        self.assertEqual(approved.status_code, 200, approved.data)
        task = RpaTask.objects.get(workflow_node_run=node)

        cancelled = self.client.post(f"/api/recruitment/workflow-runs/{run.pk}/cancel/")

        self.assertEqual(cancelled.status_code, 200, cancelled.data)
        task.refresh_from_db()
        node.refresh_from_db()
        run.refresh_from_db()
        self.assertEqual(task.status, RpaTask.Status.CANCELLED)
        self.assertEqual(node.status, WorkflowNodeRun.Status.CANCELLED)
        self.assertIsNotNone(node.completed_at)
        self.assertEqual(run.status, WorkflowRun.Status.CANCELLED)

    def test_cancelling_workflow_requests_cancellation_for_leased_task_but_closes_run(self):
        run = self._create_deep_match_approval_run()
        node = run.node_runs.get(node_key="deep")
        self.client.post(
            f"/api/recruitment/workflow-runs/{run.pk}/decision/",
            {"node_id": node.pk, "approved": True},
            format="json",
        )
        task = RpaTask.objects.get(workflow_node_run=node)
        worker = RpaWorker.objects.create(key="already-started", hostname="LOCAL")
        task.status = RpaTask.Status.LEASED
        task.worker = worker
        task.lease_expires_at = timezone.now()
        task.save(update_fields=["status", "worker", "lease_expires_at", "updated_at"])

        cancelled = self.client.post(f"/api/recruitment/workflow-runs/{run.pk}/cancel/")

        self.assertEqual(cancelled.status_code, 200, cancelled.data)
        task.refresh_from_db()
        node.refresh_from_db()
        run.refresh_from_db()
        self.assertEqual(task.status, RpaTask.Status.CANCEL_REQUESTED)
        self.assertTrue(task.events.filter(event="cancel_requested").exists())
        self.assertEqual(node.status, WorkflowNodeRun.Status.RUNNING)
        self.assertEqual(run.status, WorkflowRun.Status.CANCELLED)

    def test_cancelling_workflow_communication_closes_batch_steps_and_task(self):
        run = self._create_message_approval_run()
        gate = run.node_runs.get(node_key="gate")
        self.client.post(
            f"/api/recruitment/workflow-runs/{run.pk}/decision/",
            {"node_id": gate.pk, "approved": True},
            format="json",
        )
        node = run.node_runs.get(node_key="request")
        approved = self.client.post(
            f"/api/recruitment/workflow-runs/{run.pk}/decision/",
            {"node_id": node.pk, "approved": True},
            format="json",
        )
        self.assertEqual(approved.status_code, 200, approved.data)
        task = RpaTask.objects.get(workflow_node_run=node)
        batch = ExecutionBatch.objects.get(workflow_node_run=node)
        action = ConversationAction.objects.get(batch=batch)

        cancelled = self.client.post(f"/api/recruitment/workflow-runs/{run.pk}/cancel/")

        self.assertEqual(cancelled.status_code, 200, cancelled.data)
        task.refresh_from_db()
        batch.refresh_from_db()
        action.refresh_from_db()
        action.step.refresh_from_db()
        node.refresh_from_db()
        self.assertEqual(task.status, RpaTask.Status.CANCELLED)
        self.assertEqual(batch.status, ExecutionBatch.Status.CANCELLED)
        self.assertEqual(action.status, ConversationAction.Status.CANCELLED)
        self.assertEqual(action.step.status, "cancelled")
        self.assertEqual(node.status, WorkflowNodeRun.Status.CANCELLED)

    def test_direct_search_campaign_stop_resumes_and_cancels_workflow(self):
        run = self._create_search_approval_run()
        node = run.node_runs.get(node_key="search_pull")
        self.client.post(
            f"/api/recruitment/workflow-runs/{run.pk}/decision/",
            {"node_id": node.pk, "approved": True},
            format="json",
        )
        campaign = SearchCampaign.objects.get(workflow_run=run)

        with self.captureOnCommitCallbacks(execute=True):
            stopped = self.client.post(f"/api/recruitment/search-campaigns/{campaign.pk}/stop/")

        self.assertEqual(stopped.status_code, 200, stopped.data)
        node.refresh_from_db()
        run.refresh_from_db()
        self.assertEqual(node.status, WorkflowNodeRun.Status.CANCELLED)
        self.assertIsNotNone(node.completed_at)
        self.assertEqual(run.status, WorkflowRun.Status.CANCELLED)

    def test_deep_search_retry_creates_new_attempt_approval_and_task_then_succeeds(self):
        run = self._create_deep_match_approval_run()
        node = run.node_runs.get(node_key="deep")
        first_approval = AutomationApproval.objects.get(pk=node.output["approval_id"])
        self.client.post(
            f"/api/recruitment/workflow-runs/{run.pk}/decision/",
            {"node_id": node.pk, "approved": True},
            format="json",
        )
        first_task = RpaTask.objects.get(approval=first_approval)
        first_task.status = RpaTask.Status.FAILED
        first_task.error_code = "temporary"
        first_task.completed_at = timezone.now()
        first_task.save(update_fields=["status", "error_code", "completed_at", "updated_at"])
        resume_workflow_for_task(first_task)

        retried = self.client.post(
            f"/api/recruitment/workflow-runs/{run.pk}/retry/",
            {"node_id": node.pk},
            format="json",
        )

        self.assertEqual(retried.status_code, 200, retried.data)
        node.refresh_from_db()
        run.refresh_from_db()
        second_approval = AutomationApproval.objects.get(pk=node.output["approval_id"])
        self.assertNotEqual(second_approval.pk, first_approval.pk)
        self.assertEqual(node.attempt, 1)
        self.assertEqual(second_approval.payload["workflow_node_attempt"], 1)
        self.assertEqual(node.status, WorkflowNodeRun.Status.WAITING_HUMAN)
        self.assertEqual(run.status, WorkflowRun.Status.WAITING_HUMAN)

        approved = self.client.post(
            f"/api/recruitment/workflow-runs/{run.pk}/decision/",
            {"node_id": node.pk, "approved": True},
            format="json",
        )
        self.assertEqual(approved.status_code, 200, approved.data)
        second_task = RpaTask.objects.get(approval=second_approval)
        self.assertNotEqual(second_task.pk, first_task.pk)
        self.assertEqual(second_task.workflow_node_run, node)
        second_task.status = RpaTask.Status.SUCCEEDED
        second_task.result = {"sync": {"created": 1}}
        second_task.completed_at = timezone.now()
        second_task.save(update_fields=["status", "result", "completed_at", "updated_at"])
        resume_workflow_for_task(second_task)
        node.refresh_from_db()
        run.refresh_from_db()
        self.assertEqual(node.status, WorkflowNodeRun.Status.SUCCEEDED)
        self.assertEqual(run.status, WorkflowRun.Status.SUCCEEDED)
        self.assertEqual(RpaTask.objects.filter(workflow_node_run=node).count(), 2)
