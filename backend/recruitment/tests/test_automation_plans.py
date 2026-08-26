import uuid
from datetime import timedelta
from pathlib import Path
import tempfile

from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APITestCase

from attendance.models import AccountProfile
from recruitment.models import (
    AutomationApproval,
    ApplicationStageHistory,
    BossAccount,
    Candidate,
    ConversationAction,
    ExecutionBatch,
    HumanAttention,
    JobApplication,
    MessageSyncPolicy,
    RecruitmentAutomationPlan,
    RecruitmentJob,
    RpaTask,
    RpaWorker,
    SearchCampaign,
    WorkflowRun,
    WorkflowTemplate,
)


class AutomationPlanApiTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user("automation-plan-hr")
        AccountProfile.objects.create(user=self.user, role=AccountProfile.Role.HR)
        self.account = BossAccount.objects.create(
            name="方案生命周期账号",
            browser_profile="automation-plan-api",
            cdp_port=54101,
            login_status=BossAccount.LoginStatus.READY,
            status=BossAccount.Status.READY,
        )
        self.account.authorized_users.add(self.user)
        self.job = RecruitmentJob.objects.create(
            boss_account=self.account,
            external_id="plan-job",
            title="高级产品经理",
            owner=self.user,
        )
        RpaWorker.objects.create(
            key="automation-plan-worker",
            hostname="localhost",
            status=RpaWorker.Status.ONLINE,
            last_seen_at=timezone.now(),
            capabilities={"boss_cli": True},
        )
        self.client.force_authenticate(self.user)

    def _start(
        self, *, request_id=None, expected=None, kind="active_resume_search", job=None,
        workflow_version=None, config=None,
    ):
        job = job or self.job
        payload = {
            "job": job.pk,
            "kind": kind,
            "request_id": str(request_id or uuid.uuid4()),
            "config": config if config is not None else (
                {
                    "source": "search",
                    "keyword": "SaaS",
                    "target_resume_count": 2,
                    "max_scan_count": 10,
                    "core": ["B 端产品"],
                    "bonus": [],
                }
                if kind == "active_resume_search"
                else {
                    "interval_minutes": 3,
                    "reply_message": "您好，方便发送一份简历吗？",
                    "core": [],
                    "bonus": [],
                }
            ),
        }
        if expected is not None:
            payload["expected_control_version"] = expected
        if workflow_version is not None:
            payload["workflow_version"] = workflow_version
        return self.client.post(
            "/api/recruitment/automation-plans/start/", payload, format="json"
        )

    def _stop(self, plan):
        plan.refresh_from_db()
        return self.client.post(
            f"/api/recruitment/automation-plans/{plan.pk}/stop/",
            {
                "request_id": str(uuid.uuid4()),
                "expected_control_version": plan.control_version,
            },
            format="json",
        )

    def test_first_start_defaults_version_zero_and_returns_nested_current_state(self):
        response = self._start()

        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(RecruitmentAutomationPlan.objects.filter(job=self.job).count(), 1)
        self.assertEqual(response.data["control_version"], 1)
        self.assertEqual(response.data["current_revision"]["revision"], 1)
        self.assertEqual(response.data["current_revision"]["config"]["target_resume_count"], 2)
        self.assertEqual(response.data["current_revision"]["workflow_mode"], "managed")
        self.assertTrue(response.data["current_revision"]["is_managed_workflow"])
        self.assertEqual(
            response.data["current_run"],
            {
                "id": str(RecruitmentAutomationPlan.objects.get(job=self.job).current_run_id),
                "status": "waiting_human",
            },
        )
        self.assertEqual(response.data["effective_state"], "waiting_human")

    def test_running_or_waiting_plan_cannot_be_hot_replaced(self):
        first = self._start()
        response = self._start(expected=first.data["control_version"])

        self.assertEqual(response.status_code, 409, response.data)
        self.assertEqual(RecruitmentAutomationPlan.objects.get(job=self.job).revisions.count(), 1)

    def test_active_candidate_filters_are_normalized_and_frozen_through_campaign_approval(self):
        response = self._start(config={
            "source": "search",
            "keyword": "SaaS",
            "target_resume_count": 2,
            "max_scan_count": 10,
            "core": ["B 端产品"],
            "bonus": [],
            "candidate_filters": {
                "age_min": 24,
                "age_max": 35,
                "activity": "today",
                "gender": "female",
                "school": "unknown-school",
                "talent_keywords": ["data_analysis", "new_media", "data_analysis", "unknown"],
            },
        })

        self.assertEqual(response.status_code, 201, response.data)
        filters = response.data["current_revision"]["config"]["candidate_filters"]
        self.assertEqual(filters["age_min"], 24)
        self.assertEqual(filters["age_max"], 35)
        self.assertEqual(filters["activity"], "today")
        self.assertEqual(filters["gender"], "female")
        self.assertEqual(filters["school"], "any")
        self.assertEqual(filters["talent_keywords"], ["data_analysis", "new_media"])
        campaign = SearchCampaign.objects.get(job=self.job)
        self.assertEqual(campaign.criteria["candidate_filters"], filters)
        approval = AutomationApproval.objects.get(automation_plan_revision=campaign.automation_plan_revision)
        self.assertEqual(approval.payload["criteria"]["candidate_filters"], filters)

    def test_active_candidate_filters_reject_incomplete_age_range(self):
        response = self._start(config={
            "source": "search",
            "keyword": "SaaS",
            "target_resume_count": 2,
            "max_scan_count": 10,
            "core": ["B 端产品"],
            "bonus": [],
            "candidate_filters": {"age_min": 24, "age_max": None},
        })

        self.assertEqual(response.status_code, 400, response.data)
        self.assertIn("年龄范围", str(response.data))
        self.assertFalse(RecruitmentAutomationPlan.objects.filter(job=self.job).exists())

    def test_plan_linked_run_cannot_bypass_plan_control_endpoints(self):
        self._start()
        plan = RecruitmentAutomationPlan.objects.get(job=self.job)

        for action in ["pause", "resume", "cancel"]:
            response = self.client.post(
                f"/api/recruitment/workflow-runs/{plan.current_run_id}/{action}/",
                {},
                format="json",
            )
            self.assertEqual(response.status_code, 409, (action, response.data))

        plan.refresh_from_db()
        self.assertEqual(plan.desired_state, RecruitmentAutomationPlan.DesiredState.RUNNING)
        version = plan.current_revision.workflow_version
        formal = self.client.post(
            f"/api/recruitment/workflow-versions/{version.pk}/run/",
            {"mode": "formal", "request_id": "managed-bypass", "confirm": True},
            format="json",
        )
        self.assertEqual(formal.status_code, 409, formal.data)

        template = self.client.get(
            f"/api/recruitment/workflows/{plan.managed_template_id}/"
        )
        self.assertEqual(template.status_code, 200, template.data)
        self.assertTrue(template.data["is_plan_managed"])
        for managed_control in [
            self.client.patch(
                f"/api/recruitment/workflows/{plan.managed_template_id}/",
                {"name": "绕过修改托管流程"},
                format="json",
            ),
            self.client.post(
                f"/api/recruitment/workflows/{plan.managed_template_id}/archive/",
                {},
                format="json",
            ),
            self.client.post(
                f"/api/recruitment/workflow-versions/{version.pk}/enable/",
                {},
                format="json",
            ),
        ]:
            self.assertEqual(managed_control.status_code, 409, managed_control.data)

        campaign = plan.current_revision.search_campaigns.get()
        direct_calls = [
            self.client.patch(
                f"/api/recruitment/search-campaigns/{campaign.pk}/",
                {"name": "绕过修改"},
                format="json",
            ),
            self.client.post(
                f"/api/recruitment/search-campaigns/{campaign.pk}/start/", {}, format="json"
            ),
            self.client.post(
                f"/api/recruitment/search-campaigns/{campaign.pk}/stop/", {}, format="json"
            ),
            self.client.delete(f"/api/recruitment/search-campaigns/{campaign.pk}/"),
        ]
        for response in direct_calls:
            self.assertEqual(response.status_code, 409, response.data)

    def test_stopping_before_active_search_approval_closes_draft_campaign(self):
        self._start()
        plan = RecruitmentAutomationPlan.objects.get(job=self.job)
        campaign = plan.current_revision.search_campaigns.get()
        self.assertEqual(campaign.status, SearchCampaign.Status.DRAFT)

        stopped = self._stop(plan)

        self.assertEqual(stopped.status_code, 200, stopped.data)
        campaign.refresh_from_db()
        self.assertEqual(campaign.status, SearchCampaign.Status.CANCELLED)
        self.assertEqual(campaign.stop_reason, SearchCampaign.StopReason.USER_STOPPED)

    def test_account_active_and_job_account_rebind_cannot_bypass_plan_lifecycle(self):
        self._start()
        other_account = BossAccount.objects.create(
            name="不可重绑账号",
            browser_profile="automation-plan-rebind",
            cdp_port=54103,
            login_status=BossAccount.LoginStatus.READY,
        )
        other_account.authorized_users.add(self.user)

        disabled = self.client.patch(
            f"/api/recruitment/boss-accounts/{self.account.pk}/",
            {"active": False},
            format="json",
        )
        rebound = self.client.patch(
            f"/api/recruitment/jobs/{self.job.pk}/",
            {"boss_account": other_account.pk},
            format="json",
        )

        self.assertEqual(disabled.status_code, 400, disabled.data)
        self.assertEqual(rebound.status_code, 400, rebound.data)
        self.account.refresh_from_db()
        self.job.refresh_from_db()
        self.assertTrue(self.account.active)
        self.assertEqual(self.job.boss_account_id, self.account.pk)

    def test_stopped_plan_rejects_late_human_decision_on_old_run(self):
        self._start()
        plan = RecruitmentAutomationPlan.objects.get(job=self.job)
        run = plan.current_run
        node = run.node_runs.get(node_key="search_pull")
        stopped = self._stop(plan)
        self.assertEqual(stopped.status_code, 200, stopped.data)

        late = self.client.post(
            f"/api/recruitment/workflow-runs/{run.pk}/decision/",
            {"node_id": node.pk, "approved": True},
            format="json",
        )

        self.assertEqual(late.status_code, 409, late.data)

    def test_late_passive_message_callback_after_stop_creates_no_draft_or_attention(self):
        self._start(kind="passive_resume")
        plan = RecruitmentAutomationPlan.objects.get(job=self.job)
        generation = plan.control_generation
        candidate = Candidate.objects.create(
            identity_key="late-passive-callback", name="迟到回调候选人"
        )
        application = JobApplication.objects.create(
            candidate=candidate, job=self.job, source="boss"
        )
        from recruitment.services.conversation_ingestion import ingest_conversation, _queue_resume_request

        ingest_conversation(
            application=application,
            account=self.account,
            messages=[{
                "external_id": "late-callback-message",
                "direction": "candidate",
                "content": "我对这个岗位感兴趣",
                "sent_at": "2026-08-26T09:00:00+08:00",
            }],
        )
        source_message = application.conversation_state.messages.get()
        counts_before = (
            AutomationApproval.objects.count(),
            ConversationAction.objects.count(),
            HumanAttention.objects.count(),
        )
        stopped = self._stop(plan)
        self.assertEqual(stopped.status_code, 200, stopped.data)

        result = _queue_resume_request(
            application=application,
            account=self.account,
            actor=self.user,
            message="方便发送一份简历吗？",
            first_contact=True,
            source_message=source_message,
            automation_plan_revision=plan.current_revision,
            automation_generation=generation,
        )

        self.assertIsNone(result)
        self.assertEqual(
            (
                AutomationApproval.objects.count(),
                ConversationAction.objects.count(),
                HumanAttention.objects.count(),
            ),
            counts_before,
        )

    def test_late_verified_communication_result_is_audited_but_does_not_advance_stopped_plan(self):
        self._start(kind="passive_resume")
        plan = RecruitmentAutomationPlan.objects.get(job=self.job)
        candidate = Candidate.objects.create(
            identity_key="late-verified-communication",
            external_id="boss-late-verified",
            name="迟到成功回执候选人",
        )
        application = JobApplication.objects.create(
            candidate=candidate, job=self.job, source="boss"
        )
        initial_stage = application.stage
        initial_history_count = ApplicationStageHistory.objects.filter(application=application).count()
        from recruitment.services.approvals import approve
        from recruitment.services.communications import (
            complete_communication_task,
            materialize_communication_batch,
            prepare_communication,
        )

        approval = prepare_communication(
            account=self.account,
            applications=[application],
            action=ConversationAction.Action.REQUEST_RESUME,
            message="方便发送一份简历吗？",
            actor=self.user,
            request_id="late-verified-communication",
            automation_plan_revision=plan.current_revision,
            automation_generation=plan.control_generation,
        )
        approve(approval=approval, actor=self.user)
        batch = materialize_communication_batch(approval=approval, actor=self.user)
        task = batch.rpa_tasks.get()
        task.status = RpaTask.Status.RUNNING
        task.lease_expires_at = timezone.now() + timedelta(minutes=1)
        task.save(update_fields=["status", "lease_expires_at", "updated_at"])
        stopped = self._stop(plan)
        self.assertEqual(stopped.status_code, 202, stopped.data)
        expected_external_id = task.request_payload["target"]["external_id"]

        complete_communication_task(
            task=task,
            status=RpaTask.Status.SUCCEEDED,
            result={
                "verified": True,
                "expected_external_id": expected_external_id,
                "observed_external_id": expected_external_id,
            },
            error_code="",
            error_message="",
        )

        task.refresh_from_db()
        batch.refresh_from_db()
        application.refresh_from_db()
        action = batch.conversation_actions.get()
        plan.current_run.refresh_from_db()
        self.assertEqual(task.status, RpaTask.Status.SUCCEEDED)
        self.assertEqual(action.status, ConversationAction.Status.SUCCEEDED)
        self.assertEqual(action.step.status, "succeeded")
        self.assertEqual(batch.status, ExecutionBatch.Status.CANCELLED)
        self.assertEqual(application.stage, initial_stage)
        self.assertEqual(
            ApplicationStageHistory.objects.filter(application=application).count(),
            initial_history_count,
        )
        self.assertEqual(plan.current_run.status, WorkflowRun.Status.CANCELLED)
        self.assertFalse(batch.rpa_tasks.filter(status=RpaTask.Status.PENDING).exists())

    def test_plan_linked_rpa_task_cannot_use_generic_cancel_or_retry(self):
        self._start(kind="passive_resume")
        task = RpaTask.objects.get(automation_plan_revision__plan__job=self.job)

        for action in ["cancel", "retry"]:
            response = self.client.post(
                f"/api/recruitment/rpa-tasks/{task.pk}/{action}/", {}, format="json"
            )
            self.assertEqual(response.status_code, 409, (action, response.data))

    def test_stop_then_switch_kind_reuses_one_plan_and_one_managed_template(self):
        first = self._start()
        plan = RecruitmentAutomationPlan.objects.get(job=self.job)
        stopped = self._stop(plan)
        self.assertEqual(stopped.status_code, 200, stopped.data)

        second = self._start(
            expected=stopped.data["control_version"],
            kind="passive_resume",
        )

        self.assertEqual(second.status_code, 200, second.data)
        plan.refresh_from_db()
        self.assertEqual(plan.pk, first.data["id"])
        self.assertEqual(plan.kind, RecruitmentAutomationPlan.Kind.PASSIVE_RESUME)
        self.assertEqual(plan.revisions.count(), 2)
        self.assertEqual(WorkflowTemplate.objects.count(), 1)

    def test_three_restarts_create_three_revisions_but_only_one_managed_template(self):
        response = self._start()
        plan = RecruitmentAutomationPlan.objects.get(job=self.job)
        for _ in range(2):
            stopped = self._stop(plan)
            self.assertEqual(stopped.status_code, 200, stopped.data)
            response = self._start(expected=stopped.data["control_version"])
            self.assertEqual(response.status_code, 200, response.data)
            plan.refresh_from_db()

        self.assertEqual(plan.revisions.count(), 3)
        self.assertEqual(WorkflowTemplate.objects.count(), 1)
        self.assertEqual(plan.managed_template.versions.count(), 3)

    def test_managed_workflow_version_cannot_be_replayed_as_custom_configuration(self):
        self._start()
        plan = RecruitmentAutomationPlan.objects.get(job=self.job)
        managed_version_id = plan.current_revision.workflow_version_id
        stopped = self._stop(plan)
        self.assertEqual(stopped.status_code, 200, stopped.data)

        replayed_as_custom = self._start(
            expected=stopped.data["control_version"],
            workflow_version=managed_version_id,
        )

        self.assertEqual(replayed_as_custom.status_code, 400, replayed_as_custom.data)
        plan.refresh_from_db()
        self.assertEqual(plan.desired_state, RecruitmentAutomationPlan.DesiredState.STOPPED)
        self.assertEqual(plan.revisions.count(), 1)

    def test_real_custom_enabled_workflow_can_start_and_is_reported_as_custom(self):
        from recruitment.services.standard_workflows import create_standard_workflow
        from recruitment.services.workflows import enable_version

        _, custom_version = create_standard_workflow(
            kind=RecruitmentAutomationPlan.Kind.ACTIVE_RESUME_SEARCH,
            account=self.account,
            actor=self.user,
            config={
                "source": "search",
                "keyword": "SaaS",
                "target_resume_count": 2,
                "max_scan_count": 10,
                "core": ["B 端产品"],
                "bonus": [],
            },
        )
        enable_version(version=custom_version, actor=self.user)

        started = self._start(workflow_version=custom_version.pk)

        self.assertEqual(started.status_code, 201, started.data)
        self.assertEqual(started.data["current_revision"]["workflow_mode"], "custom")
        self.assertFalse(started.data["current_revision"]["is_managed_workflow"])
        plan = RecruitmentAutomationPlan.objects.get(job=self.job)
        self.assertIsNone(plan.managed_template_id)

    def test_successful_start_replay_survives_later_account_and_job_state_changes(self):
        request_id = uuid.uuid4()
        first = self._start(request_id=request_id)
        self.account.login_status = BossAccount.LoginStatus.WAITING_HUMAN
        self.account.save(update_fields=["login_status", "updated_at"])
        self.job.archived_at = timezone.now()
        self.job.save(update_fields=["archived_at", "updated_at"])

        replay = self._start(request_id=request_id)

        self.assertEqual(replay.status_code, 200, replay.data)
        self.assertEqual(replay.data["id"], first.data["id"])
        self.assertEqual(RecruitmentAutomationPlan.objects.get(job=self.job).revisions.count(), 1)

    def test_stop_does_not_rewrite_terminal_batch_from_an_older_generation(self):
        self._start()
        plan = RecruitmentAutomationPlan.objects.get(job=self.job)
        historical = ExecutionBatch.objects.create(
            boss_account=self.account,
            action="request_resume",
            status=ExecutionBatch.Status.SUCCEEDED,
            idempotency_key="historical-plan-batch",
            created_by=self.user,
            automation_plan_revision=plan.current_revision,
            automation_generation=plan.control_generation,
        )
        stopped = self._stop(plan)
        self.assertEqual(stopped.status_code, 200, stopped.data)
        restarted = self._start(expected=stopped.data["control_version"])
        self.assertEqual(restarted.status_code, 200, restarted.data)
        self.assertEqual(self._stop(plan).status_code, 200)

        historical.refresh_from_db()
        self.assertEqual(historical.status, ExecutionBatch.Status.SUCCEEDED)

    def test_stop_with_inflight_atomic_task_reports_stopping_and_blocks_restart(self):
        self._start()
        plan = RecruitmentAutomationPlan.objects.get(job=self.job)
        RpaTask.objects.create(
            boss_account=self.account,
            action=RpaTask.Action.SEARCH_AND_PULL_RESUMES,
            status=RpaTask.Status.RUNNING,
            created_by=self.user,
            automation_plan_revision=plan.current_revision,
            automation_generation=plan.control_generation,
            idempotency_key="inflight-plan-task",
        )

        stopped = self._stop(plan)
        self.assertEqual(stopped.status_code, 202, stopped.data)
        self.assertEqual(stopped.data["effective_state"], "stopping")
        restart = self._start(expected=stopped.data["control_version"])
        self.assertEqual(restart.status_code, 409, restart.data)

    def test_workbench_poll_recovers_expired_plan_lease_and_allows_restart(self):
        self._start()
        plan = RecruitmentAutomationPlan.objects.get(job=self.job)
        task = RpaTask.objects.create(
            boss_account=self.account,
            action=RpaTask.Action.SYNC_CONVERSATIONS,
            status=RpaTask.Status.RUNNING,
            created_by=self.user,
            automation_plan_revision=plan.current_revision,
            automation_generation=plan.control_generation,
            lease_expires_at=timezone.now() + timedelta(minutes=1),
            idempotency_key="expired-plan-task-visible-from-workbench",
        )
        stopped = self._stop(plan)
        self.assertEqual(stopped.status_code, 202, stopped.data)
        RpaTask.objects.filter(pk=task.pk).update(
            lease_expires_at=timezone.now() - timedelta(seconds=1)
        )

        polled = self.client.get(f"/api/recruitment/automation-plans/{plan.pk}/")

        self.assertEqual(polled.status_code, 200, polled.data)
        self.assertEqual(polled.data["effective_state"], "stopped")
        task.refresh_from_db()
        self.assertEqual(task.status, RpaTask.Status.FAILED)
        restarted = self._start(expected=stopped.data["control_version"])
        self.assertEqual(restarted.status_code, 200, restarted.data)

    @override_settings(
        RPA_WORKER_TOKEN="plan-completion-fence-secret",
        RPA_WORKER_KEYS={"automation-plan-worker": "plan-completion-fence-secret"},
    )
    def test_search_completion_after_stop_uses_server_fence_even_without_worker_stop_flag(self):
        self._start()
        plan = RecruitmentAutomationPlan.objects.get(job=self.job)
        node = plan.current_run.node_runs.get(node_key="search_pull")
        approved = self.client.post(
            f"/api/recruitment/workflow-runs/{plan.current_run_id}/decision/",
            {"node_id": node.pk, "approved": True},
            format="json",
        )
        self.assertEqual(approved.status_code, 200, approved.data)
        task = RpaTask.objects.get(
            automation_plan_revision=plan.current_revision,
            action=RpaTask.Action.SEARCH_AND_PULL_RESUMES,
        )
        campaign = SearchCampaign.objects.get(pk=task.request_payload["campaign_id"])
        worker = RpaWorker.objects.get(key="automation-plan-worker")
        lease_token = uuid.uuid4()
        task.status = RpaTask.Status.RUNNING
        task.worker = worker
        task.lease_token = lease_token
        task.lease_generation = 1
        task.lease_expires_at = timezone.now() + timedelta(minutes=1)
        task.save(update_fields=[
            "status", "worker", "lease_token", "lease_generation", "lease_expires_at", "updated_at",
        ])
        stopped = self._stop(plan)
        self.assertEqual(stopped.status_code, 202, stopped.data)

        completed = self.client.post(
            f"/api/recruitment/worker/tasks/{task.pk}/complete/",
            {
                "worker_key": worker.key,
                "lease_token": str(lease_token),
                "lease_generation": 1,
                "status": RpaTask.Status.SUCCEEDED,
                "result": {
                    "candidates": [],
                    "resumes": [],
                    "scanned_count": 0,
                    "view_attempt_count": 0,
                    "resume_view_budget": task.request_payload["resume_view_budget"],
                    "attempts": [],
                },
            },
            format="json",
            HTTP_X_RPA_WORKER_TOKEN="plan-completion-fence-secret",
        )

        self.assertEqual(completed.status_code, 200, completed.data)
        task.refresh_from_db()
        campaign.refresh_from_db()
        self.assertEqual(task.status, RpaTask.Status.CANCELLED)
        self.assertEqual(campaign.status, SearchCampaign.Status.CANCELLED)
        self.assertEqual(campaign.stop_reason, SearchCampaign.StopReason.USER_STOPPED)

    def test_passive_subscription_stays_running_after_bootstrap_run_finishes(self):
        response = self._start(kind="passive_resume")
        self.assertEqual(response.status_code, 201, response.data)
        plan = RecruitmentAutomationPlan.objects.get(job=self.job)
        plan.current_run.status = WorkflowRun.Status.SUCCEEDED
        plan.current_run.completed_at = timezone.now()
        plan.current_run.save(update_fields=["status", "completed_at", "updated_at"])
        RpaTask.objects.filter(automation_plan_revision=plan.current_revision).update(
            status=RpaTask.Status.SUCCEEDED,
            completed_at=timezone.now(),
        )

        response = self.client.get(
            f"/api/recruitment/automation-plans/{plan.pk}/"
        )

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["effective_state"], "running")
        self.assertTrue(MessageSyncPolicy.objects.get(boss_account=self.account).enabled)

    @override_settings(RPA_WORKER_TOKEN="plan-lifecycle-worker-secret")
    def test_archiving_job_fences_and_cancels_pending_plan_task_before_lease(self):
        response = self._start(kind="passive_resume")
        self.assertEqual(response.status_code, 201, response.data)
        pending = RpaTask.objects.get(automation_plan_revision__plan__job=self.job)

        from recruitment.services.lifecycle import archive_object

        archive_object(instance=self.job, actor=self.user)
        leased = self.client.post(
            "/api/recruitment/worker/tasks/lease/",
            {"worker_key": "automation-plan-worker"},
            format="json",
            HTTP_X_RPA_WORKER_TOKEN="plan-lifecycle-worker-secret",
        )

        self.assertEqual(leased.status_code, 200, leased.data)
        self.assertIsNone(leased.data["task"])
        pending.refresh_from_db()
        self.assertEqual(pending.status, RpaTask.Status.CANCELLED)
        plan = RecruitmentAutomationPlan.objects.get(job=self.job)
        self.assertEqual(plan.desired_state, RecruitmentAutomationPlan.DesiredState.STOPPED)

    def test_stopping_one_passive_job_keeps_other_job_subscription_running(self):
        first = self._start(kind="passive_resume")
        self.assertEqual(first.status_code, 201, first.data)
        second_job = RecruitmentJob.objects.create(
            boss_account=self.account,
            external_id="plan-job-two",
            title="高级研发经理",
            owner=self.user,
        )
        second = self._start(kind="passive_resume", job=second_job)
        self.assertEqual(second.status_code, 201, second.data)
        first_plan = RecruitmentAutomationPlan.objects.get(job=self.job)

        stopped = self._stop(first_plan)

        self.assertEqual(stopped.status_code, 200, stopped.data)
        second_plan = RecruitmentAutomationPlan.objects.get(job=second_job)
        self.assertEqual(second_plan.desired_state, RecruitmentAutomationPlan.DesiredState.RUNNING)
        policy = MessageSyncPolicy.objects.get(boss_account=self.account)
        self.assertTrue(policy.enabled)
        from recruitment.services.automation_plans import message_sync_scopes_for_account

        self.assertEqual(
            set(message_sync_scopes_for_account(self.account)),
            {str(second_job.pk)},
        )

    @override_settings(RPA_WORKER_TOKEN="plan-multi-scope-secret")
    def test_changing_one_scope_stops_whole_shared_poll_and_reschedules_remaining_job(self):
        self._start(kind="passive_resume")
        second_job = RecruitmentJob.objects.create(
            boss_account=self.account,
            external_id="plan-job-scope-two",
            title="第二个被动岗位",
            owner=self.user,
        )
        self._start(kind="passive_resume", job=second_job)
        first_plan = RecruitmentAutomationPlan.objects.get(job=self.job)
        second_plan = RecruitmentAutomationPlan.objects.get(job=second_job)
        RpaTask.objects.filter(
            automation_plan_revision_id__in=[
                first_plan.current_revision_id,
                second_plan.current_revision_id,
            ]
        ).update(status=RpaTask.Status.SUCCEEDED, completed_at=timezone.now())
        scopes = {
            str(self.job.pk): {
                "revision_id": first_plan.current_revision_id,
                "generation": first_plan.control_generation,
            },
            str(second_job.pk): {
                "revision_id": second_plan.current_revision_id,
                "generation": second_plan.control_generation,
            },
        }
        worker = RpaWorker.objects.get(key="automation-plan-worker")
        lease_token = uuid.uuid4()
        shared = RpaTask.objects.create(
            boss_account=self.account,
            action=RpaTask.Action.SYNC_CONVERSATIONS,
            status=RpaTask.Status.RUNNING,
            created_by=self.user,
            worker=worker,
            lease_token=lease_token,
            lease_generation=1,
            lease_expires_at=timezone.now() + timedelta(minutes=1),
            request_payload={"scheduled": True, "passive_plan_scopes": scopes},
            idempotency_key="multi-scope-poll-before-stop",
        )
        stopped = self._stop(first_plan)
        self.assertEqual(stopped.status_code, 202, stopped.data)

        checkpoint = self.client.post(
            f"/api/recruitment/worker/tasks/{shared.pk}/event/",
            {
                "worker_key": worker.key,
                "lease_token": str(lease_token),
                "lease_generation": 1,
                "event": "before_open_chat",
            },
            format="json",
            HTTP_X_RPA_WORKER_TOKEN="plan-multi-scope-secret",
        )
        self.assertEqual(checkpoint.status_code, 409, checkpoint.data)
        completed = self.client.post(
            f"/api/recruitment/worker/tasks/{shared.pk}/complete/",
            {
                "worker_key": worker.key,
                "lease_token": str(lease_token),
                "lease_generation": 1,
                "status": RpaTask.Status.SUCCEEDED,
                "result": {"conversations": [], "checkpoint_stopped": True},
            },
            format="json",
            HTTP_X_RPA_WORKER_TOKEN="plan-multi-scope-secret",
        )
        self.assertEqual(completed.status_code, 200, completed.data)
        shared.refresh_from_db()
        self.assertEqual(shared.status, RpaTask.Status.CANCELLED)

        policy = MessageSyncPolicy.objects.get(boss_account=self.account)
        policy.last_scheduled_at = timezone.now() - timedelta(minutes=policy.interval_minutes + 1)
        policy.save(update_fields=["last_scheduled_at", "updated_at"])
        from recruitment.services.message_scheduling import schedule_due_conversation_syncs

        scheduled = schedule_due_conversation_syncs(now=timezone.now())
        self.assertEqual(len(scheduled), 1)
        self.assertEqual(
            set(scheduled[0].request_payload["passive_plan_scopes"]),
            {str(second_job.pk)},
        )

    @override_settings(RPA_WORKER_TOKEN="plan-ambiguous-scope-secret")
    def test_account_wide_same_name_row_cannot_be_misbound_to_only_allowed_job(self):
        self._start(kind="passive_resume")
        second_job = RecruitmentJob.objects.create(
            boss_account=self.account,
            external_id="plan-job-ambiguous-two",
            title="同名候选人第二岗位",
            owner=self.user,
        )
        self._start(kind="passive_resume", job=second_job)
        first_plan = RecruitmentAutomationPlan.objects.get(job=self.job)
        second_plan = RecruitmentAutomationPlan.objects.get(job=second_job)
        for index, job in enumerate([self.job, second_job]):
            candidate = Candidate.objects.create(
                identity_key=f"same-name-across-jobs-{index}",
                name="张三",
            )
            JobApplication.objects.create(candidate=candidate, job=job, source="boss")
        stopped = self._stop(first_plan)
        self.assertEqual(stopped.status_code, 200, stopped.data)
        scopes = {
            str(second_job.pk): {
                "revision_id": second_plan.current_revision_id,
                "generation": second_plan.control_generation,
            }
        }
        worker = RpaWorker.objects.get(key="automation-plan-worker")
        lease_token = uuid.uuid4()
        shared = RpaTask.objects.create(
            boss_account=self.account,
            action=RpaTask.Action.SYNC_CONVERSATIONS,
            status=RpaTask.Status.RUNNING,
            created_by=self.user,
            worker=worker,
            lease_token=lease_token,
            lease_generation=1,
            lease_expires_at=timezone.now() + timedelta(minutes=1),
            request_payload={"scheduled": True, "passive_plan_scopes": scopes},
            idempotency_key="ambiguous-name-b-only-poll",
        )

        completed = self.client.post(
            f"/api/recruitment/worker/tasks/{shared.pk}/complete/",
            {
                "worker_key": worker.key,
                "lease_token": str(lease_token),
                "lease_generation": 1,
                "status": RpaTask.Status.SUCCEEDED,
                "result": {"conversations": [{
                    "name": "张三",
                    "messages": [{
                        "direction": "candidate",
                        "content": "我是 A 岗位的候选人",
                        "sent_at": "2026-08-26T09:00:00+08:00",
                    }],
                    "attachments": [],
                }]},
            },
            format="json",
            HTTP_X_RPA_WORKER_TOKEN="plan-ambiguous-scope-secret",
        )

        self.assertEqual(completed.status_code, 200, completed.data)
        from recruitment.models import ConversationMessage, ConversationSyncState

        self.assertFalse(ConversationMessage.objects.exists())
        self.assertFalse(ConversationSyncState.objects.exists())

    @override_settings(RPA_WORKER_TOKEN="plan-scope-worker-secret")
    def test_late_stopped_scope_discards_rows_and_cleans_only_incoming_attachments(self):
        self._start(kind="passive_resume")
        plan = RecruitmentAutomationPlan.objects.get(job=self.job)
        scopes = {
            str(self.job.pk): {
                "revision_id": plan.current_revision_id,
                "generation": plan.control_generation,
            }
        }
        RpaTask.objects.filter(automation_plan_revision=plan.current_revision).update(
            status=RpaTask.Status.SUCCEEDED,
            completed_at=timezone.now(),
        )
        worker = RpaWorker.objects.get(key="automation-plan-worker")
        lease_token = uuid.uuid4()
        shared = RpaTask.objects.create(
            boss_account=self.account,
            action=RpaTask.Action.SYNC_CONVERSATIONS,
            status=RpaTask.Status.RUNNING,
            created_by=self.user,
            worker=worker,
            lease_token=lease_token,
            lease_generation=1,
            lease_expires_at=timezone.now() + timedelta(minutes=1),
            request_payload={"scheduled": True, "passive_plan_scopes": scopes},
            idempotency_key="late-stopped-scope",
        )
        stopped = self._stop(plan)
        self.assertEqual(stopped.status_code, 202, stopped.data)
        self.assertEqual(stopped.data["effective_state"], "stopping")

        with tempfile.TemporaryDirectory() as root:
            media = Path(root) / "media"
            incoming = media / "rpa-incoming"
            incoming.mkdir(parents=True)
            safe_file = incoming / "candidate.pdf"
            safe_file.write_bytes(b"pdf")
            outside_file = Path(root) / "outside.pdf"
            outside_file.write_bytes(b"private")
            with override_settings(MEDIA_ROOT=media), self.captureOnCommitCallbacks(execute=True):
                completed = self.client.post(
                    f"/api/recruitment/worker/tasks/{shared.pk}/complete/",
                    {
                        "worker_key": worker.key,
                        "lease_token": str(lease_token),
                        "lease_generation": 1,
                        "status": "succeeded",
                        "result": {"conversations": [{
                            "name": "停止岗位候选人",
                            "messages": [{
                                "direction": "candidate",
                                "content": "这是简历",
                                "sent_at": "2026-08-25T09:00:00+08:00",
                            }],
                            "attachments": [
                                {"path": str(safe_file), "filename": "candidate.pdf"},
                                {"path": str(outside_file), "filename": "outside.pdf"},
                            ],
                        }]},
                    },
                    format="json",
                    HTTP_X_RPA_WORKER_TOKEN="plan-scope-worker-secret",
                )

            self.assertEqual(completed.status_code, 200, completed.data)
            self.assertFalse(safe_file.exists())
            self.assertTrue(outside_file.exists())
            from recruitment.models import ConversationMessage

            self.assertFalse(ConversationMessage.objects.exists())
            shared.refresh_from_db()
            self.assertEqual(shared.status, RpaTask.Status.CANCELLED)
            self.assertEqual(shared.error_code, "automation_plan_stopped")
        final = self.client.get(f"/api/recruitment/automation-plans/{plan.pk}/")
        self.assertEqual(final.data["effective_state"], "stopped")


class AutomationPlanModelTests(TestCase):
    def test_one_plan_per_job_is_database_invariant(self):
        user = User.objects.create_user("one-plan-model")
        account = BossAccount.objects.create(
            name="one-plan-account", browser_profile="one-plan", cdp_port=54102
        )
        job = RecruitmentJob.objects.create(
            boss_account=account, external_id="one-plan-job", title="工程师", owner=user
        )
        RecruitmentAutomationPlan.objects.create(
            job=job,
            kind=RecruitmentAutomationPlan.Kind.PASSIVE_RESUME,
            created_by=user,
        )

        from django.db import IntegrityError, transaction

        with self.assertRaises(IntegrityError), transaction.atomic():
            RecruitmentAutomationPlan.objects.create(
                job=job,
                kind=RecruitmentAutomationPlan.Kind.ACTIVE_RESUME_SEARCH,
                created_by=user,
            )
