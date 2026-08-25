from django.contrib.auth.models import User
from django.db import IntegrityError, transaction
from django.test import TestCase

from recruitment.models import (
    AutomationApproval,
    AutomationEvidence,
    BossAccount,
    ExecutionBatch,
    StepExecution,
    RpaTask,
)


class AutomationModelTests(TestCase):
    def setUp(self):
        self.hr = User.objects.create_user(username="foundation-hr")
        self.account = BossAccount.objects.create(
            name="foundation-account",
            browser_profile="boss-foundation",
            cdp_port=53480,
        )

    def test_approval_batch_and_step_defaults(self):
        approval = AutomationApproval.objects.create(
            action=AutomationApproval.Action.SYNC_POSITIONS,
            boss_account=self.account,
            created_by=self.hr,
            payload={"account_id": self.account.id},
            item_count=1,
        )
        batch = ExecutionBatch.objects.create(
            approval=approval,
            boss_account=self.account,
            action=approval.action,
            idempotency_key="sync:foundation:1",
            created_by=self.hr,
        )
        step = StepExecution.objects.create(batch=batch, target_key="account")

        self.assertEqual(approval.status, AutomationApproval.Status.DRAFT)
        self.assertEqual(batch.status, ExecutionBatch.Status.PENDING)
        self.assertEqual(step.status, StepExecution.Status.PENDING)

    def test_batch_idempotency_key_is_unique(self):
        first = ExecutionBatch.objects.create(
            boss_account=self.account,
            action="sync_positions",
            idempotency_key="same-key",
            created_by=self.hr,
        )
        self.assertIsNotNone(first.pk)
        with self.assertRaises(IntegrityError), transaction.atomic():
            ExecutionBatch.objects.create(
                boss_account=self.account,
                action="sync_positions",
                idempotency_key="same-key",
                created_by=self.hr,
            )

    def test_evidence_does_not_require_a_file(self):
        batch = ExecutionBatch.objects.create(
            boss_account=self.account,
            action="sync_positions",
            idempotency_key="evidence-key",
            created_by=self.hr,
        )
        step = StepExecution.objects.create(batch=batch, target_key="account")
        evidence = AutomationEvidence.objects.create(
            step=step,
            kind="page_state",
            summary="职位列表已读取",
            metadata={"url_path": "/web/chat/job/list"},
        )
        self.assertEqual(evidence.file.name, "")

    def test_rpa_task_can_own_persistent_execution_evidence(self):
        task = RpaTask.objects.create(
            boss_account=self.account,
            action=RpaTask.Action.SEARCH_AND_PULL_RESUMES,
            created_by=self.hr,
        )

        evidence = AutomationEvidence.objects.create(
            task=task,
            kind="resume_preview_attempt",
            summary="候选人身份复核后尝试查看在线简历",
            metadata={"external_id_hash": "stable-id-hash", "outcome": "preview_succeeded"},
        )

        self.assertEqual(evidence.task, task)
        self.assertIsNone(evidence.step)

    def test_evidence_requires_exactly_one_step_or_task_owner(self):
        task = RpaTask.objects.create(
            boss_account=self.account,
            action=RpaTask.Action.SEARCH_AND_PULL_RESUMES,
            created_by=self.hr,
        )
        batch = ExecutionBatch.objects.create(
            boss_account=self.account,
            action="sync_positions",
            idempotency_key="evidence-xor",
            created_by=self.hr,
        )
        step = StepExecution.objects.create(batch=batch, target_key="account")

        with self.assertRaises(IntegrityError), transaction.atomic():
            AutomationEvidence.objects.create(
                kind="invalid_owner",
                summary="缺少证据所有者",
            )
        with self.assertRaises(IntegrityError), transaction.atomic():
            AutomationEvidence.objects.create(
                task=task,
                step=step,
                kind="invalid_owner",
                summary="存在两个证据所有者",
            )
