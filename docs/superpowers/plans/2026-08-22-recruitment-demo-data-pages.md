# Recruitment Demo Data and Pages Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build persistent, removable recruitment demo data with three PDF resumes and replace the four recruitment placeholder routes with functional Vue 3 pages.

**Architecture:** Django owns the demo-data lifecycle, PDF generation, filtering, stage mutation, and authenticated file responses. Vue pages consume those APIs through the existing session-authenticated client and share a small demo-data menu; all demo records carry `is_demo=True`, while demo jobs use a nullable BOSS account so no fake automation account is created.

**Tech Stack:** Python 3, Django 5.2, Django REST Framework 3.16, ReportLab, SQLite/PostgreSQL-compatible models, Vue 3 Composition API, Vue Router, Vitest, Vue Test Utils, native HTML drag-and-drop.

---

## File map

**Backend**

- Modify `backend/requirements.txt`: add ReportLab for deterministic PDF generation.
- Modify `backend/recruitment/models.py`: add demo flags, permit internal jobs, and define `Resume`.
- Create `backend/recruitment/migrations/0003_recruitment_demo_data.py`: schema migration for the model changes.
- Create `backend/recruitment/demo_data.py`: fixed fictional dataset, PDF builder, idempotent load/status/clear services.
- Modify `backend/recruitment/serializers.py`: expose related job/candidate/resume fields and constrain stage mutation.
- Modify `backend/recruitment/views.py`: filtering, partial stage updates, resume file response, and demo lifecycle API.
- Modify `backend/recruitment/urls.py`: register resumes and demo endpoint.
- Create `backend/recruitment/tests/test_demo_data.py`: model, service, PDF, rollback, and cleanup coverage.
- Create `backend/recruitment/tests/test_recruitment_pages_api.py`: list filters, stage update, permissions, and PDF response coverage.

**Frontend**

- Create `frontend/src/recruitment.js`: stage columns and formatting helpers shared by pages.
- Create `frontend/src/recruitment.test.js`: helper tests.
- Create `frontend/src/components/RecruitmentDemoMenu.vue`: low-emphasis load/status/clear menu.
- Create `frontend/src/components/RecruitmentDemoMenu.test.js`: menu lifecycle and confirmation tests.
- Create `frontend/src/components/RecruitmentDetailDrawer.vue`: reusable right-side details panel.
- Create `frontend/src/views/recruitment/RecruitmentJobsView.vue`: job list and details.
- Create `frontend/src/views/recruitment/RecruitmentJobsView.test.js`: job rendering and demo reload.
- Create `frontend/src/views/recruitment/RecruitmentCandidatesView.vue`: filters, list, and candidate details.
- Create `frontend/src/views/recruitment/RecruitmentCandidatesView.test.js`: filters and detail drawer.
- Create `frontend/src/views/recruitment/RecruitmentPipelineView.vue`: stage board and persisted drag/drop.
- Create `frontend/src/views/recruitment/RecruitmentPipelineView.test.js`: successful move and failed-move rollback.
- Create `frontend/src/views/recruitment/RecruitmentResumesView.vue`: PDF list, preview, and download.
- Create `frontend/src/views/recruitment/RecruitmentResumesView.test.js`: PDF actions and unavailable state.
- Modify `frontend/src/router.js`: replace four placeholder routes.
- Modify `frontend/src/styles.css`: scoped recruitment list, drawer, menu, board, and resume styles.

### Task 1: Add demo-safe recruitment schema

**Files:**
- Modify: `backend/recruitment/models.py`
- Create: `backend/recruitment/migrations/0003_recruitment_demo_data.py`
- Modify: `backend/recruitment/tests/test_foundation.py`

- [ ] **Step 1: Write failing model tests**

Add `Resume` to the imports in `backend/recruitment/tests/test_foundation.py`, then add:

```python
def test_demo_job_can_exist_without_boss_account(self):
    job = RecruitmentJob.objects.create(
        boss_account=None,
        external_id="demo:job:frontend",
        title="前端工程师",
        owner=self.hr,
        is_demo=True,
    )
    self.assertIsNone(job.boss_account)
    self.assertTrue(job.is_demo)

def test_pdf_resume_belongs_to_candidate_and_application(self):
    application = JobApplication.objects.create(
        candidate=self.candidate,
        job=self.job,
        source="demo",
        is_demo=True,
    )
    resume = Resume.objects.create(
        candidate=self.candidate,
        application=application,
        original_name="candidate.pdf",
        file="recruitment/resumes/candidate.pdf",
        content_type="application/pdf",
        file_size=128,
        source=Resume.Source.DEMO,
        is_demo=True,
    )
    self.assertEqual(resume.application, application)
    self.assertEqual(self.candidate.resumes.get(), resume)
```

- [ ] **Step 2: Run the tests and verify the schema is missing**

Run:

```powershell
.\.venv\Scripts\python.exe backend\manage.py test recruitment.tests.test_foundation -v 2
```

Expected: FAIL because `Resume` and `is_demo` do not exist.

- [ ] **Step 3: Add the minimal model definitions**

In `backend/recruitment/models.py`, replace the existing `RecruitmentJob.boss_account` declaration with:

```python
boss_account = models.ForeignKey(
    BossAccount,
    on_delete=models.PROTECT,
    related_name="jobs",
    null=True,
    blank=True,
)
```

Add this field immediately before `created_at` in each of `RecruitmentJob`, `Candidate`, and `JobApplication`:

```python
is_demo = models.BooleanField(default=False, db_index=True)
```

Append the complete resume model after `JobApplication`:

```python


class Resume(models.Model):
    class Source(models.TextChoices):
        BOSS = "boss", "BOSS 直聘"
        UPLOAD = "upload", "人工上传"
        DEMO = "demo", "演示数据"

    class ProcessingStatus(models.TextChoices):
        PENDING = "pending", "待处理"
        READY = "ready", "待 AI 评估"
        ERROR = "error", "文件不可用"

    candidate = models.ForeignKey(Candidate, on_delete=models.CASCADE, related_name="resumes")
    application = models.ForeignKey(
        JobApplication,
        on_delete=models.SET_NULL,
        related_name="resumes",
        null=True,
        blank=True,
    )
    original_name = models.CharField(max_length=255)
    file = models.FileField(upload_to="recruitment/resumes/%Y/%m")
    content_type = models.CharField(max_length=100, default="application/pdf")
    file_size = models.PositiveBigIntegerField(default=0)
    source = models.CharField(max_length=20, choices=Source.choices, default=Source.BOSS)
    processing_status = models.CharField(
        max_length=20,
        choices=ProcessingStatus.choices,
        default=ProcessingStatus.READY,
    )
    is_demo = models.BooleanField(default=False, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]
```

- [ ] **Step 4: Generate and inspect the migration**

Run:

```powershell
.\.venv\Scripts\python.exe backend\manage.py makemigrations recruitment --name recruitment_demo_data
.\.venv\Scripts\python.exe backend\manage.py sqlmigrate recruitment 0003
```

Expected: migration alters `RecruitmentJob.boss_account`, adds three `is_demo` fields, and creates `Resume` without dropping existing recruitment tables.

- [ ] **Step 5: Run model tests**

Run:

```powershell
.\.venv\Scripts\python.exe backend\manage.py test recruitment.tests.test_foundation -v 2
```

Expected: PASS.

- [ ] **Step 6: Commit the schema**

```powershell
git add backend/recruitment/models.py backend/recruitment/migrations/0003_recruitment_demo_data.py backend/recruitment/tests/test_foundation.py
git commit -m "feat: add recruitment demo data schema"
```

### Task 2: Build idempotent fictional data and PDF services

**Files:**
- Modify: `backend/requirements.txt`
- Create: `backend/recruitment/demo_data.py`
- Create: `backend/recruitment/tests/test_demo_data.py`

- [ ] **Step 1: Add ReportLab and install it locally**

Append to `backend/requirements.txt`:

```text
reportlab>=4.4,<5
```

Run:

```powershell
.\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt
```

Expected: ReportLab installs successfully.

- [ ] **Step 2: Write failing lifecycle and PDF tests**

Create `backend/recruitment/tests/test_demo_data.py` with tests using a temporary media directory:

```python
from pathlib import Path
from tempfile import TemporaryDirectory

from django.contrib.auth.models import User
from django.test import TestCase, override_settings

from recruitment.demo_data import clear_demo_data, demo_status, load_demo_data
from recruitment.models import Candidate, JobApplication, RecruitmentJob, Resume


class DemoDataServiceTests(TestCase):
    def setUp(self):
        self.temp_media = TemporaryDirectory()
        self.override = override_settings(MEDIA_ROOT=self.temp_media.name)
        self.override.enable()
        self.hr = User.objects.create_user(username="demo-owner")

    def tearDown(self):
        self.override.disable()
        self.temp_media.cleanup()

    def test_load_creates_exact_counts_and_real_pdfs(self):
        result = load_demo_data(self.hr)
        self.assertEqual(result, {"jobs": 3, "candidates": 10, "applications": 10, "resumes": 3})
        self.assertEqual(RecruitmentJob.objects.filter(is_demo=True).count(), 3)
        self.assertEqual(Candidate.objects.filter(is_demo=True).count(), 10)
        self.assertEqual(JobApplication.objects.filter(is_demo=True).count(), 10)
        self.assertEqual(Resume.objects.filter(is_demo=True).count(), 3)
        for resume in Resume.objects.filter(is_demo=True):
            self.assertTrue(Path(resume.file.path).read_bytes().startswith(b"%PDF"))

    def test_load_is_idempotent(self):
        load_demo_data(self.hr)
        first_files = set(Resume.objects.filter(is_demo=True).values_list("file", flat=True))
        load_demo_data(self.hr)
        self.assertEqual(demo_status()["counts"], {"jobs": 3, "candidates": 10, "applications": 10, "resumes": 3})
        self.assertEqual(set(Resume.objects.filter(is_demo=True).values_list("file", flat=True)), first_files)

    def test_clear_removes_only_demo_rows_and_files(self):
        real = Candidate.objects.create(identity_key="real:1", name="真实候选人")
        load_demo_data(self.hr)
        paths = [Path(item.file.path) for item in Resume.objects.filter(is_demo=True)]
        with self.captureOnCommitCallbacks(execute=True):
            clear_demo_data()
        self.assertTrue(Candidate.objects.filter(pk=real.pk).exists())
        self.assertFalse(Candidate.objects.filter(is_demo=True).exists())
        self.assertTrue(all(not path.exists() for path in paths))
```

- [ ] **Step 3: Run the service tests and verify they fail**

Run:

```powershell
.\.venv\Scripts\python.exe backend\manage.py test recruitment.tests.test_demo_data -v 2
```

Expected: FAIL because `recruitment.demo_data` is missing.

- [ ] **Step 4: Implement the fictional dataset and PDF builder**

Create `backend/recruitment/demo_data.py` with this fixed, fictional dataset and service implementation:

```python
from io import BytesIO

from django.core.files.base import ContentFile
from django.db import transaction
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.pdfgen import canvas

from .models import Candidate, JobApplication, RecruitmentJob, Resume

DEMO_PREFIX = "demo:2026-08-22:"

JOBS = {
    "frontend": {"title": "Vue 前端工程师", "department": "研发中心", "headcount": 2, "status": "open", "jd": "负责 Vue 3 人事产品的页面与交互开发。"},
    "product": {"title": "人事产品经理", "department": "产品中心", "headcount": 1, "status": "open", "jd": "负责招聘与考勤工作台的产品规划和交付。"},
    "implementation": {"title": "实施顾问", "department": "客户成功部", "headcount": 2, "status": "paused", "jd": "负责人事系统上线、培训与客户需求跟进。"},
}

CANDIDATES = [
    {"key": "zhou-xiaoning", "name": "周晓宁", "phone": "138****0001", "email": "zhou.xiaoning@example.com", "title": "前端开发工程师", "city": "北京", "job": "frontend", "stage": "new"},
    {"key": "lin-yuwei", "name": "林雨薇", "phone": "138****0002", "email": "lin.yuwei@example.com", "title": "高级前端工程师", "city": "上海", "job": "frontend", "stage": "to_screen"},
    {"key": "chen-mo", "name": "陈默", "phone": "138****0003", "email": "chen.mo@example.com", "title": "人事产品经理", "city": "杭州", "job": "product", "stage": "communicating"},
    {"key": "xu-wen", "name": "徐雯", "phone": "138****0004", "email": "xu.wen@example.com", "title": "SaaS 产品经理", "city": "深圳", "job": "product", "stage": "interviewing"},
    {"key": "gao-yuan", "name": "高远", "phone": "138****0005", "email": "gao.yuan@example.com", "title": "HRIS 产品经理", "city": "北京", "job": "product", "stage": "to_offer"},
    {"key": "song-yi", "name": "宋怡", "phone": "138****0006", "email": "song.yi@example.com", "title": "实施顾问", "city": "成都", "job": "implementation", "stage": "hired"},
    {"key": "han-chuan", "name": "韩川", "phone": "138****0007", "email": "han.chuan@example.com", "title": "项目实施工程师", "city": "武汉", "job": "implementation", "stage": "rejected"},
    {"key": "lu-jia", "name": "陆佳", "phone": "138****0008", "email": "lu.jia@example.com", "title": "Web 前端工程师", "city": "南京", "job": "frontend", "stage": "communicating"},
    {"key": "tang-ke", "name": "唐可", "phone": "138****0009", "email": "tang.ke@example.com", "title": "客户成功顾问", "city": "重庆", "job": "implementation", "stage": "to_screen"},
    {"key": "he-an", "name": "何安", "phone": "138****0010", "email": "he.an@example.com", "title": "产品专员", "city": "苏州", "job": "product", "stage": "new"},
]

RESUME_PROFILES = {
    "zhou-xiaoning": {"file_name": "zhou-xiaoning.pdf", "name": "周晓宁", "lines": ["应聘岗位：Vue 前端工程师", "技能：Vue 3、TypeScript、Vite", "经历：虚构科技有限公司，前端工程师，3 年", "教育：示例大学，计算机科学，本科"]},
    "xu-wen": {"file_name": "xu-wen.pdf", "name": "徐雯", "lines": ["应聘岗位：人事产品经理", "技能：产品规划、用户研究、数据分析", "经历：虚构软件有限公司，产品经理，5 年", "教育：示例大学，信息管理，本科"]},
    "song-yi": {"file_name": "song-yi.pdf", "name": "宋怡", "lines": ["应聘岗位：实施顾问", "技能：项目交付、客户培训、需求分析", "经历：虚构服务有限公司，实施顾问，4 年", "教育：示例大学，人力资源管理，本科"]},
}


def build_resume_pdf(profile: dict) -> bytes:
    pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
    buffer = BytesIO()
    page = canvas.Canvas(buffer)
    page.setTitle(profile["file_name"])
    page.setFont("STSong-Light", 18)
    page.drawString(54, 790, profile["name"])
    page.setFont("STSong-Light", 10)
    y = 755
    for line in profile["lines"]:
        page.drawString(54, y, line)
        y -= 22
    page.showPage()
    page.save()
    return buffer.getvalue()


def demo_status() -> dict:
    counts = {
        "jobs": RecruitmentJob.objects.filter(is_demo=True).count(),
        "candidates": Candidate.objects.filter(is_demo=True).count(),
        "applications": JobApplication.objects.filter(is_demo=True).count(),
        "resumes": Resume.objects.filter(is_demo=True).count(),
    }
    return {"loaded": any(counts.values()), "counts": counts}


@transaction.atomic
def load_demo_data(actor) -> dict:
    jobs = {}
    candidates = {}
    applications = {}
    created_files = []
    storage = Resume._meta.get_field("file").storage
    try:
        for key, values in JOBS.items():
            job, _ = RecruitmentJob.objects.update_or_create(
                external_id=f"{DEMO_PREFIX}job:{key}",
                is_demo=True,
                defaults={**values, "boss_account": None, "owner": actor},
            )
            jobs[key] = job

        for values in CANDIDATES:
            candidate, _ = Candidate.objects.update_or_create(
                identity_key=f"{DEMO_PREFIX}candidate:{values['key']}",
                defaults={
                    "external_id": "",
                    "name": values["name"],
                    "phone": values["phone"],
                    "email": values["email"],
                    "current_title": values["title"],
                    "current_city": values["city"],
                    "is_demo": True,
                },
            )
            application, _ = JobApplication.objects.update_or_create(
                candidate=candidate,
                job=jobs[values["job"]],
                defaults={"source": "demo", "stage": values["stage"], "owner": actor, "is_demo": True},
            )
            candidates[values["key"]] = candidate
            applications[values["key"]] = application

        for key, profile in RESUME_PROFILES.items():
            if Resume.objects.filter(candidate=candidates[key], is_demo=True).exists():
                continue
            resume = Resume(
                candidate=candidates[key],
                application=applications[key],
                original_name=profile["file_name"],
                content_type="application/pdf",
                source=Resume.Source.DEMO,
                processing_status=Resume.ProcessingStatus.READY,
                is_demo=True,
            )
            content = build_resume_pdf(profile)
            resume.file_size = len(content)
            resume.file.save(profile["file_name"], ContentFile(content), save=False)
            created_files.append(resume.file.name)
            resume.save()
    except Exception:
        for name in created_files:
            storage.delete(name)
        raise
    return demo_status()["counts"]


@transaction.atomic
def clear_demo_data() -> dict:
    resumes = list(Resume.objects.filter(is_demo=True))
    file_names = [resume.file.name for resume in resumes if resume.file]
    storage = Resume._meta.get_field("file").storage
    Resume.objects.filter(is_demo=True).delete()
    JobApplication.objects.filter(is_demo=True).delete()
    Candidate.objects.filter(is_demo=True).delete()
    RecruitmentJob.objects.filter(is_demo=True).delete()
    transaction.on_commit(lambda: [storage.delete(name) for name in file_names])
    return {"loaded": False, "counts": {"jobs": 0, "candidates": 0, "applications": 0, "resumes": 0}}
```

- [ ] **Step 5: Run lifecycle tests**

Run:

```powershell
.\.venv\Scripts\python.exe backend\manage.py test recruitment.tests.test_demo_data -v 2
```

Expected: PASS with exact 3/10/10/3 counts, idempotency, valid `%PDF` headers, and selective cleanup.

- [ ] **Step 6: Commit the demo service**

```powershell
git add backend/requirements.txt backend/recruitment/demo_data.py backend/recruitment/tests/test_demo_data.py
git commit -m "feat: generate isolated recruitment demo data"
```

### Task 3: Expose recruitment lists, stage changes, files, and demo lifecycle

**Files:**
- Modify: `backend/recruitment/serializers.py`
- Modify: `backend/recruitment/views.py`
- Modify: `backend/recruitment/urls.py`
- Create: `backend/recruitment/tests/test_recruitment_pages_api.py`

- [ ] **Step 1: Write failing API tests**

Create authenticated HR and viewer users. Load demo data for the HR, then cover these exact requests:

```python
jobs = self.client.get("/api/recruitment/jobs/?is_demo=true")
self.assertEqual(jobs.status_code, 200)
self.assertEqual(jobs.data["count"], 3)
self.assertIn("candidate_count", jobs.data["results"][0])

candidates = self.client.get("/api/recruitment/candidates/?search=周&stage=to_screen")
self.assertEqual(candidates.status_code, 200)
self.assertIn("applications", candidates.data["results"][0])

application = JobApplication.objects.filter(is_demo=True).first()
changed = self.client.patch(
    f"/api/recruitment/applications/{application.pk}/",
    {"stage": JobApplication.Stage.INTERVIEWING},
    format="json",
)
self.assertEqual(changed.status_code, 200)
self.assertEqual(changed.data["stage"], "interviewing")

resume = Resume.objects.filter(is_demo=True).first()
inline = self.client.get(f"/api/recruitment/resumes/{resume.pk}/file/")
self.assertEqual(inline.status_code, 200)
self.assertEqual(inline["Content-Type"], "application/pdf")
self.assertTrue(inline["Content-Disposition"].startswith("inline"))

resume.file.storage.delete(resume.file.name)
missing = self.client.get(f"/api/recruitment/resumes/{resume.pk}/")
self.assertFalse(missing.data["file_available"])

status_response = self.client.get("/api/recruitment/demo-data/")
self.assertEqual(status_response.data["counts"]["candidates"], 10)
```

Also assert that a viewer receives `403` for `POST`/`DELETE /api/recruitment/demo-data/` and for application `PATCH`, and that an anonymous user receives `403` for resume file access under DRF session authentication.

- [ ] **Step 2: Run the API tests and verify they fail**

Run:

```powershell
.\.venv\Scripts\python.exe backend\manage.py test recruitment.tests.test_recruitment_pages_api -v 2
```

Expected: FAIL because resume and demo endpoints do not exist and application updates return 405.

- [ ] **Step 3: Expand serializers with stable read shapes**

Implement:

```python
class JobApplicationSummarySerializer(serializers.ModelSerializer):
    job_title = serializers.CharField(source="job.title", read_only=True)
    owner_name = serializers.CharField(source="owner.username", read_only=True, allow_null=True)
    stage_label = serializers.CharField(source="get_stage_display", read_only=True)

    class Meta:
        model = JobApplication
        fields = ["id", "job", "job_title", "stage", "stage_label", "owner_name", "updated_at"]


class CandidateSummarySerializer(serializers.ModelSerializer):
    resume_count = serializers.SerializerMethodField()

    def get_resume_count(self, obj):
        return obj.resumes.count()

    class Meta:
        model = Candidate
        fields = ["id", "name", "current_title", "current_city", "resume_count"]


class RecruitmentJobSerializer(serializers.ModelSerializer):
    owner_name = serializers.CharField(source="owner.username", read_only=True)
    account_name = serializers.CharField(source="boss_account.name", read_only=True, allow_null=True)
    candidate_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = RecruitmentJob
        fields = [
            "id", "boss_account", "account_name", "external_id", "title", "department",
            "jd", "owner", "owner_name", "headcount", "status", "candidate_count",
            "is_demo", "created_at", "updated_at",
        ]


class CandidateSerializer(serializers.ModelSerializer):
    applications = JobApplicationSummarySerializer(many=True, read_only=True)
    resume_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = Candidate
        fields = [
            "id", "identity_key", "external_id", "name", "phone", "email",
            "current_title", "current_city", "applications", "resume_count",
            "is_demo", "created_at", "updated_at",
        ]


class JobApplicationSerializer(serializers.ModelSerializer):
    candidate = CandidateSummarySerializer(read_only=True)
    job_title = serializers.CharField(source="job.title", read_only=True)
    owner_name = serializers.CharField(source="owner.username", read_only=True, allow_null=True)
    stage_label = serializers.CharField(source="get_stage_display", read_only=True)

    class Meta:
        model = JobApplication
        fields = [
            "id", "candidate", "job", "job_title", "source", "stage", "stage_label",
            "owner", "owner_name", "priority", "last_interaction_at", "is_demo",
            "created_at", "updated_at",
        ]
        read_only_fields = [
            "id", "candidate", "job", "job_title", "source", "stage_label", "owner",
            "owner_name", "priority", "last_interaction_at", "is_demo", "created_at", "updated_at",
        ]


class ResumeSerializer(serializers.ModelSerializer):
    candidate_name = serializers.CharField(source="candidate.name", read_only=True)
    job_title = serializers.CharField(source="application.job.title", read_only=True, allow_null=True)
    status_label = serializers.CharField(source="get_processing_status_display", read_only=True)
    source_label = serializers.CharField(source="get_source_display", read_only=True)
    file_available = serializers.SerializerMethodField()
    preview_url = serializers.SerializerMethodField()
    download_url = serializers.SerializerMethodField()

    def get_file_available(self, obj):
        return bool(obj.file and obj.file.storage.exists(obj.file.name))

    def get_preview_url(self, obj):
        return f"/api/recruitment/resumes/{obj.pk}/file/"

    def get_download_url(self, obj):
        return f"/api/recruitment/resumes/{obj.pk}/file/?download=1"

    class Meta:
        model = Resume
        fields = [
            "id", "candidate", "candidate_name", "application", "job_title", "original_name",
            "content_type", "file_size", "source", "source_label", "processing_status",
            "status_label", "file_available", "preview_url", "download_url", "is_demo",
            "created_at", "updated_at",
        ]
```

- [ ] **Step 4: Implement filters and authenticated file responses**

Add `Q` to the `django.db.models` import and replace the three existing workspace viewsets with:

```python
class RecruitmentJobViewSet(viewsets.ModelViewSet):
    queryset = RecruitmentJob.objects.select_related("boss_account", "owner").annotate(
        candidate_count=Count("applications", distinct=True)
    ).order_by("-updated_at")
    serializer_class = RecruitmentJobSerializer
    permission_classes = [RecruitmentWritePermission]

    def get_queryset(self):
        queryset = super().get_queryset()
        if self.request.query_params.get("is_demo") == "true":
            queryset = queryset.filter(is_demo=True)
        return queryset


class CandidateViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Candidate.objects.prefetch_related(
        "applications__job", "applications__owner", "resumes"
    ).annotate(resume_count=Count("resumes", distinct=True)).order_by("-updated_at")
    serializer_class = CandidateSerializer
    permission_classes = [RecruitmentWritePermission]

    def get_queryset(self):
        queryset = super().get_queryset()
        search = self.request.query_params.get("search", "").strip()
        if search:
            queryset = queryset.filter(
                Q(name__icontains=search)
                | Q(current_title__icontains=search)
                | Q(current_city__icontains=search)
            )
        if self.request.query_params.get("job"):
            queryset = queryset.filter(applications__job_id=self.request.query_params["job"])
        if self.request.query_params.get("stage"):
            queryset = queryset.filter(applications__stage=self.request.query_params["stage"])
        if self.request.query_params.get("is_demo") == "true":
            queryset = queryset.filter(is_demo=True)
        return queryset.distinct()


class JobApplicationViewSet(viewsets.ModelViewSet):
    queryset = JobApplication.objects.select_related(
        "candidate", "job", "owner"
    ).prefetch_related("candidate__resumes").order_by("-updated_at")
    serializer_class = JobApplicationSerializer
    permission_classes = [RecruitmentWritePermission]
    http_method_names = ["get", "patch", "head", "options"]

    def get_queryset(self):
        queryset = super().get_queryset()
        if self.request.query_params.get("job"):
            queryset = queryset.filter(job_id=self.request.query_params["job"])
        if self.request.query_params.get("stage"):
            queryset = queryset.filter(stage=self.request.query_params["stage"])
        if self.request.query_params.get("is_demo") == "true":
            queryset = queryset.filter(is_demo=True)
        return queryset
```

Then add the authenticated resume and demo lifecycle views:

```python
class ResumeViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Resume.objects.select_related("candidate", "application__job").all()
    serializer_class = ResumeSerializer
    permission_classes = [RecruitmentWritePermission]

    @action(detail=True, methods=["get"])
    def file(self, request, pk=None):
        resume = self.get_object()
        if not resume.file or not resume.file.storage.exists(resume.file.name):
            return Response({"detail": "简历文件不可用"}, status=status.HTTP_404_NOT_FOUND)
        response = FileResponse(resume.file.open("rb"), content_type="application/pdf")
        disposition = "attachment" if request.query_params.get("download") == "1" else "inline"
        response["Content-Disposition"] = content_disposition_header(
            as_attachment=disposition == "attachment",
            filename=resume.original_name,
        )
        return response


@api_view(["GET", "POST", "DELETE"])
@permission_classes([RecruitmentWritePermission])
def demo_data_view(request):
    if request.method == "GET":
        return Response(demo_status())
    if request.method == "POST":
        load_demo_data(request.user)
        return Response(demo_status(), status=status.HTTP_201_CREATED)
    return Response(clear_demo_data())
```

Import `FileResponse`, `content_disposition_header`, `Resume`, `ResumeSerializer`, and the three demo service functions.

- [ ] **Step 5: Register URLs and run API tests**

Register `resumes` on the DRF router and add:

```python
path("demo-data/", views.demo_data_view),
```

Run:

```powershell
.\.venv\Scripts\python.exe backend\manage.py test recruitment.tests.test_recruitment_pages_api -v 2
```

Expected: PASS.

- [ ] **Step 6: Run the full backend suite and commit**

Run:

```powershell
.\.venv\Scripts\python.exe backend\manage.py test -v 1
```

Expected: all existing attendance, accounts, recruitment, RPA, and new demo tests PASS.

```powershell
git add backend/recruitment/serializers.py backend/recruitment/views.py backend/recruitment/urls.py backend/recruitment/tests/test_recruitment_pages_api.py
git commit -m "feat: expose recruitment workspace APIs"
```

### Task 4: Add shared frontend recruitment primitives

**Files:**
- Create: `frontend/src/recruitment.js`
- Create: `frontend/src/recruitment.test.js`
- Create: `frontend/src/components/RecruitmentDemoMenu.vue`
- Create: `frontend/src/components/RecruitmentDemoMenu.test.js`
- Create: `frontend/src/components/RecruitmentDetailDrawer.vue`
- Modify: `frontend/src/styles.css`

- [ ] **Step 1: Write failing helper and menu tests**

Test that the stage list is exactly:

```javascript
expect(stageColumns.map((item) => item.key)).toEqual([
  'new', 'to_screen', 'communicating', 'interviewing', 'to_offer', 'hired', 'rejected',
])
expect(formatFileSize(1536)).toBe('1.5 KB')
```

In the menu test, mock `api()` so GET returns `{ loaded: true, counts: { jobs: 3, candidates: 10, applications: 10, resumes: 3 } }`. Assert that opening the text trigger shows the four counts, POST emits `changed`, and DELETE is not called when `window.confirm` returns false.

- [ ] **Step 2: Run tests and verify missing modules**

Run:

```powershell
Set-Location frontend
npm test -- src/recruitment.test.js src/components/RecruitmentDemoMenu.test.js
```

Expected: FAIL because the files do not exist.

- [ ] **Step 3: Implement shared helpers**

Create `frontend/src/recruitment.js`:

```javascript
export const stageColumns = [
  { key: 'new', label: '新候选人' },
  { key: 'to_screen', label: '初筛' },
  { key: 'communicating', label: '沟通' },
  { key: 'interviewing', label: '面试' },
  { key: 'to_offer', label: 'Offer' },
  { key: 'hired', label: '已入职' },
  { key: 'rejected', label: '淘汰' },
]

export function formatFileSize(bytes) {
  if (!bytes) return '0 B'
  if (bytes < 1024) return `${bytes} B`
  return `${(bytes / 1024).toFixed(1)} KB`
}

export function formatRecruitmentDate(value) {
  return value ? new Intl.DateTimeFormat('zh-CN', { dateStyle: 'medium' }).format(new Date(value)) : '—'
}
```

- [ ] **Step 4: Implement the menu and drawer**

`RecruitmentDemoMenu.vue` must use `api('recruitment/demo-data/')` on mount, POST for loading, and DELETE only after `window.confirm('只会清除演示数据，确定继续吗？')`. Keep one visible text button labelled “演示数据”; render load/clear actions only inside an absolutely positioned popover and emit `changed` after successful mutation.

`RecruitmentDetailDrawer.vue` must render a fixed backdrop and right panel, accept a `title` prop, emit `close` from the close button/backdrop, and expose default and footer slots.

- [ ] **Step 5: Add focused shared styles**

Append classes prefixed `recruitment-` for the toolbar, demo popover, data shell, drawer, filters, status chips, and error strip. Use existing CSS variables `--paper`, `--line`, `--ink`, `--muted`, and `--teal`; do not change sidebar or top-navigation rules.

- [ ] **Step 6: Run shared frontend tests and commit**

Run:

```powershell
npm test -- src/recruitment.test.js src/components/RecruitmentDemoMenu.test.js
```

Expected: PASS.

```powershell
Set-Location ..
git add frontend/src/recruitment.js frontend/src/recruitment.test.js frontend/src/components/RecruitmentDemoMenu.vue frontend/src/components/RecruitmentDemoMenu.test.js frontend/src/components/RecruitmentDetailDrawer.vue frontend/src/styles.css
git commit -m "feat: add recruitment demo UI primitives"
```

### Task 5: Implement jobs and candidates pages

**Files:**
- Create: `frontend/src/views/recruitment/RecruitmentJobsView.vue`
- Create: `frontend/src/views/recruitment/RecruitmentJobsView.test.js`
- Create: `frontend/src/views/recruitment/RecruitmentCandidatesView.vue`
- Create: `frontend/src/views/recruitment/RecruitmentCandidatesView.test.js`
- Modify: `frontend/src/router.js`

- [ ] **Step 1: Write failing page tests**

Mock jobs with `title`, `department`, `headcount`, `owner_name`, `candidate_count`, and `status`. Assert all three titles render, clicking a row opens its JD, and a `changed` event from `RecruitmentDemoMenu` triggers another GET.

Mock candidates with nested `applications` and `resume_count`. Assert filtering input hides non-matching names, selecting a stage passes `?stage=...` on reload, and clicking a row opens the drawer with phone, email, job, owner, and resume state.

- [ ] **Step 2: Run page tests and verify components are missing**

Run:

```powershell
Set-Location frontend
npm test -- src/views/recruitment/RecruitmentJobsView.test.js src/views/recruitment/RecruitmentCandidatesView.test.js
```

Expected: FAIL because both views are missing.

- [ ] **Step 3: Implement the jobs page**

Use this data flow in `RecruitmentJobsView.vue`:

```javascript
const jobs = ref([])
const selected = ref(null)
const loading = ref(true)
const error = ref('')

async function loadJobs() {
  loading.value = true
  try {
    jobs.value = listItems(await api('recruitment/jobs/'))
  } catch (err) {
    error.value = err.message
  } finally {
    loading.value = false
  }
}
```

Render the standard compact page hero with `RecruitmentDemoMenu @changed="loadJobs"`, then a single table with the approved columns. Make each row keyboard accessible (`tabindex="0"`, Enter opens details). Use `RecruitmentDetailDrawer` for JD, BOSS account/source, timestamps, and status.

- [ ] **Step 4: Implement the candidates page**

Keep local `search`, `job`, and `stage` refs. Fetch jobs for the job select and fetch candidates with `URLSearchParams`. The table columns are candidate, current title/city, target job, stage, owner, and resume state. Use `RecruitmentDetailDrawer` for full fictional contact details and every application.

Do not render an upload button or AI score control; resume state is either “1 份简历” or “暂无简历”.

- [ ] **Step 5: Replace the first two placeholder routes**

In `frontend/src/router.js`:

```javascript
{ path: 'recruitment/jobs', name: 'recruitment-jobs', component: () => import('@/views/recruitment/RecruitmentJobsView.vue'), meta: { module: 'recruitment', title: '职位管理' } },
{ path: 'recruitment/candidates', name: 'recruitment-candidates', component: () => import('@/views/recruitment/RecruitmentCandidatesView.vue'), meta: { module: 'recruitment', title: '候选人' } },
```

- [ ] **Step 6: Run page tests and commit**

Run:

```powershell
npm test -- src/views/recruitment/RecruitmentJobsView.test.js src/views/recruitment/RecruitmentCandidatesView.test.js
```

Expected: PASS.

```powershell
Set-Location ..
git add frontend/src/views/recruitment/RecruitmentJobsView.vue frontend/src/views/recruitment/RecruitmentJobsView.test.js frontend/src/views/recruitment/RecruitmentCandidatesView.vue frontend/src/views/recruitment/RecruitmentCandidatesView.test.js frontend/src/router.js
git commit -m "feat: add recruitment jobs and candidates pages"
```

### Task 6: Implement persisted recruitment pipeline

**Files:**
- Create: `frontend/src/views/recruitment/RecruitmentPipelineView.vue`
- Create: `frontend/src/views/recruitment/RecruitmentPipelineView.test.js`
- Modify: `frontend/src/router.js`
- Modify: `frontend/src/styles.css`

- [ ] **Step 1: Write failing pipeline tests**

Mock applications across at least three stages. Trigger `dragstart` on one card and `drop` on the `interviewing` column. Assert:

```javascript
expect(apiMock).toHaveBeenCalledWith('recruitment/applications/11/', {
  method: 'PATCH',
  body: JSON.stringify({ stage: 'interviewing' }),
})
expect(wrapper.get('[data-stage="interviewing"]').text()).toContain('周晓宁')
```

In a second test reject the PATCH promise and assert the card returns to its original column and an error strip is visible.

- [ ] **Step 2: Run the test and verify the page is missing**

Run:

```powershell
Set-Location frontend
npm test -- src/views/recruitment/RecruitmentPipelineView.test.js
```

Expected: FAIL because the view is missing.

- [ ] **Step 3: Implement optimistic native drag/drop**

Use `stageColumns` and an `applications` ref. Store the dragged application ID on drag start. On drop, snapshot the previous stage, update locally, PATCH only `{ stage }`, and restore the snapshot in `catch`.

Render the compact page hero with `RecruitmentDemoMenu @changed="loadApplications"`, followed by seven horizontally scrollable columns. Each candidate card contains only name, target job, city/current title, and resume indicator. Clicking a card opens `RecruitmentDetailDrawer`; dragging must not trigger the drawer.

- [ ] **Step 4: Replace the pipeline route and add styles**

Replace the placeholder import with `RecruitmentPipelineView.vue`. Add `recruitment-board`, `recruitment-column`, and `recruitment-candidate-card` styles. The board may scroll horizontally on desktop but must not alter the existing left or top navigation.

- [ ] **Step 5: Run the pipeline test and commit**

Run:

```powershell
npm test -- src/views/recruitment/RecruitmentPipelineView.test.js
```

Expected: PASS for both persisted move and rollback.

```powershell
Set-Location ..
git add frontend/src/views/recruitment/RecruitmentPipelineView.vue frontend/src/views/recruitment/RecruitmentPipelineView.test.js frontend/src/router.js frontend/src/styles.css
git commit -m "feat: add recruitment pipeline board"
```

### Task 7: Implement the PDF resume center

**Files:**
- Create: `frontend/src/views/recruitment/RecruitmentResumesView.vue`
- Create: `frontend/src/views/recruitment/RecruitmentResumesView.test.js`
- Modify: `frontend/src/router.js`
- Modify: `frontend/src/styles.css`

- [ ] **Step 1: Write failing resume tests**

Mock three resume rows. Assert candidate, job, `PDF`, formatted file size, source label, and “待 AI 评估” render. Clicking preview must set the selected resume and render an iframe whose `src` is `preview_url`; clicking download must render or invoke an anchor with `download_url`. A row with `file_available: false` must show “文件不可用” and no preview action.

- [ ] **Step 2: Run the test and verify the page is missing**

Run:

```powershell
Set-Location frontend
npm test -- src/views/recruitment/RecruitmentResumesView.test.js
```

Expected: FAIL because the view is missing.

- [ ] **Step 3: Implement the resume center**

Fetch `recruitment/resumes/`, render `RecruitmentDemoMenu @changed="loadResumes"` in the compact page hero, use `formatFileSize` and `formatRecruitmentDate`, and render a restrained table. Open inline PDF preview in `RecruitmentDetailDrawer` using:

```html
<iframe
  v-if="selected?.file_available"
  class="recruitment-pdf-preview"
  :src="selected.preview_url"
  :title="`${selected.candidate_name}的简历`"
></iframe>
```

Use a normal `<a v-if="resume.file_available" :href="resume.download_url">下载</a>` so the browser performs an authenticated GET. Do not use JavaScript blob conversion or add image/DOC controls.

- [ ] **Step 4: Replace the resume route and add preview styles**

Replace the placeholder route import with `RecruitmentResumesView.vue`. Size the iframe to fill the drawer below the metadata and provide an unavailable-file block for error rows.

- [ ] **Step 5: Run the resume test and commit**

Run:

```powershell
npm test -- src/views/recruitment/RecruitmentResumesView.test.js
```

Expected: PASS.

```powershell
Set-Location ..
git add frontend/src/views/recruitment/RecruitmentResumesView.vue frontend/src/views/recruitment/RecruitmentResumesView.test.js frontend/src/router.js frontend/src/styles.css
git commit -m "feat: add PDF resume center"
```

### Task 8: Verify the complete demo in production build

**Files:**
- Modify: `README.md`
- Verify: all backend and frontend files from Tasks 1–7

- [ ] **Step 1: Document the demo lifecycle**

Add a short README section stating that “演示数据” creates 3 fictional jobs, 10 fictional candidates, 10 applications, and 3 generated PDFs; it does not call BOSS CLI; and “清除演示数据” removes only rows marked as demo.

- [ ] **Step 2: Run all backend tests**

Run:

```powershell
.\.venv\Scripts\python.exe backend\manage.py test -v 1
```

Expected: all tests PASS with no migration warning.

- [ ] **Step 3: Run migration consistency check**

Run:

```powershell
.\.venv\Scripts\python.exe backend\manage.py makemigrations --check --dry-run
```

Expected: `No changes detected`.

- [ ] **Step 4: Run all frontend tests and build**

Run:

```powershell
Set-Location frontend
npm test
npm run build
```

Expected: all Vitest tests PASS and Vite writes the production bundle to `backend/frontend_dist`.

- [ ] **Step 5: Apply migrations and load demo data through the application**

Run:

```powershell
Set-Location ..
.\.venv\Scripts\python.exe backend\manage.py migrate
```

Start the existing local launcher, log in, and use the “演示数据” menu to load the dataset. Do not insert records with a shell command because the UI/API lifecycle is part of acceptance.

- [ ] **Step 6: Perform the manual acceptance path**

Verify all of the following:

1. Job management shows exactly three demo jobs and correct candidate counts.
2. Candidate filters and detail drawer work for ten candidates.
3. A pipeline card persists after moving and refreshing.
4. Three PDFs render inline and download successfully.
5. Loading again leaves counts at 3/10/10/3.
6. Clearing after confirmation restores empty states.
7. Automation accounts and RPA task history are unchanged.

- [ ] **Step 7: Commit documentation and built frontend**

```powershell
git add README.md
git commit -m "docs: explain recruitment demo workspace"
```

- [ ] **Step 8: Final repository check**

Run:

```powershell
git status --short
git log -8 --oneline
```

Expected: clean working tree and one focused commit for each completed task.
