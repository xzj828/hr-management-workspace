import threading
import uuid
from datetime import timedelta
from unittest import skipUnless

from django.contrib.auth.models import User
from django.db import close_old_connections, connection
from django.test import TransactionTestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from attendance.models import AccountProfile
from recruitment.models import (
    AutomationApproval,
    BossAccount,
    RecruitmentAutomationPlan,
    RecruitmentJob,
    RpaTask,
    RpaWorker,
    SearchCampaign,
)
from recruitment.services.approvals import approve
from recruitment.services.automation_plans import AutomationPlanConflict, start_plan, stop_plan
from recruitment.services.search_campaigns import start_search_campaign
from recruitment.services.sqlite_lifecycle import sqlite_lifecycle_serialized


@skipUnless(connection.vendor == "sqlite", "SQLite transaction-mode regression")
@override_settings(RPA_WORKER_TOKEN="sqlite-plan-worker-secret")
class AutomationPlanSqliteConcurrencyTests(TransactionTestCase):
    reset_sequences = True

    def setUp(self):
        self.user = User.objects.create_user("sqlite-plan-concurrency")
        AccountProfile.objects.create(user=self.user, role=AccountProfile.Role.HR)
        self.account = BossAccount.objects.create(
            name="SQLite 并发账号",
            browser_profile="sqlite-plan-concurrency",
            cdp_port=54104,
            login_status=BossAccount.LoginStatus.READY,
            status=BossAccount.Status.READY,
        )
        self.account.authorized_users.add(self.user)
        self.job = RecruitmentJob.objects.create(
            boss_account=self.account,
            external_id="sqlite-concurrent-job",
            title="SQLite 并发职位",
            owner=self.user,
        )

    @staticmethod
    def _config():
        return {
            "source": "search",
            "keyword": "并发安全",
            "target_resume_count": 1,
            "max_scan_count": 3,
            "core": [],
            "bonus": [],
        }

    def test_two_connections_starting_same_job_serialize_without_database_locked(self):
        barrier = threading.Barrier(3)
        outcomes = []
        outcome_lock = threading.Lock()

        def run_start(request_id):
            close_old_connections()
            try:
                actor = User.objects.get(pk=self.user.pk)
                barrier.wait(timeout=5)
                result = start_plan(
                    job_id=self.job.pk,
                    kind=RecruitmentAutomationPlan.Kind.ACTIVE_RESUME_SEARCH,
                    config=self._config(),
                    request_id=request_id,
                    expected_control_version=0,
                    actor=actor,
                )
                outcome = ("started", result.plan.pk)
            except AutomationPlanConflict as exc:
                outcome = ("conflict", str(exc))
            except Exception as exc:  # surfaced below with its concrete class/message
                outcome = ("error", f"{type(exc).__name__}: {exc}")
            finally:
                close_old_connections()
            with outcome_lock:
                outcomes.append(outcome)

        threads = [
            threading.Thread(target=run_start, args=(uuid.uuid4(),), daemon=True)
            for _ in range(2)
        ]
        for thread in threads:
            thread.start()
        barrier.wait(timeout=5)
        for thread in threads:
            thread.join(timeout=25)

        self.assertFalse(any(thread.is_alive() for thread in threads), outcomes)
        self.assertEqual(sorted(value[0] for value in outcomes), ["conflict", "started"], outcomes)
        self.assertNotIn("database is locked", str(outcomes).lower())
        plan = RecruitmentAutomationPlan.objects.get(job=self.job)
        self.assertEqual(plan.control_generation, 1)
        self.assertEqual(plan.control_version, 1)
        self.assertEqual(plan.revisions.count(), 1)

    def test_stop_transaction_fences_concurrent_worker_completion_without_500(self):
        started = start_plan(
            job_id=self.job.pk,
            kind=RecruitmentAutomationPlan.Kind.ACTIVE_RESUME_SEARCH,
            config=self._config(),
            request_id=uuid.uuid4(),
            expected_control_version=0,
            actor=self.user,
        )
        plan = started.plan
        plan.refresh_from_db()
        node = plan.current_run.node_runs.get(node_key="search_pull")
        approval = AutomationApproval.objects.get(pk=node.output["approval_id"])
        approve(approval=approval, actor=self.user)
        campaign = SearchCampaign.objects.get(
            automation_plan_revision=plan.current_revision,
            workflow_run=plan.current_run,
        )
        task = start_search_campaign(
            campaign=campaign,
            actor=self.user,
            approval=approval,
        )
        worker = RpaWorker.objects.create(
            key="sqlite-plan-worker",
            hostname="localhost",
            status=RpaWorker.Status.ONLINE,
            last_seen_at=timezone.now(),
        )
        lease_token = uuid.uuid4()
        task.status = RpaTask.Status.RUNNING
        task.worker = worker
        task.lease_token = lease_token
        task.lease_generation = 1
        task.lease_expires_at = timezone.now() + timedelta(minutes=1)
        task.save(update_fields=[
            "status", "worker", "lease_token", "lease_generation", "lease_expires_at", "updated_at",
        ])

        barrier = threading.Barrier(2)
        outcomes = {}

        def run_stop():
            close_old_connections()
            try:
                actor = User.objects.get(pk=self.user.pk)
                # Hold the same process boundary used by both HTTP control and
                # Worker completion, release the Worker, then commit stop first.
                with sqlite_lifecycle_serialized():
                    barrier.wait(timeout=5)
                    result = stop_plan(
                        plan_id=plan.pk,
                        actor=actor,
                        request_id=uuid.uuid4(),
                        expected_control_version=plan.control_version,
                    )
                    outcomes["stop"] = ("ok", result.plan.control_generation)
            except Exception as exc:
                outcomes["stop"] = ("error", f"{type(exc).__name__}: {exc}")
            finally:
                close_old_connections()

        def run_complete():
            close_old_connections()
            try:
                barrier.wait(timeout=5)
                client = APIClient()
                response = client.post(
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
                    HTTP_X_RPA_WORKER_TOKEN="sqlite-plan-worker-secret",
                )
                outcomes["complete"] = (response.status_code, getattr(response, "data", None))
            except Exception as exc:
                outcomes["complete"] = ("error", f"{type(exc).__name__}: {exc}")
            finally:
                close_old_connections()

        stop_thread = threading.Thread(target=run_stop, daemon=True)
        complete_thread = threading.Thread(target=run_complete, daemon=True)
        stop_thread.start()
        complete_thread.start()
        stop_thread.join(timeout=25)
        complete_thread.join(timeout=25)

        self.assertFalse(stop_thread.is_alive(), outcomes)
        self.assertFalse(complete_thread.is_alive(), outcomes)
        self.assertEqual(outcomes.get("stop", (None,))[0], "ok", outcomes)
        self.assertEqual(outcomes.get("complete", (None,))[0], 200, outcomes)
        self.assertNotIn("database is locked", str(outcomes).lower())
        plan.refresh_from_db()
        task.refresh_from_db()
        campaign.refresh_from_db()
        self.assertEqual(plan.desired_state, RecruitmentAutomationPlan.DesiredState.STOPPED)
        self.assertEqual(task.status, RpaTask.Status.CANCELLED)
        self.assertEqual(campaign.status, SearchCampaign.Status.CANCELLED)
        self.assertEqual(campaign.stop_reason, SearchCampaign.StopReason.USER_STOPPED)
