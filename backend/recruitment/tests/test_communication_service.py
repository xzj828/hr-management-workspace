import uuid

from django.contrib.auth.models import User
from django.test import TestCase
from rest_framework.exceptions import ValidationError

from attendance.models import AccountProfile
from recruitment.models import (
    AutomationApproval,
    AutomationUsage,
    BossAccount,
    Candidate,
    CandidateDiscovery,
    CandidateExternalIdentity,
    ConversationAction,
    ExecutionBatch,
    HumanAttention,
    JobApplication,
    RecruitmentJob,
    RpaTask,
    StepExecution,
    WorkflowNodeRun,
    WorkflowRun,
    WorkflowTemplate,
    WorkflowVersion,
)
from recruitment.rpa.tasks import create_task
from recruitment.services.approvals import approve
from recruitment.services.communications import (
    cancel_workflow_communication,
    complete_communication_task,
    materialize_communication_batch,
    prepare_communication,
)


class CommunicationServiceTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("hr-comms")
        AccountProfile.objects.update_or_create(user=self.user, defaults={"role": AccountProfile.Role.HR})
        self.account = BossAccount.objects.create(
            name="沟通账号", browser_profile="comms-profile", cdp_port=53522,
            daily_contact_limit=10, daily_message_limit=10,
        )
        self.account.authorized_users.add(self.user)
        self.job = RecruitmentJob.objects.create(
            boss_account=self.account, external_id="job-comms", title="产品经理", owner=self.user
        )
        self.applications = []
        for index in range(2):
            candidate = Candidate.objects.create(
                identity_key=f"candidate-{index}",
                external_id=f"boss-candidate-{index}",
                name=f"候选人{index}",
            )
            CandidateExternalIdentity.objects.create(
                boss_account=self.account,
                candidate=candidate,
                external_id=f"boss-candidate-{index}",
                fingerprint=f"{index + 1:064x}",
                identity_quality=CandidateDiscovery.IdentityQuality.PLATFORM,
            )
            self.applications.append(JobApplication.objects.create(
                candidate=candidate, job=self.job, source="boss", owner=self.user
            ))

    def test_prepare_only_creates_draft_snapshot(self):
        approval = prepare_communication(
            account=self.account,
            applications=self.applications,
            action=ConversationAction.Action.GREET,
            message="你好，想和你聊聊产品经理岗位。",
            actor=self.user,
            request_id=uuid.uuid4(),
        )
        self.assertEqual(approval.status, AutomationApproval.Status.DRAFT)
        self.assertEqual(approval.item_count, 2)
        self.assertEqual(ConversationAction.objects.filter(status="draft").count(), 2)
        self.assertEqual(ExecutionBatch.objects.count(), 0)
        self.assertEqual(AutomationUsage.objects.count(), 0)

    def test_prepare_idempotency_key_rejects_candidate_or_message_substitution(self):
        request_id = uuid.uuid4()
        prepare_communication(
            account=self.account,
            applications=[self.applications[0]],
            action=ConversationAction.Action.GREET,
            message="统一话术一",
            actor=self.user,
            request_id=request_id,
        )

        with self.assertRaisesMessage(ValidationError, "请求标识已被不同候选人或话术使用"):
            prepare_communication(
                account=self.account,
                applications=[self.applications[1]],
                action=ConversationAction.Action.GREET,
                message="统一话术二",
                actor=self.user,
                request_id=request_id,
            )

        self.assertEqual(AutomationApproval.objects.count(), 1)
        self.assertEqual(ConversationAction.objects.count(), 1)

    def test_approval_materializes_independent_steps_and_enqueues_first(self):
        approval = prepare_communication(
            account=self.account,
            applications=self.applications,
            action=ConversationAction.Action.REQUEST_RESUME,
            message="方便发送一份 PDF 简历吗？",
            actor=self.user,
            request_id=uuid.uuid4(),
        )
        approve(approval=approval, actor=self.user)
        batch = materialize_communication_batch(approval=approval, actor=self.user)
        self.assertEqual(batch.steps.count(), 2)
        self.assertEqual(batch.rpa_tasks.count(), 1)
        self.assertEqual(batch.rpa_tasks.get().request_payload["message"], "方便发送一份 PDF 简历吗？")
        self.assertEqual(StepExecution.objects.filter(status="pending").count(), 2)
        usage = AutomationUsage.objects.get(boss_account=self.account, metric="message")
        self.assertEqual(usage.used, 1)

    def test_successful_greet_on_other_account_is_rejected_before_approval(self):
        other = BossAccount.objects.create(name="其他账号", browser_profile="other-profile", cdp_port=53523)
        ConversationAction.objects.create(
            application=self.applications[0], boss_account=other, action="greet", status="succeeded",
            message_snapshot="已联系", idempotency_key="previous-contact", created_by=self.user,
        )
        with self.assertRaisesMessage(ValidationError, "候选人已联系"):
            prepare_communication(
                account=self.account,
                applications=[self.applications[0]],
                action="greet",
                message="你好",
                actor=self.user,
                request_id=uuid.uuid4(),
            )
        self.assertEqual(AutomationApproval.objects.count(), 0)

    def test_prepare_greet_rejects_missing_stable_identity(self):
        candidate = self.applications[0].candidate
        CandidateExternalIdentity.objects.filter(candidate=candidate, boss_account=self.account).delete()

        with self.assertRaisesMessage(ValidationError, "缺少平台稳定身份"):
            prepare_communication(
                account=self.account,
                applications=[self.applications[0]],
                action=ConversationAction.Action.GREET,
                message="你好，想和你聊聊产品经理岗位。",
                actor=self.user,
                request_id=uuid.uuid4(),
            )

        self.assertFalse(AutomationApproval.objects.exists())

    def test_prepare_greet_rejects_active_greeting_as_a_whole(self):
        ConversationAction.objects.create(
            application=self.applications[0],
            boss_account=self.account,
            action=ConversationAction.Action.GREET,
            status=ConversationAction.Status.PENDING,
            message_snapshot="你好",
            idempotency_key="active-greet",
            created_by=self.user,
        )

        with self.assertRaisesMessage(ValidationError, "已有打招呼任务处理中"):
            prepare_communication(
                account=self.account,
                applications=self.applications,
                action=ConversationAction.Action.GREET,
                message="统一话术",
                actor=self.user,
                request_id=uuid.uuid4(),
            )

        self.assertEqual(AutomationApproval.objects.count(), 0)

    def test_success_completes_one_step_advances_stage_and_enqueues_next(self):
        approval = prepare_communication(
            account=self.account, applications=self.applications, action="request_resume",
            message="请发送 PDF 简历", actor=self.user, request_id=uuid.uuid4(),
        )
        approve(approval=approval, actor=self.user)
        batch = materialize_communication_batch(approval=approval, actor=self.user)
        first_task = batch.rpa_tasks.get()
        executed_application = ConversationAction.objects.get(
            pk=first_task.request_payload["conversation_action_id"]
        ).application
        expected_external_id = first_task.request_payload["target"]["external_id"]
        complete_communication_task(
            task=first_task,
            status="succeeded",
            result={
                "verified": True,
                "expected_external_id": expected_external_id,
                "observed_external_id": expected_external_id,
            },
            error_code="", error_message="",
        )
        batch.refresh_from_db()
        executed_application.refresh_from_db()
        self.assertEqual(batch.succeeded_items, 1)
        self.assertEqual(executed_application.stage, JobApplication.Stage.WAITING_RESUME)
        self.assertEqual(batch.rpa_tasks.count(), 2)

    def test_verified_greet_advances_stage_and_resolves_matching_attention(self):
        application = self.applications[0]
        attention = HumanAttention.objects.create(
            attention_type=HumanAttention.Type.GREETING_REQUIRED,
            title="待人工打招呼",
            idempotency_key=f"greeting-required:{application.pk}",
            boss_account=self.account,
            job=self.job,
            application=application,
        )
        approval = prepare_communication(
            account=self.account,
            applications=[application],
            action=ConversationAction.Action.GREET,
            message="你好，想和你聊聊产品经理岗位。",
            actor=self.user,
            request_id=uuid.uuid4(),
        )
        approve(approval=approval, actor=self.user)
        batch = materialize_communication_batch(approval=approval, actor=self.user)
        task = batch.rpa_tasks.get()
        external_id = task.request_payload["target"]["external_id"]

        complete_communication_task(
            task=task,
            status="succeeded",
            result={
                "verified": True,
                "greeting_verified": True,
                "expected_external_id": external_id,
                "observed_external_id": external_id,
            },
            error_code="",
            error_message="",
        )

        application.refresh_from_db()
        attention.refresh_from_db()
        self.assertEqual(application.stage, JobApplication.Stage.GREETED)
        self.assertEqual(attention.status, HumanAttention.Status.RESOLVED)
        self.assertEqual(attention.resolved_by, self.user)

    def test_greet_without_native_greeting_receipt_waits_for_human(self):
        application = self.applications[0]
        approval = prepare_communication(
            account=self.account,
            applications=[application],
            action=ConversationAction.Action.GREET,
            message="统一话术",
            actor=self.user,
            request_id=uuid.uuid4(),
        )
        approve(approval=approval, actor=self.user)
        batch = materialize_communication_batch(approval=approval, actor=self.user)
        task = batch.rpa_tasks.get()
        external_id = task.request_payload["target"]["external_id"]

        complete_communication_task(
            task=task,
            status="succeeded",
            result={
                "verified": True,
                "expected_external_id": external_id,
                "observed_external_id": external_id,
            },
            error_code="",
            error_message="",
        )

        application.refresh_from_db()
        task.refresh_from_db()
        self.assertEqual(task.status, RpaTask.Status.WAITING_HUMAN)
        self.assertEqual(application.stage, JobApplication.Stage.NEW)

    def test_verified_result_without_observed_platform_id_waits_for_human(self):
        approval = prepare_communication(
            account=self.account,
            applications=[self.applications[0]],
            action="request_resume",
            message="请发送 PDF 简历",
            actor=self.user,
            request_id=uuid.uuid4(),
        )
        approve(approval=approval, actor=self.user)
        batch = materialize_communication_batch(approval=approval, actor=self.user)
        task = batch.rpa_tasks.get()

        complete_communication_task(
            task=task,
            status="succeeded",
            result={
                "verified": True,
                "expected_external_id": task.request_payload["target"]["external_id"],
            },
            error_code="",
            error_message="",
        )

        task.refresh_from_db()
        action = ConversationAction.objects.get(pk=task.request_payload["conversation_action_id"])
        action.application.refresh_from_db()
        self.assertEqual(task.status, RpaTask.Status.WAITING_HUMAN)
        self.assertEqual(action.status, ConversationAction.Status.WAITING_HUMAN)
        self.assertEqual(action.step.status, StepExecution.Status.WAITING_HUMAN)
        self.assertEqual(action.application.stage, JobApplication.Stage.NEW)

    def test_verified_result_with_wrong_observed_platform_id_waits_for_human(self):
        approval = prepare_communication(
            account=self.account,
            applications=[self.applications[0]],
            action="request_resume",
            message="请发送 PDF 简历",
            actor=self.user,
            request_id=uuid.uuid4(),
        )
        approve(approval=approval, actor=self.user)
        batch = materialize_communication_batch(approval=approval, actor=self.user)
        task = batch.rpa_tasks.get()

        complete_communication_task(
            task=task,
            status="succeeded",
            result={
                "verified": True,
                "expected_external_id": task.request_payload["target"]["external_id"],
                "observed_external_id": "boss-other-candidate",
            },
            error_code="",
            error_message="",
        )

        task.refresh_from_db()
        action = ConversationAction.objects.get(pk=task.request_payload["conversation_action_id"])
        action.application.refresh_from_db()
        self.assertEqual(task.status, RpaTask.Status.WAITING_HUMAN)
        self.assertEqual(action.status, ConversationAction.Status.WAITING_HUMAN)
        self.assertEqual(action.step.status, StepExecution.Status.WAITING_HUMAN)
        self.assertEqual(action.application.stage, JobApplication.Stage.NEW)

    def test_request_resume_cannot_be_created_without_approval(self):
        with self.assertRaisesMessage(ValidationError, "需要 HR 确认"):
            create_task(
                account=self.account,
                action=RpaTask.Action.REQUEST_RESUME,
                actor=self.user,
                request_payload={"message": "请发送简历", "target": {"name": "候选人0"}},
            )

    def test_approved_resume_request_rejects_target_or_message_substitution(self):
        approval = prepare_communication(
            account=self.account,
            applications=[self.applications[0]],
            action=ConversationAction.Action.REQUEST_RESUME,
            message="请发送 PDF 简历",
            actor=self.user,
            request_id=uuid.uuid4(),
        )
        approve(approval=approval, actor=self.user)
        action = ConversationAction.objects.get(approval=approval)

        with self.assertRaisesMessage(ValidationError, "身份快照不一致"):
            create_task(
                account=self.account,
                action=RpaTask.Action.REQUEST_RESUME,
                actor=self.user,
                approval=approval,
                request_payload={
                    "conversation_action_id": str(action.pk),
                    "message": action.message_snapshot,
                    "target": {**action.target_snapshot, "name": "被替换的候选人"},
                    "first_contact": False,
                },
            )

    def test_cancel_workflow_communication_requests_cancellation_for_running_task(self):
        template = WorkflowTemplate.objects.create(name="cancel comms", created_by=self.user)
        version = WorkflowVersion.objects.create(
            template=template, version=1, boss_account=self.account, created_by=self.user,
        )
        run = WorkflowRun.objects.create(
            version=version, boss_account=self.account, actor=self.user,
            status=WorkflowRun.Status.RUNNING, idempotency_key="cancel-comms-run",
            graph_snapshot={"nodes": [], "edges": []},
        )
        node = WorkflowNodeRun.objects.create(
            run=run, node_key="comm", node_type="greet",
            status=WorkflowNodeRun.Status.RUNNING, idempotency_key="cancel-comms-node",
        )
        batch = ExecutionBatch.objects.create(
            boss_account=self.account, action=AutomationApproval.Action.GREET,
            idempotency_key="cancel-comms-batch", created_by=self.user, total_items=1,
            workflow_node_run=node,
        )
        task = RpaTask.objects.create(
            boss_account=self.account, action=RpaTask.Action.GREET, created_by=self.user,
            status=RpaTask.Status.RUNNING, execution_batch=batch,
            request_payload={"step_id": 1, "conversation_action_id": "x"},
        )

        result = cancel_workflow_communication(workflow_node_run=node, actor=self.user)

        task.refresh_from_db()
        self.assertTrue(result)
        self.assertEqual(task.status, RpaTask.Status.CANCEL_REQUESTED)
        self.assertTrue(task.events.filter(event="cancel_requested").exists())
