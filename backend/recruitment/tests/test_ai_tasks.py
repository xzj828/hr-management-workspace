from datetime import timedelta
from importlib import import_module
from types import SimpleNamespace
from unittest.mock import patch

from django.apps import apps
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection
from django.test import TestCase
from django.utils import timezone

from accounts.crypto import decrypt_secret, encrypt_secret
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
    task_model_credential,
)
from recruitment.services.job_documents import create_document
from recruitment.services.resumes import archive_pdf
from recruitment.serializers import AiProcessingTaskSerializer


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

    def configure_model(
        self,
        *,
        user=None,
        api_url="https://models.example/v1",
        model="example-chat",
        api_key="sk-ai-1234",
    ):
        return UserModelCredential.objects.create(
            user=user or self.user,
            api_url=api_url,
            model=model,
            encrypted_api_key=encrypt_secret(api_key),
            key_last4=api_key[-4:],
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
        self.assertIsNone(task.model_snapshot_bound_at)

    def test_enqueued_task_executes_with_model_a_after_switching_to_model_b(self):
        credential = self.configure_model(model="model-a", api_key="sk-model-a")
        task, _ = enqueue_resume_structure(resume=self.resume, requested_by=self.user)
        credential.api_url = "https://models-b.example/v1"
        credential.model = "model-b"
        credential.encrypted_api_key = encrypt_secret("sk-model-b")
        credential.key_last4 = "el-b"
        credential.save()

        with (
            patch("recruitment.services.resume_intelligence._extract_resume", return_value=object()),
            patch("recruitment.services.resume_intelligence.OpenAICompatibleGateway") as gateway_class,
            patch(
                "recruitment.services.resume_intelligence.create_structured_resume",
                return_value=SimpleNamespace(pk=42),
            ),
        ):
            execute_task(task)

        frozen = gateway_class.call_args.args[0]
        self.assertEqual(frozen.api_url, "https://models.example/v1")
        self.assertEqual(frozen.model, "model-a")
        self.assertEqual(decrypt_secret(frozen.encrypted_api_key), "sk-model-a")
        task.refresh_from_db()
        self.assertEqual(task.result_ref, {"structured_resume_id": 42})

    def test_bound_task_executes_after_current_credential_is_deleted(self):
        credential = self.configure_model(model="model-a", api_key="sk-model-a")
        task, _ = enqueue_resume_structure(resume=self.resume, requested_by=self.user)
        credential.delete()
        captured = {}

        def executor(bound_task):
            captured["credential"] = task_model_credential(bound_task)
            return {"structured_resume_id": 7}

        with patch.dict(
            "recruitment.services.ai_tasks.TASK_EXECUTORS",
            {AiProcessingTask.Kind.RESUME_STRUCTURE: executor},
            clear=True,
        ):
            execute_task(task)

        self.assertEqual(captured["credential"].model, "model-a")
        self.assertEqual(decrypt_secret(captured["credential"].encrypted_api_key), "sk-model-a")

    def test_waiting_task_binds_first_available_configuration_once(self):
        task, _ = enqueue_resume_structure(resume=self.resume, requested_by=self.user)
        credential = self.configure_model(model="first-model", api_key="sk-first-model")

        leased = lease_next_task(lease_seconds=120)

        self.assertEqual(leased.pk, task.pk)
        self.assertIsNotNone(leased.model_snapshot_bound_at)
        self.assertEqual(leased.model_name_snapshot, "first-model")
        self.assertEqual(decrypt_secret(leased.encrypted_model_api_key_snapshot), "sk-first-model")
        original_snapshot = tuple(getattr(leased, field) for field in AiProcessingTask.MODEL_SNAPSHOT_FIELDS)
        credential.model = "second-model"
        credential.encrypted_api_key = encrypt_secret("sk-second-model")
        credential.save()
        leased.status = AiProcessingTask.Status.FAILED
        leased.save(update_fields=["status", "updated_at"])

        retried = retry_task(task=leased, requested_by=self.user)

        self.assertEqual(
            tuple(getattr(retried, field) for field in AiProcessingTask.MODEL_SNAPSHOT_FIELDS),
            original_snapshot,
        )
        self.assertEqual(retried.status, AiProcessingTask.Status.PENDING)

    def test_superuser_retry_binds_the_task_owners_model(self):
        task, _ = enqueue_resume_structure(resume=self.resume, requested_by=self.user)
        self.configure_model(user=self.user, model="owner-model", api_key="sk-owner-model")
        admin = User.objects.create_superuser(username="ai-admin", password="secret")
        self.configure_model(user=admin, model="admin-model", api_key="sk-admin-model")

        retried = retry_task(task=task, requested_by=admin)

        self.assertEqual(retried.status, AiProcessingTask.Status.PENDING)
        self.assertEqual(retried.requested_by, self.user)
        self.assertEqual(retried.model_name_snapshot, "owner-model")
        self.assertEqual(decrypt_secret(retried.encrypted_model_api_key_snapshot), "sk-owner-model")

    def test_task_serializer_never_exposes_model_snapshot_or_secret(self):
        self.configure_model(model="private-model", api_key="sk-private-secret")
        task, _ = enqueue_resume_structure(resume=self.resume, requested_by=self.user)

        data = AiProcessingTaskSerializer(task).data

        self.assertTrue(set(AiProcessingTask.MODEL_SNAPSHOT_FIELDS).isdisjoint(data))
        self.assertNotIn(task.encrypted_model_api_key_snapshot, str(data))
        self.assertNotIn("sk-private-secret", str(data))

    def test_bound_model_snapshot_cannot_be_modified(self):
        self.configure_model(model="immutable-model")
        task, _ = enqueue_resume_structure(resume=self.resume, requested_by=self.user)
        task.model_name_snapshot = "tampered-model"

        with self.assertRaises(ValidationError):
            task.save()

    def test_data_migration_binds_configured_legacy_tasks_and_parks_unconfigured_tasks(self):
        self.configure_model(model="migration-model", api_key="sk-migration-model")
        configured = AiProcessingTask.objects.create(
            kind=AiProcessingTask.Kind.RESUME_STRUCTURE,
            status=AiProcessingTask.Status.PENDING,
            requested_by=self.user,
            resume=self.resume,
            idempotency_key="legacy-pending-configured",
        )
        other = User.objects.create_user(username="legacy-unconfigured")
        unconfigured = AiProcessingTask.objects.create(
            kind=AiProcessingTask.Kind.RESUME_STRUCTURE,
            status=AiProcessingTask.Status.PENDING,
            requested_by=other,
            resume=self.resume,
            idempotency_key="legacy-pending-unconfigured",
        )
        migration = import_module(
            "recruitment.migrations.0026_bind_existing_ai_task_model_snapshots"
        )

        migration.bind_existing_task_snapshots(
            apps,
            SimpleNamespace(connection=connection),
        )

        configured.refresh_from_db()
        unconfigured.refresh_from_db()
        self.assertEqual(configured.status, AiProcessingTask.Status.PENDING)
        self.assertEqual(configured.model_name_snapshot, "migration-model")
        self.assertIsNotNone(configured.model_snapshot_bound_at)
        self.assertEqual(unconfigured.status, AiProcessingTask.Status.WAITING_CONFIG)
        self.assertIsNone(unconfigured.model_snapshot_bound_at)

    def test_legacy_unbound_pending_task_is_not_leased_until_it_can_bind(self):
        legacy = AiProcessingTask.objects.create(
            kind=AiProcessingTask.Kind.RESUME_STRUCTURE,
            status=AiProcessingTask.Status.PENDING,
            requested_by=self.user,
            resume=self.resume,
            idempotency_key="legacy-unbound-pending",
        )

        self.assertIsNone(lease_next_task())
        legacy.refresh_from_db()
        self.assertEqual(legacy.status, AiProcessingTask.Status.WAITING_CONFIG)
        self.configure_model(model="recovered-model", api_key="sk-recovered-model")

        leased = lease_next_task()

        self.assertEqual(leased.pk, legacy.pk)
        self.assertEqual(leased.model_name_snapshot, "recovered-model")

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
