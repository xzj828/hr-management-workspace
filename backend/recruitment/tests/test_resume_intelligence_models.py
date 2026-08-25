from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase

from recruitment.models import (
    AiProcessingTask,
    BossAccount,
    Candidate,
    FileTextExtraction,
    JobApplication,
    JobRequirementDocument,
    JobRequirementDocumentVersion,
    JobStandardVersion,
    RecruitmentJob,
    Resume,
    ResumeAssessment,
    StructuredResumeVersion,
)


class ResumeIntelligenceModelTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="intelligence-owner", password="secret")
        self.account = BossAccount.objects.create(
            name="Intelligence account", browser_profile="intelligence-account", cdp_port=54121
        )
        self.account.authorized_users.add(self.user)
        self.job = RecruitmentJob.objects.create(
            boss_account=self.account, external_id="job-intelligence", title="产品经理", owner=self.user
        )
        self.document = JobRequirementDocument.objects.create(
            job=self.job,
            category=JobRequirementDocument.Category.REQUIREMENT,
            title="产品经理要求",
            created_by=self.user,
        )
        self.document_version = JobRequirementDocumentVersion.objects.create(
            document=self.document,
            version=1,
            original_name="requirement.docx",
            file="recruitment/job-documents/requirement.docx",
            file_size=100,
            sha256="a" * 64,
            uploaded_by=self.user,
        )
        self.document.current_version = self.document_version
        self.document.save(update_fields=["current_version"])
        self.candidate = Candidate.objects.create(identity_key="intelligence-candidate", name="林然")
        self.application = JobApplication.objects.create(candidate=self.candidate, job=self.job, source="boss")
        self.resume = Resume.objects.create(
            candidate=self.candidate,
            application=self.application,
            original_name="resume.pdf",
            file="recruitment/resumes/resume.pdf",
            content_type="application/pdf",
            file_size=120,
            sha256="b" * 64,
        )

    def test_file_extraction_is_unique_for_source_version(self):
        values = {
            "source_kind": FileTextExtraction.SourceKind.RESUME,
            "source_id": self.resume.id,
            "source_sha256": self.resume.sha256,
            "method": FileTextExtraction.Method.PDF_TEXT,
            "plain_text": "候选人简历",
            "blocks": [{"id": "resume-block-1", "text": "候选人简历"}],
            "status": FileTextExtraction.Status.READY,
        }
        FileTextExtraction.objects.create(**values)

        with self.assertRaises(IntegrityError), transaction.atomic():
            FileTextExtraction.objects.create(**values)

    def test_job_standard_versions_are_unique_and_only_one_can_be_published(self):
        first = JobStandardVersion.objects.create(
            job=self.job,
            version=1,
            status=JobStandardVersion.Status.PUBLISHED,
            criteria={"dimensions": []},
            created_by=self.user,
            published_by=self.user,
        )
        first.source_document_versions.add(self.document_version)

        with self.assertRaises(IntegrityError), transaction.atomic():
            JobStandardVersion.objects.create(
                job=self.job,
                version=2,
                status=JobStandardVersion.Status.PUBLISHED,
                criteria={"dimensions": []},
                created_by=self.user,
            )

        with self.assertRaises(IntegrityError), transaction.atomic():
            JobStandardVersion.objects.create(
                job=self.job,
                version=1,
                status=JobStandardVersion.Status.DRAFT,
                criteria={"dimensions": []},
                created_by=self.user,
            )

    def test_published_standard_rejects_direct_mutation(self):
        standard = JobStandardVersion.objects.create(
            job=self.job,
            version=1,
            status=JobStandardVersion.Status.PUBLISHED,
            criteria={"summary": "原始标准", "dimensions": []},
            created_by=self.user,
            published_by=self.user,
        )
        standard.criteria = {"summary": "被修改", "dimensions": []}

        with self.assertRaises(ValidationError):
            standard.save()

    def test_structured_resume_versions_and_assessment_keep_exact_inputs(self):
        extraction = FileTextExtraction.objects.create(
            source_kind=FileTextExtraction.SourceKind.RESUME,
            source_id=self.resume.id,
            source_sha256=self.resume.sha256,
            method=FileTextExtraction.Method.PDF_TEXT,
            plain_text="5 年产品经验",
            blocks=[{"id": "resume-block-1", "text": "5 年产品经验"}],
            status=FileTextExtraction.Status.READY,
        )
        structured = StructuredResumeVersion.objects.create(
            resume=self.resume,
            version=1,
            extraction=extraction,
            data={"summary": "5 年产品经验"},
            evidence=[{"field": "summary", "block_ids": ["resume-block-1"]}],
            model_name="example-chat",
        )
        standard = JobStandardVersion.objects.create(
            job=self.job,
            version=1,
            status=JobStandardVersion.Status.DRAFT,
            criteria={"dimensions": [{"key": "experience", "weight": 100}]},
            created_by=self.user,
        )
        assessment = ResumeAssessment.objects.create(
            structured_resume=structured,
            standard=standard,
            total_score="80.00",
            dimension_scores=[{"criterion_key": "experience", "score": 80, "max_score": 100}],
            evidence=[{"block_ids": ["resume-block-1"]}],
            confidence="0.800",
            recommendation=ResumeAssessment.Recommendation.ADVANCE,
            model_name="example-chat",
        )

        self.assertEqual(assessment.structured_resume.resume, self.resume)
        self.assertEqual(assessment.standard, standard)
        with self.assertRaises(IntegrityError), transaction.atomic():
            StructuredResumeVersion.objects.create(
                resume=self.resume,
                version=1,
                extraction=extraction,
                data={},
                model_name="other-model",
            )

    def test_ai_task_idempotency_key_is_unique_and_targets_are_optional(self):
        task = AiProcessingTask.objects.create(
            kind=AiProcessingTask.Kind.JOB_STANDARD,
            status=AiProcessingTask.Status.PENDING,
            requested_by=self.user,
            job=self.job,
            idempotency_key="job-standard:1:abc",
        )
        self.assertIsNone(task.resume_id)
        self.assertIsNone(task.standard_id)

        with self.assertRaises(IntegrityError), transaction.atomic():
            AiProcessingTask.objects.create(
                kind=AiProcessingTask.Kind.JOB_STANDARD,
                requested_by=self.user,
                idempotency_key="job-standard:1:abc",
            )
