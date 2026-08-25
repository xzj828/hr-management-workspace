import uuid

from django.contrib.auth.models import User
from django.test import TestCase
from rest_framework.test import APITestCase

from accounts.crypto import encrypt_secret
from accounts.models import UserModelCredential
from attendance.models import AccountProfile
from recruitment.models import (
    AiProcessingTask,
    BossAccount,
    Candidate,
    FileTextExtraction,
    JobApplication,
    JobStandardVersion,
    RecruitmentJob,
    Resume,
    ResumeAssessment,
    StructuredResumeVersion,
)
from recruitment.services.resume_intelligence import (
    create_assessment,
    create_structured_resume,
    validate_assessment_payload,
    validate_structured_payload,
)


def structured_payload(block_id, *, include_sensitive=False):
    basics = {
        "name": "林然",
        "phone": "13800000000",
        "email": "candidate@example.com",
        "city": "北京",
        "target_role": "产品经理",
    }
    if include_sensitive:
        basics["gender"] = "女"
    return {
        "data": {
            "basics": basics,
            "summary": "五年产品经验",
            "work_experiences": [
                {
                    "company": "示例科技",
                    "role": "产品经理",
                    "start": "2021-01",
                    "end": None,
                    "description": "负责企业产品",
                    "evidence_block_ids": [block_id],
                }
            ],
            "project_experiences": [],
            "educations": [],
            "skills": ["需求分析"],
            "certificates": [],
            "languages": [],
            "total_experience_months": 60,
            "achievements": [
                {"text": "推动产品上线", "evidence_block_ids": [block_id]}
            ],
            "unknown_fields": ["学历未提供"],
        },
        "evidence": [{"field": "summary", "block_ids": [block_id]}],
        "warnings": [],
    }


class FakeGateway:
    def __init__(self, payload):
        self.payload = payload
        self.credential = type("Credential", (), {"model": "example-chat"})()

    def complete_json(self, **kwargs):
        self.user = kwargs["user"]
        return type("Result", (), {"data": self.payload})()


class StructuredResumeServiceTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="structure-owner", password="secret")
        self.account = BossAccount.objects.create(
            name="Structure account", browser_profile="structure-account", cdp_port=54151
        )
        self.job = RecruitmentJob.objects.create(
            boss_account=self.account, external_id="structure-job", title="产品经理", owner=self.user
        )
        self.candidate = Candidate.objects.create(identity_key="structure-candidate", name="林然")
        self.application = JobApplication.objects.create(candidate=self.candidate, job=self.job, source="boss")

    def make_resume(self, suffix, content_type, sha):
        return Resume.objects.create(
            candidate=self.candidate,
            application=self.application,
            original_name=f"resume.{suffix}",
            file=f"recruitment/resumes/resume.{suffix}",
            content_type=content_type,
            file_size=100,
            sha256=sha,
            version=Resume.objects.filter(candidate=self.candidate).count() + 1,
        )

    def make_extraction(self, resume, method):
        block_id = f"resume-{resume.id}-block-1"
        extraction = FileTextExtraction.objects.create(
            source_kind="resume",
            source_id=resume.id,
            source_sha256=resume.sha256,
            method=method,
            plain_text="五年产品经验",
            blocks=[{"id": block_id, "text": "五年产品经验", "page": 1, "bbox": [0, 0, 100, 30]}],
            status="ready",
        )
        return extraction, block_id

    def test_pdf_and_png_create_the_same_structured_schema(self):
        results = []
        for suffix, content_type, method, sha in (
            ("pdf", "application/pdf", "pdf_text", "f" * 64),
            ("png", "image/png", "image_ocr", "1" * 64),
        ):
            resume = self.make_resume(suffix, content_type, sha)
            extraction, block_id = self.make_extraction(resume, method)
            structured = create_structured_resume(
                resume=resume,
                extraction=extraction,
                gateway=FakeGateway(structured_payload(block_id)),
            )
            results.append(structured)

        self.assertEqual(set(results[0].data), set(results[1].data))
        self.assertEqual(results[0].data["summary"], "五年产品经验")
        self.assertEqual(results[1].evidence[0]["block_ids"], [f"resume-{results[1].resume_id}-block-1"])

    def test_unknown_evidence_is_rejected(self):
        resume = self.make_resume("pdf", "application/pdf", "2" * 64)
        extraction, _ = self.make_extraction(resume, "pdf_text")

        with self.assertRaises(ValueError):
            validate_structured_payload(structured_payload("missing-block"), extraction=extraction)

    def test_sensitive_demographic_fields_are_removed_and_recorded_as_warning(self):
        resume = self.make_resume("png", "image/png", "3" * 64)
        extraction, block_id = self.make_extraction(resume, "image_ocr")

        normalized = validate_structured_payload(
            structured_payload(block_id, include_sensitive=True),
            extraction=extraction,
        )

        self.assertNotIn("gender", normalized["data"]["basics"])
        self.assertTrue(any("敏感" in warning for warning in normalized["warnings"]))


class StructuredResumeApiTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="structure-hr")
        AccountProfile.objects.create(user=self.user, role=AccountProfile.Role.HR)
        self.account = BossAccount.objects.create(name="Structure API", browser_profile="structure-api", cdp_port=54152)
        self.account.authorized_users.add(self.user)
        self.job = RecruitmentJob.objects.create(
            boss_account=self.account, external_id="structure-api-job", title="后端工程师", owner=self.user
        )
        candidate = Candidate.objects.create(identity_key="structure-api-candidate", name="周宁")
        application = JobApplication.objects.create(candidate=candidate, job=self.job, source="boss")
        self.resume = Resume.objects.create(
            candidate=candidate,
            application=application,
            original_name="resume.pdf",
            file="recruitment/resumes/api-resume.pdf",
            content_type="application/pdf",
            file_size=100,
            sha256="4" * 64,
        )
        self.block_id = f"resume-{self.resume.id}-block-1"
        extraction = FileTextExtraction.objects.create(
            source_kind="resume",
            source_id=self.resume.id,
            source_sha256=self.resume.sha256,
            method="pdf_text",
            plain_text="三年后端经验",
            blocks=[{"id": self.block_id, "text": "三年后端经验"}],
            status="ready",
        )
        self.structured = StructuredResumeVersion.objects.create(
            resume=self.resume,
            version=1,
            extraction=extraction,
            data=structured_payload(self.block_id)["data"],
            evidence=structured_payload(self.block_id)["evidence"],
            model_name="example-chat",
        )
        UserModelCredential.objects.create(
            user=self.user,
            api_url="https://models.example/v1",
            model="example-chat",
            encrypted_api_key=encrypt_secret("sk-structure-1234"),
            key_last4="1234",
        )
        self.task = AiProcessingTask.objects.create(
            kind="resume_structure",
            status="failed",
            requested_by=self.user,
            job=self.job,
            resume=self.resume,
            idempotency_key="structure-api-failed",
            error_code="model_timeout",
            error_message="模型超时",
        )
        self.client.force_login(self.user)

    def test_lists_structure_and_exposes_latest_status_on_resume(self):
        response = self.client.get(f"/api/recruitment/structured-resumes/?resume={self.resume.id}")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(response.data["results"][0]["data"]["summary"], "五年产品经验")

        resumes = self.client.get(f"/api/recruitment/resumes/?job={self.job.id}")
        self.assertEqual(resumes.data["results"][0]["latest_structure_id"], self.structured.id)
        self.assertEqual(resumes.data["results"][0]["intelligence_status"], "completed")

    def test_structure_list_can_be_scoped_to_the_selected_job(self):
        response = self.client.get(f"/api/recruitment/structured-resumes/?job={self.job.id}")
        empty = self.client.get("/api/recruitment/structured-resumes/?job=999999")
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(empty.data["count"], 0)

    def test_retry_actions_clear_failed_task(self):
        retried = self.client.post(f"/api/recruitment/ai-tasks/{self.task.id}/retry/", {}, format="json")
        self.assertEqual(retried.status_code, 200, retried.data)
        self.assertEqual(retried.data["status"], "pending")

        self.task.status = "failed"
        self.task.save(update_fields=["status"])
        resume_retry = self.client.post(f"/api/recruitment/resumes/{self.resume.id}/retry-structure/", {}, format="json")
        self.assertEqual(resume_retry.status_code, 200, resume_retry.data)

    def test_other_user_cannot_read_structure_or_task(self):
        other = User.objects.create_user(username="structure-other")
        AccountProfile.objects.create(user=other, role=AccountProfile.Role.HR)
        self.client.force_login(other)

        structure = self.client.get(f"/api/recruitment/structured-resumes/{self.structured.id}/")
        task = self.client.get(f"/api/recruitment/ai-tasks/{self.task.id}/")
        self.assertEqual(structure.status_code, 404)
        self.assertEqual(task.status_code, 404)


def scoring_criteria():
    return {
        "summary": "后端岗位",
        "dimensions": [
            {"key": "experience", "name": "相关经验", "weight": 60, "description": "后端经验", "evidence_block_ids": []},
            {"key": "skills", "name": "技术能力", "weight": 40, "description": "Python 技能", "evidence_block_ids": []},
        ],
        "required": [],
        "preferred": [],
        "risks": [],
    }


def assessment_payload(block_id):
    return {
        "total_score": 99,
        "dimension_scores": [
            {
                "criterion_key": "experience",
                "score": 48,
                "max_score": 60,
                "status": "supported",
                "reason": "有相关经验",
                "resume_evidence_block_ids": [block_id],
            },
            {
                "criterion_key": "skills",
                "score": 0,
                "max_score": 40,
                "status": "information_missing",
                "reason": "未提供足够信息",
                "resume_evidence_block_ids": [],
            },
        ],
        "evidence": [{"criterion_key": "experience", "block_ids": [block_id]}],
        "gaps": ["Python 深度信息不足"],
        "verification_questions": ["请补充 Python 项目细节"],
        "confidence": 0.75,
        "recommendation": "review",
    }


class ResumeAssessmentServiceTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="assessment-owner")
        self.account = BossAccount.objects.create(
            name="Assessment account", browser_profile="assessment-account", cdp_port=54153
        )
        self.job = RecruitmentJob.objects.create(
            boss_account=self.account, external_id="assessment-job", title="后端工程师", owner=self.user
        )
        candidate = Candidate.objects.create(identity_key="assessment-candidate", name="陈思")
        application = JobApplication.objects.create(candidate=candidate, job=self.job, source="boss")
        resume = Resume.objects.create(
            candidate=candidate,
            application=application,
            original_name="assessment.pdf",
            file="recruitment/resumes/assessment.pdf",
            content_type="application/pdf",
            file_size=100,
            sha256="5" * 64,
        )
        self.block_id = f"resume-{resume.id}-block-1"
        extraction = FileTextExtraction.objects.create(
            source_kind="resume",
            source_id=resume.id,
            source_sha256=resume.sha256,
            method="pdf_text",
            plain_text="五年后端经验",
            blocks=[{"id": self.block_id, "text": "五年后端经验"}],
            status="ready",
        )
        self.structured = StructuredResumeVersion.objects.create(
            resume=resume,
            version=1,
            extraction=extraction,
            data=structured_payload(self.block_id)["data"],
            evidence=structured_payload(self.block_id)["evidence"],
            model_name="example-chat",
        )
        self.standard = JobStandardVersion.objects.create(
            job=self.job,
            version=1,
            status="published",
            criteria=scoring_criteria(),
            created_by=self.user,
            published_by=self.user,
        )

    def test_server_recomputes_total_and_keeps_evidence(self):
        normalized = validate_assessment_payload(
            payload=assessment_payload(self.block_id),
            standard=self.standard,
            structured=self.structured,
        )
        self.assertEqual(normalized["total_score"], 48)
        self.assertEqual(normalized["recommendation"], "review")

    def test_nonzero_score_without_resume_evidence_is_rejected(self):
        payload = assessment_payload(self.block_id)
        payload["dimension_scores"][0]["resume_evidence_block_ids"] = []
        with self.assertRaises(ValueError):
            validate_assessment_payload(payload=payload, standard=self.standard, structured=self.structured)

    def test_rescoring_same_inputs_creates_a_new_assessment_version(self):
        gateway = FakeGateway(assessment_payload(self.block_id))
        first = create_assessment(
            structured=self.structured,
            standard=self.standard,
            gateway=gateway,
            request_id=uuid.uuid4(),
        )
        second = create_assessment(
            structured=self.structured,
            standard=self.standard,
            gateway=gateway,
            request_id=uuid.uuid4(),
        )
        self.assertEqual((first.version, second.version), (1, 2))
        self.assertEqual(first.total_score, second.total_score)

    def test_replaying_same_task_request_returns_existing_assessment(self):
        gateway = FakeGateway(assessment_payload(self.block_id))
        request_id = uuid.uuid4()
        first = create_assessment(
            structured=self.structured,
            standard=self.standard,
            gateway=gateway,
            request_id=request_id,
        )
        second = create_assessment(
            structured=self.structured,
            standard=self.standard,
            gateway=gateway,
            request_id=request_id,
        )
        self.assertEqual(first.pk, second.pk)
        self.assertEqual(ResumeAssessment.objects.count(), 1)


class ResumeAssessmentApiTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="assessment-hr")
        AccountProfile.objects.create(user=self.user, role=AccountProfile.Role.HR)
        self.account = BossAccount.objects.create(
            name="Assessment API", browser_profile="assessment-api", cdp_port=54154
        )
        self.account.authorized_users.add(self.user)
        self.job = RecruitmentJob.objects.create(
            boss_account=self.account, external_id="assessment-api-job", title="数据工程师", owner=self.user
        )
        candidate = Candidate.objects.create(identity_key="assessment-api-candidate", name="顾言")
        self.application = JobApplication.objects.create(candidate=candidate, job=self.job, source="boss")
        self.resume = Resume.objects.create(
            candidate=candidate,
            application=self.application,
            original_name="assessment-api.pdf",
            file="recruitment/resumes/assessment-api.pdf",
            content_type="application/pdf",
            file_size=100,
            sha256="6" * 64,
        )
        self.block_id = f"resume-{self.resume.id}-block-1"
        extraction = FileTextExtraction.objects.create(
            source_kind="resume",
            source_id=self.resume.id,
            source_sha256=self.resume.sha256,
            method="pdf_text",
            plain_text="五年数据经验",
            blocks=[{"id": self.block_id, "text": "五年数据经验"}],
            status="ready",
        )
        self.structured = StructuredResumeVersion.objects.create(
            resume=self.resume,
            version=1,
            extraction=extraction,
            data=structured_payload(self.block_id)["data"],
            evidence=structured_payload(self.block_id)["evidence"],
            model_name="example-chat",
        )
        UserModelCredential.objects.create(
            user=self.user,
            api_url="https://models.example/v1",
            model="example-chat",
            encrypted_api_key=encrypt_secret("sk-assessment-1234"),
            key_last4="1234",
        )
        self.client.force_login(self.user)

    def test_scoring_is_blocked_before_standard_is_published(self):
        response = self.client.post(
            "/api/recruitment/resume-assessments/score/",
            {"request_id": str(uuid.uuid4()), "job": self.job.id, "resume_ids": [self.resume.id]},
            format="json",
        )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data["code"], "standard_not_published")

    def test_batch_scoring_is_idempotent_and_does_not_change_stage(self):
        standard = JobStandardVersion.objects.create(
            job=self.job,
            version=1,
            status="published",
            criteria=scoring_criteria(),
            created_by=self.user,
            published_by=self.user,
        )
        request_id = uuid.uuid4()
        payload = {"request_id": str(request_id), "job": self.job.id, "resume_ids": [self.resume.id, 999999]}

        first = self.client.post("/api/recruitment/resume-assessments/score/", payload, format="json")
        second = self.client.post("/api/recruitment/resume-assessments/score/", payload, format="json")

        self.assertEqual(first.status_code, 202, first.data)
        self.assertEqual(first.data["results"][0]["resume_id"], self.resume.id)
        self.assertIn("task_id", first.data["results"][0])
        self.assertEqual(first.data["results"][1]["code"], "resume_not_ready")
        self.assertEqual(first.data["results"][0]["task_id"], second.data["results"][0]["task_id"])
        self.application.refresh_from_db()
        self.assertEqual(self.application.stage, JobApplication.Stage.NEW)
        self.assertEqual(AiProcessingTask.objects.filter(kind="resume_score", standard=standard).count(), 1)

    def test_rescore_creates_a_new_task_request(self):
        standard = JobStandardVersion.objects.create(
            job=self.job,
            version=1,
            status="published",
            criteria=scoring_criteria(),
            created_by=self.user,
            published_by=self.user,
        )
        assessment = ResumeAssessment.objects.create(
            structured_resume=self.structured,
            standard=standard,
            version=1,
            request_id=uuid.uuid4(),
            total_score=48,
            dimension_scores=assessment_payload(self.block_id)["dimension_scores"],
            evidence=[],
            confidence="0.750",
            recommendation="review",
            model_name="example-chat",
        )
        response = self.client.post(
            f"/api/recruitment/resume-assessments/{assessment.id}/rescore/",
            {"request_id": str(uuid.uuid4())},
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data["status"], "pending")
