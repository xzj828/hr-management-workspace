from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.utils import timezone

from accounts.crypto import encrypt_secret
from accounts.models import UserModelCredential
from accounts.services.model_gateway import ModelGatewayError
from recruitment.models import (
    AiProcessingTask,
    BossAccount,
    Candidate,
    JobApplication,
    JobRequirementDocument,
    RecruitmentJob,
    Resume,
)
from recruitment.services.ai_tasks import (
    enqueue_job_standard,
    enqueue_resume_structure,
    execute_task,
    lease_next_task,
    retry_task,
)
from recruitment.services.job_documents import create_document
from recruitment.services.resumes import archive_pdf


class AiTaskServiceTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="ai-owner", password="secret")
        self.account = BossAccount.objects.create(name="AI account", browser_profile="ai-account", cdp_port=54131)
        self.account.authorized_users.add(self.user)
        self.job = RecruitmentJob.objects.create(
            boss_account=self.account, external_id="ai-job", title="产品经理", owner=self.user
        )
        candidate = Candidate.objects.create(identity_key="ai-candidate", name="林然")
        self.application = JobApplication.objects.create(candidate=candidate, job=self.job, source="boss")
        self.resume = Resume.objects.create(
            candidate=candidate,
            application=self.application,
            original_name="resume.pdf",
            file="recruitment/resumes/resume.pdf",
            content_type="application/pdf",
            file_size=100,
            sha256="c" * 64,
        )

    def configure_model(self):
        return UserModelCredential.objects.create(
            user=self.user,
            api_url="https://models.example/v1",
            model="example-chat",
            encrypted_api_key=encrypt_secret("sk-ai-1234"),
            key_last4="1234",
        )

    def add_document(self, name="requirement.docx", content=b"first requirement"):
        with self.captureOnCommitCallbacks(execute=False):
            document = create_document(
                job=self.job,
                category=JobRequirementDocument.Category.REQUIREMENT,
                title="岗位需求",
                upload=SimpleUploadedFile(name, content),
                actor=self.user,
            )
        return document

    def test_job_task_hashes_all_current_documents_and_is_idempotent(self):
        self.configure_model()
        first = self.add_document(content=b"first")
        second = self.add_document(name="persona.docx", content=b"second")

        task, created = enqueue_job_standard(job=self.job, requested_by=self.user)
        duplicate, duplicate_created = enqueue_job_standard(job=self.job, requested_by=self.user)

        self.assertTrue(created)
        self.assertFalse(duplicate_created)
        self.assertEqual(duplicate.pk, task.pk)
        self.assertEqual(task.status, AiProcessingTask.Status.PENDING)
        self.assertIn(first.current_version.sha256[:12], task.idempotency_key)
        self.assertIn(second.current_version.sha256[:12], task.idempotency_key)

    def test_missing_model_configuration_waits_without_losing_task(self):
        task, created = enqueue_resume_structure(resume=self.resume, requested_by=self.user)

        self.assertTrue(created)
        self.assertEqual(task.status, AiProcessingTask.Status.WAITING_CONFIG)
        self.assertEqual(task.resume, self.resume)

    def test_expired_lease_is_recovered_and_leased_again(self):
        self.configure_model()
        task, _ = enqueue_resume_structure(resume=self.resume, requested_by=self.user)
        task.status = AiProcessingTask.Status.MODEL
        task.leased_at = timezone.now() - timedelta(minutes=5)
        task.lease_expires_at = timezone.now() - timedelta(seconds=1)
        task.save(update_fields=["status", "leased_at", "lease_expires_at", "updated_at"])

        leased = lease_next_task(lease_seconds=120)

        self.assertEqual(leased.pk, task.pk)
        self.assertEqual(leased.status, AiProcessingTask.Status.MODEL)
        self.assertGreater(leased.lease_expires_at, timezone.now())

    def test_retryable_model_failure_uses_bounded_backoff(self):
        self.configure_model()
        task, _ = enqueue_resume_structure(resume=self.resume, requested_by=self.user)

        with patch.dict(
            "recruitment.services.ai_tasks.TASK_EXECUTORS",
            {AiProcessingTask.Kind.RESUME_STRUCTURE: lambda _task: (_ for _ in ()).throw(
                ModelGatewayError("model_rate_limited", "rate limited", retryable=True)
            )},
            clear=True,
        ):
            execute_task(task)

        task.refresh_from_db()
        self.assertEqual(task.status, AiProcessingTask.Status.PENDING)
        self.assertEqual(task.attempt_count, 1)
        self.assertEqual(task.error_code, "model_rate_limited")
        self.assertGreaterEqual(task.available_at, timezone.now() + timedelta(seconds=25))

    def test_non_retryable_failure_stops_and_manual_retry_clears_error(self):
        self.configure_model()
        task, _ = enqueue_resume_structure(resume=self.resume, requested_by=self.user)

        with patch.dict(
            "recruitment.services.ai_tasks.TASK_EXECUTORS",
            {AiProcessingTask.Kind.RESUME_STRUCTURE: lambda _task: (_ for _ in ()).throw(
                ModelGatewayError("model_auth_failed", "bad key")
            )},
            clear=True,
        ):
            execute_task(task)

        task.refresh_from_db()
        self.assertEqual(task.status, AiProcessingTask.Status.FAILED)
        retried = retry_task(task=task, requested_by=self.user)
        self.assertEqual(retried.status, AiProcessingTask.Status.PENDING)
        self.assertEqual(retried.error_code, "")
        self.assertEqual(retried.attempt_count, 0)

    def test_successful_executor_persists_result_reference(self):
        self.configure_model()
        task, _ = enqueue_resume_structure(resume=self.resume, requested_by=self.user)

        with patch.dict(
            "recruitment.services.ai_tasks.TASK_EXECUTORS",
            {AiProcessingTask.Kind.RESUME_STRUCTURE: lambda _task: {"structured_resume_id": 42}},
            clear=True,
        ):
            execute_task(task)

        task.refresh_from_db()
        self.assertEqual(task.status, AiProcessingTask.Status.SUCCEEDED)
        self.assertEqual(task.result_ref, {"structured_resume_id": 42})
        self.assertEqual(task.progress, 100)

    def test_word_and_resume_ingestion_enqueue_after_commit(self):
        self.configure_model()
        with self.captureOnCommitCallbacks(execute=True):
            document = create_document(
                job=self.job,
                category=JobRequirementDocument.Category.PERSONA,
                title="用户画像",
                upload=SimpleUploadedFile("persona.docx", b"persona"),
                actor=self.user,
            )
        self.assertTrue(AiProcessingTask.objects.filter(job=self.job, document_version=document.current_version).exists())

        with self.captureOnCommitCallbacks(execute=True):
            archived, created = archive_pdf(
                application=self.application,
                filename="archived.pdf",
                content=b"%PDF-1.4\nsynthetic resume",
                actor=self.user,
            )
        self.assertTrue(created)
        self.assertTrue(AiProcessingTask.objects.filter(resume=archived).exists())
