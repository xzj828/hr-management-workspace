from django.contrib.auth.models import User
from django.test import TestCase

from attendance.models import AccountProfile
from recruitment.models import (
    BossAccount,
    Candidate,
    JobApplication,
    RecruitmentJob,
    WorkflowNodeRun,
    WorkflowRun,
    WorkflowTemplate,
)
from recruitment.services.workflow_events import publish_workflow_event
from recruitment.services.conversation_ingestion import ingest_conversation
from recruitment.services.resumes import archive_pdf
from recruitment.services.workflow_nodes import execute_workflow_node
from recruitment.services.workflow_runtime import advance_run, create_run
from recruitment.services.workflows import create_version


class WorkflowEventWakeupTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("workflow-event")
        AccountProfile.objects.create(user=self.user, role=AccountProfile.Role.HR)
        self.account = BossAccount.objects.create(
            name="Workflow event account",
            browser_profile="workflow-event",
            cdp_port=53997,
        )
        self.account.authorized_users.add(self.user)
        self.job = RecruitmentJob.objects.create(
            boss_account=self.account,
            external_id="event-job",
            title="运营经理",
            owner=self.user,
        )
        candidate = Candidate.objects.create(identity_key="event-candidate", name="陈月")
        self.application = JobApplication.objects.create(candidate=candidate, job=self.job, source="boss")

    def _waiting_run(self, node_type, event_name):
        template = WorkflowTemplate.objects.create(name=f"wait {node_type}", created_by=self.user)
        version = create_version(
            template=template,
            boss_account=self.account,
            actor=self.user,
            nodes=[
                {"key": "source", "type": "search", "config": {}, "position": {}},
                {"key": "wait", "type": node_type, "config": {"wake_event": event_name}, "position": {}},
                {"key": "end", "type": "end", "config": {}, "position": {}},
            ],
            edges=[{"source": "source", "target": "wait"}, {"source": "wait", "target": "end"}],
        )
        run = create_run(
            version=version,
            actor=self.user,
            mode=WorkflowRun.Mode.FORMAL,
            idempotency_key=f"event:{node_type}",
            job=self.job,
            input_snapshot={"application_ids": [self.application.pk]},
        )
        source = run.node_runs.get(node_key="source")
        source.status = WorkflowNodeRun.Status.SUCCEEDED
        source.save(update_fields=["status", "updated_at"])
        return advance_run(run, executor=execute_workflow_node)

    def test_resume_event_wakes_matching_wait_resume_once(self):
        run = self._waiting_run("wait_resume", "resume.archived")
        self.assertEqual(run.node_runs.get(node_key="wait").status, WorkflowNodeRun.Status.WAITING_HUMAN)

        first = publish_workflow_event(
            event="resume.archived",
            application=self.application,
            event_key="resume:10",
            payload={"resume_id": 10},
        )
        second = publish_workflow_event(
            event="resume.archived",
            application=self.application,
            event_key="resume:10",
            payload={"resume_id": 10},
        )

        self.assertEqual(first, 1)
        self.assertEqual(second, 0)
        run.refresh_from_db()
        self.assertEqual(run.status, WorkflowRun.Status.SUCCEEDED)
        self.assertEqual(run.node_runs.get(node_key="wait").output["event_key"], "resume:10")

    def test_candidate_message_does_not_wake_resume_wait(self):
        run = self._waiting_run("wait_resume", "resume.archived")

        changed = publish_workflow_event(
            event="candidate_message.received",
            application=self.application,
            event_key="message:2",
            payload={"message_id": 2},
        )

        self.assertEqual(changed, 0)
        run.node_runs.get(node_key="wait").refresh_from_db()
        self.assertEqual(run.node_runs.get(node_key="wait").status, WorkflowNodeRun.Status.WAITING_HUMAN)

    def test_ingested_candidate_message_automatically_wakes_wait_reply(self):
        run = self._waiting_run("wait_reply", "candidate_message.received")

        with self.captureOnCommitCallbacks(execute=True):
            ingest_conversation(
                application=self.application,
                account=self.account,
                messages=[{
                    "external_id": "wake-message-1",
                    "direction": "candidate",
                    "content": "你好",
                    "sent_at": "2026-08-25T10:00:00+08:00",
                }],
            )

        run.refresh_from_db()
        self.assertEqual(run.status, WorkflowRun.Status.SUCCEEDED)

    def test_archived_resume_automatically_wakes_wait_resume(self):
        run = self._waiting_run("wait_resume", "resume.archived")

        with self.settings(MEDIA_ROOT=self._testMethodName), self.captureOnCommitCallbacks(execute=True):
            archive_pdf(
                application=self.application,
                filename="candidate.pdf",
                content=b"%PDF-1.4\nworkflow event test",
                actor=self.user,
            )

        run.refresh_from_db()
        self.assertEqual(run.status, WorkflowRun.Status.SUCCEEDED)
