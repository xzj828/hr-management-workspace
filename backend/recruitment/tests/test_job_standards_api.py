from django.contrib.auth.models import User
from django.test import TestCase
from rest_framework.test import APITestCase

from attendance.models import AccountProfile
from recruitment.models import (
    AiProcessingTask,
    BossAccount,
    FileTextExtraction,
    JobRequirementDocument,
    JobRequirementDocumentVersion,
    JobStandardVersion,
    RecruitmentJob,
)
from recruitment.services.job_standards import (
    create_standard_draft,
    publish_standard,
    update_standard_draft,
    validate_criteria,
)


def valid_criteria(block_id):
    return {
        "summary": "招聘有 B2B 经验的产品经理",
        "dimensions": [
            {
                "key": "experience",
                "name": "相关经验",
                "weight": 100,
                "description": "评估 B2B 产品经验",
                "evidence_block_ids": [block_id],
            }
        ],
        "required": [{"text": "具备产品经验", "evidence_block_ids": [block_id]}],
        "preferred": [],
        "risks": [],
    }


class FakeGateway:
    def __init__(self, payload):
        self.payload = payload
        self.credential = type("Credential", (), {"model": "example-chat"})()

    def complete_json(self, **kwargs):
        self.system = kwargs["system"]
        self.user = kwargs["user"]
        return type("Result", (), {"data": self.payload})()


class JobStandardServiceTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="standard-owner", password="secret")
        self.account = BossAccount.objects.create(
            name="Standard account", browser_profile="standard-account", cdp_port=54141
        )
        self.job = RecruitmentJob.objects.create(
            boss_account=self.account, external_id="standard-job", title="产品经理", owner=self.user
        )
        self.document = JobRequirementDocument.objects.create(
            job=self.job,
            category=JobRequirementDocument.Category.REQUIREMENT,
            title="岗位需求",
            created_by=self.user,
        )
        self.version = JobRequirementDocumentVersion.objects.create(
            document=self.document,
            version=1,
            original_name="requirement.docx",
            file="recruitment/job-documents/requirement.docx",
            file_size=10,
            sha256="d" * 64,
            uploaded_by=self.user,
        )
        self.document.current_version = self.version
        self.document.save(update_fields=["current_version"])
        self.block_id = f"doc-{self.version.id}-block-1"
        FileTextExtraction.objects.create(
            source_kind=FileTextExtraction.SourceKind.JOB_DOCUMENT,
            source_id=self.version.id,
            source_sha256=self.version.sha256,
            method=FileTextExtraction.Method.DOCX,
            plain_text="需要五年 B2B 产品经验",
            blocks=[{"id": self.block_id, "text": "需要五年 B2B 产品经验", "page": None, "section": "paragraph", "bbox": None}],
            status=FileTextExtraction.Status.READY,
        )

    def test_model_output_creates_evidence_backed_draft(self):
        gateway = FakeGateway(
            {"criteria": valid_criteria(self.block_id), "unresolved_questions": ["是否要求英语能力"]}
        )

        standard = create_standard_draft(
            job=self.job,
            document_versions=[self.version],
            gateway=gateway,
            actor=self.user,
        )

        self.assertEqual(standard.status, JobStandardVersion.Status.DRAFT)
        self.assertEqual(standard.version, 1)
        self.assertEqual(standard.model_name, "example-chat")
        self.assertEqual(list(standard.source_document_versions.all()), [self.version])
        self.assertIn(self.block_id, gateway.user)
        self.assertEqual(standard.unresolved_questions, ["是否要求英语能力"])

    def test_publish_requires_exact_weight_and_supersedes_previous_version(self):
        first = JobStandardVersion.objects.create(
            job=self.job,
            version=1,
            status=JobStandardVersion.Status.PUBLISHED,
            criteria=valid_criteria(self.block_id),
            created_by=self.user,
            published_by=self.user,
        )
        draft = JobStandardVersion.objects.create(
            job=self.job,
            version=2,
            criteria={**valid_criteria(self.block_id), "dimensions": [{**valid_criteria(self.block_id)["dimensions"][0], "weight": 80}]},
            created_by=self.user,
        )
        draft.source_document_versions.add(self.version)

        with self.assertRaises(ValueError):
            publish_standard(standard=draft, actor=self.user)

        update_standard_draft(
            standard=draft,
            criteria=valid_criteria(self.block_id),
            unresolved_questions=[],
            actor=self.user,
        )
        published = publish_standard(standard=draft, actor=self.user)

        first.refresh_from_db()
        self.assertEqual(first.status, JobStandardVersion.Status.SUPERSEDED)
        self.assertEqual(published.status, JobStandardVersion.Status.PUBLISHED)
        self.assertIsNotNone(published.published_at)

    def test_rejects_sensitive_criteria_and_unknown_evidence(self):
        sensitive = valid_criteria(self.block_id)
        sensitive["dimensions"][0]["key"] = "gender"
        with self.assertRaises(ValueError):
            validate_criteria(sensitive, allowed_evidence_ids={self.block_id}, require_publishable=True)

        unknown = valid_criteria("missing-block")
        with self.assertRaises(ValueError):
            validate_criteria(unknown, allowed_evidence_ids={self.block_id}, require_publishable=True)

    def test_accepts_explicit_hard_requirements_but_rejects_sensitive_ones(self):
        criteria = valid_criteria(self.block_id)
        criteria["hard_requirements"] = [
            {"key": "degree", "text": "本科及以上", "evidence_block_ids": [self.block_id],
             "rule": {"field": "highest_degree", "operator": "gte", "value": "本科"}},
        ]
        criteria["auto_reject_on_hard_fail"] = True
        normalized = validate_criteria(
            criteria, allowed_evidence_ids={self.block_id}, require_publishable=True,
        )
        self.assertTrue(normalized["auto_reject_on_hard_fail"])
        self.assertEqual(normalized["hard_requirements"][0]["key"], "degree")

        criteria["hard_requirements"][0]["key"] = "age"
        with self.assertRaises(ValueError):
            validate_criteria(criteria, allowed_evidence_ids={self.block_id}, require_publishable=True)

        criteria["hard_requirements"][0] = {
            "key": "other_gate", "text": "年龄不超过 35 岁", "evidence_block_ids": [self.block_id],
        }
        with self.assertRaises(ValueError):
            validate_criteria(criteria, allowed_evidence_ids={self.block_id}, require_publishable=True)

        criteria = valid_criteria(self.block_id)
        criteria["auto_reject_on_hard_fail"] = "false"
        with self.assertRaisesRegex(ValueError, "确定性硬性条件核验"):
            validate_criteria(criteria, allowed_evidence_ids={self.block_id}, require_publishable=True)


class JobStandardApiTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="standard-hr")
        AccountProfile.objects.create(user=self.user, role=AccountProfile.Role.HR)
        self.account = BossAccount.objects.create(name="API standard", browser_profile="api-standard", cdp_port=54142)
        self.account.authorized_users.add(self.user)
        self.job = RecruitmentJob.objects.create(
            boss_account=self.account, external_id="api-standard-job", title="后端工程师", owner=self.user
        )
        self.document = JobRequirementDocument.objects.create(
            job=self.job, category="requirement", title="需求", created_by=self.user
        )
        self.version = JobRequirementDocumentVersion.objects.create(
            document=self.document,
            version=1,
            original_name="requirement.docx",
            file="recruitment/job-documents/requirement.docx",
            file_size=10,
            sha256="e" * 64,
            uploaded_by=self.user,
        )
        self.document.current_version = self.version
        self.document.save(update_fields=["current_version"])
        self.block_id = f"doc-{self.version.id}-block-1"
        FileTextExtraction.objects.create(
            source_kind="job_document",
            source_id=self.version.id,
            source_sha256=self.version.sha256,
            method="docx",
            plain_text="要求 Python 经验",
            blocks=[{"id": self.block_id, "text": "要求 Python 经验"}],
            status="ready",
        )
        self.standard = JobStandardVersion.objects.create(
            job=self.job,
            version=1,
            criteria=valid_criteria(self.block_id),
            created_by=self.user,
        )
        self.standard.source_document_versions.add(self.version)
        self.client.force_login(self.user)

    def test_lists_only_accessible_job_standards(self):
        response = self.client.get(f"/api/recruitment/job-standards/?job={self.job.id}")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(response.data["results"][0]["id"], self.standard.id)

        other = User.objects.create_user(username="standard-other")
        AccountProfile.objects.create(user=other, role=AccountProfile.Role.HR)
        self.client.force_login(other)
        hidden = self.client.get(f"/api/recruitment/job-standards/?job={self.job.id}")
        self.assertEqual(hidden.status_code, 404)

    def test_updates_draft_and_publishes_it(self):
        updated = self.client.patch(
            f"/api/recruitment/job-standards/{self.standard.id}/",
            {"criteria": valid_criteria(self.block_id), "unresolved_questions": []},
            format="json",
        )
        self.assertEqual(updated.status_code, 200, updated.data)

        published = self.client.post(f"/api/recruitment/job-standards/{self.standard.id}/publish/", {}, format="json")
        self.assertEqual(published.status_code, 200, published.data)
        self.assertEqual(published.data["status"], "published")

        conflict = self.client.patch(
            f"/api/recruitment/job-standards/{self.standard.id}/",
            {"criteria": valid_criteria(self.block_id)},
            format="json",
        )
        self.assertEqual(conflict.status_code, 409)

    def test_generate_is_idempotent_and_viewer_cannot_write(self):
        first = self.client.post("/api/recruitment/job-standards/generate/", {"job": self.job.id}, format="json")
        second = self.client.post("/api/recruitment/job-standards/generate/", {"job": self.job.id}, format="json")
        self.assertIn(first.status_code, {200, 201})
        self.assertEqual(second.status_code, 200)
        self.assertEqual(first.data["task_id"], second.data["task_id"])
        self.assertEqual(AiProcessingTask.objects.filter(job=self.job, kind="job_standard").count(), 1)

        viewer = User.objects.create_user(username="standard-viewer")
        AccountProfile.objects.create(user=viewer, role=AccountProfile.Role.VIEWER)
        self.account.authorized_users.add(viewer)
        self.client.force_login(viewer)
        denied = self.client.post("/api/recruitment/job-standards/generate/", {"job": self.job.id}, format="json")
        self.assertEqual(denied.status_code, 403)
