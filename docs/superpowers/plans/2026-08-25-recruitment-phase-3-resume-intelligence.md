# Recruitment Phase 3 Resume Intelligence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build local Word/PDF/PNG extraction, OpenAI-compatible structuring, HR-confirmed job standards, and evidence-backed resume scoring without generating scores before a standard is published.

**Architecture:** Local adapters turn files into positioned text blocks; a single model gateway turns those blocks into validated JSON. Versioned Django models preserve job standards, structured resumes, assessments, and task history, while a database-backed AI worker performs idempotent background work. Vue adds a compact job-standard workspace and structured/assessment tabs to the existing resume center.

**Tech Stack:** Django 5.2, DRF 3.16, SQLite/PostgreSQL, Python `urllib`, `python-docx`, `pypdf`, `pypdfium2`, `rapidocr`, Vue 3.5, Pinia 3, Vitest 3, Vite 7.

---

## File map

### Backend files to create

- `backend/accounts/services/model_gateway.py`: decrypt the current user's key, call OpenAI-compatible chat completions, validate JSON, and classify provider failures.
- `backend/accounts/tests.py`: gateway request, masking, timeout, auth, rate-limit, and malformed-output tests.
- `backend/recruitment/services/file_extraction.py`: DOCX, legacy DOC conversion, PDF text, scanned-PDF fallback, and PNG OCR adapters.
- `backend/recruitment/services/ai_tasks.py`: enqueue, lease, execute, retry, and resume idempotent AI tasks.
- `backend/recruitment/services/job_standards.py`: create/edit/publish immutable job-standard versions and validate weights.
- `backend/recruitment/services/resume_intelligence.py`: validate structured resumes, create assessments, and enforce evidence/sensitive-field rules.
- `backend/recruitment/management/commands/run_ai_worker.py`: process database AI tasks in the local background worker.
- `backend/recruitment/tests/test_file_extraction.py`: local extraction and OCR fallback tests.
- `backend/recruitment/tests/test_ai_tasks.py`: task lifecycle, idempotency, recovery, and model-configuration tests.
- `backend/recruitment/tests/test_job_standards_api.py`: draft, edit, publish, permissions, and version tests.
- `backend/recruitment/tests/test_resume_intelligence_api.py`: structure, score, evidence, batch, and retry tests.
- `backend/recruitment/migrations/0021_resume_intelligence.py`: third-phase tables and constraints.
- `frontend/src/components/JobStandardDrawer.vue`: evidence-aware criteria editor.
- `frontend/src/components/ResumeIntelligencePanel.vue`: original, structured, assessment, and history tabs.
- `frontend/src/components/JobStandardDrawer.test.js`: standard-editor component tests.
- `frontend/src/components/ResumeIntelligencePanel.test.js`: resume-intelligence component tests.

### Existing files to modify

- `backend/requirements.txt`: add local document/PDF/OCR packages.
- `backend/accounts/urls.py`, `backend/accounts/views.py`: add model connection test.
- `backend/recruitment/models.py`: add extraction, AI task, standard, structured resume, and assessment models.
- `backend/recruitment/serializers.py`, `backend/recruitment/views.py`, `backend/recruitment/urls.py`: expose scoped third-phase APIs.
- `backend/recruitment/services/job_documents.py`, `backend/recruitment/services/resumes.py`: enqueue parsing after transaction commit.
- `backend/recruitment/services/dashboard.py`: add third-phase aggregate counts.
- `frontend/src/stores/modelCredential.js`, `frontend/src/components/RecruitmentCopilotDrawer.vue`: test model connection and show state.
- `frontend/src/views/recruitment/RecruitmentResumesView.vue`: replace the placeholder with real standard/parse/score UI.
- `frontend/src/views/recruitment/RecruitmentResumesView.test.js`: page workflow and four-state tests.
- `frontend/src/views/recruitment/RecruitmentDashboardView.vue`, `frontend/src/views/recruitment/RecruitmentDashboardView.test.js`: aggregate cards and filtered links.
- `frontend/src/style.css`: scoped third-phase layout, progress, drawer, and evidence styles.
- `scripts/start-local.ps1`, `scripts/test-startup.ps1`: start and verify exactly one AI worker.
- `docs/autodev-api.md`, `docs/autodev-design.md`, `README.md`: document endpoints, data model, dependencies, worker, and privacy boundary.

## Task 1: OpenAI-compatible model gateway

**Files:**
- Create: `backend/accounts/services/__init__.py`
- Create: `backend/accounts/services/model_gateway.py`
- Modify: `backend/accounts/views.py`
- Modify: `backend/accounts/urls.py`
- Modify: `backend/accounts/tests.py`

- [x] **Step 1: Write failing gateway and connection API tests**

Create tests that patch `urllib.request.urlopen`, assert a POST to `<api_url>/chat/completions`, assert the decrypted key is sent only in the Authorization header, and return:

```python
{
    "choices": [{"message": {"content": '{"ok": true}'}}],
    "usage": {"prompt_tokens": 10, "completion_tokens": 4},
}
```

Add cases for HTTP 401 -> `model_auth_failed`, HTTP 429 -> `model_rate_limited`, timeout -> `model_timeout`, invalid JSON -> `model_invalid_response`, and `POST /api/account/model-credential/test/` returning `{status, model, latency_ms}` without an API key.

- [x] **Step 2: Run tests and verify failure**

Run: `..\.venv\Scripts\python.exe manage.py test accounts.tests -v 2` from `backend`.

Expected: FAIL because `accounts.services.model_gateway` and the connection endpoint do not exist.

- [x] **Step 3: Implement the gateway and endpoint**

Implement these public types and signatures:

```python
class ModelGatewayError(RuntimeError):
    def __init__(self, code: str, message: str, *, retryable: bool = False): ...

@dataclass(frozen=True)
class ModelResult:
    data: dict
    prompt_tokens: int
    completion_tokens: int
    latency_ms: int

class OpenAICompatibleGateway:
    def __init__(self, credential: UserModelCredential, *, timeout: int = 60): ...
    def complete_json(self, *, system: str, user: str) -> ModelResult: ...
    def test_connection(self) -> ModelResult: ...
```

Normalize the URL with `rstrip('/')`, call `/chat/completions`, use `temperature: 0`, strip optional Markdown JSON fences, and parse one JSON object. Read the secret with `decrypt_secret`; never place it in exceptions or response data. Add `POST model-credential/test/` with `IsAuthenticated` and the current user's credential only.

- [x] **Step 4: Run tests and verify pass**

Run: `..\.venv\Scripts\python.exe manage.py test accounts -v 2` from `backend`.

Expected: all account tests PASS.

- [x] **Step 5: Commit**

```powershell
git add backend/accounts
git commit -m "feat: add compatible model gateway"
```

## Task 2: Versioned intelligence models

**Files:**
- Modify: `backend/recruitment/models.py`
- Create: `backend/recruitment/migrations/0021_resume_intelligence.py`
- Create: `backend/recruitment/tests/test_resume_intelligence_models.py`

- [x] **Step 1: Write failing model tests**

Cover unique versions, immutable published standards, one current published standard per job, unique task idempotency keys, nullable task targets, and an assessment that binds one `JobStandardVersion` to one `StructuredResumeVersion`.

- [x] **Step 2: Run tests and verify failure**

Run: `..\.venv\Scripts\python.exe manage.py test recruitment.tests.test_resume_intelligence_models -v 2`.

Expected: FAIL because the models do not exist.

- [x] **Step 3: Add the models and migration**

Add these models with timestamps and explicit choices:

```python
class FileTextExtraction(models.Model):
    source_kind = models.CharField(max_length=24, choices=[("job_document", "岗位文档"), ("resume", "简历")])
    source_id = models.PositiveBigIntegerField()
    source_sha256 = models.CharField(max_length=64)
    method = models.CharField(max_length=24, choices=[("docx", "DOCX"), ("doc_convert", "DOC 转换"), ("pdf_text", "PDF 文字"), ("pdf_ocr", "PDF OCR"), ("image_ocr", "图片 OCR")])
    plain_text = models.TextField(blank=True)
    blocks = models.JSONField(default=list)
    status = models.CharField(max_length=20, choices=[("pending", "待处理"), ("ready", "已完成"), ("failed", "失败")], default="pending")
    error_code = models.CharField(max_length=80, blank=True)
    error_message = models.CharField(max_length=500, blank=True)
```

Unique constraint: `(source_kind, source_id, source_sha256)`.

```python
class JobStandardVersion(models.Model):
    job = models.ForeignKey(RecruitmentJob, on_delete=models.PROTECT, related_name="standard_versions")
    version = models.PositiveIntegerField()
    status = models.CharField(max_length=16, choices=[("draft", "草稿"), ("published", "已启用"), ("superseded", "历史版本")], default="draft")
    source_document_versions = models.ManyToManyField(JobRequirementDocumentVersion, related_name="job_standard_versions")
    criteria = models.JSONField(default=dict)
    unresolved_questions = models.JSONField(default=list)
    model_name = models.CharField(max_length=120, blank=True)
    prompt_version = models.CharField(max_length=40, default="job-standard-v1")
    created_by = models.ForeignKey(User, on_delete=models.PROTECT, related_name="created_job_standards")
    published_by = models.ForeignKey(User, on_delete=models.PROTECT, null=True, blank=True, related_name="published_job_standards")
    published_at = models.DateTimeField(null=True, blank=True)
```

Unique constraint: `(job, version)`; conditional unique constraint: one `published` row per job.

```python
class StructuredResumeVersion(models.Model):
    resume = models.ForeignKey(Resume, on_delete=models.PROTECT, related_name="structured_versions")
    version = models.PositiveIntegerField()
    extraction = models.ForeignKey(FileTextExtraction, on_delete=models.PROTECT, related_name="structured_resumes")
    data = models.JSONField(default=dict)
    evidence = models.JSONField(default=list)
    warnings = models.JSONField(default=list)
    model_name = models.CharField(max_length=120)
    prompt_version = models.CharField(max_length=40, default="resume-structure-v1")
```

Unique constraint: `(resume, version)`.

```python
class ResumeAssessment(models.Model):
    structured_resume = models.ForeignKey(StructuredResumeVersion, on_delete=models.PROTECT, related_name="assessments")
    standard = models.ForeignKey(JobStandardVersion, on_delete=models.PROTECT, related_name="assessments")
    total_score = models.DecimalField(max_digits=5, decimal_places=2)
    dimension_scores = models.JSONField(default=list)
    evidence = models.JSONField(default=list)
    gaps = models.JSONField(default=list)
    verification_questions = models.JSONField(default=list)
    confidence = models.DecimalField(max_digits=4, decimal_places=3)
    recommendation = models.CharField(max_length=32, choices=[("advance", "建议进一步沟通"), ("review", "建议人工复核"), ("hold", "暂不建议推进")])
    model_name = models.CharField(max_length=120)
    prompt_version = models.CharField(max_length=40, default="resume-score-v1")
```

Unique constraint: `(structured_resume, standard)`.

```python
class AiProcessingTask(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    kind = models.CharField(max_length=32, choices=[("job_standard", "岗位标准"), ("resume_structure", "简历结构化"), ("resume_score", "简历评分")])
    status = models.CharField(max_length=24, choices=[("waiting_config", "等待模型配置"), ("pending", "等待处理"), ("extracting", "文本提取中"), ("ocr", "OCR 处理中"), ("model", "模型处理中"), ("waiting_review", "待人工确认"), ("succeeded", "已完成"), ("failed", "失败")], default="pending")
    requested_by = models.ForeignKey(User, on_delete=models.PROTECT, related_name="ai_processing_tasks")
    job = models.ForeignKey(RecruitmentJob, on_delete=models.PROTECT, null=True, blank=True, related_name="ai_tasks")
    document_version = models.ForeignKey(JobRequirementDocumentVersion, on_delete=models.PROTECT, null=True, blank=True, related_name="ai_tasks")
    resume = models.ForeignKey(Resume, on_delete=models.PROTECT, null=True, blank=True, related_name="ai_tasks")
    standard = models.ForeignKey(JobStandardVersion, on_delete=models.PROTECT, null=True, blank=True, related_name="ai_tasks")
    idempotency_key = models.CharField(max_length=160, unique=True)
    progress = models.PositiveSmallIntegerField(default=0)
    attempt_count = models.PositiveSmallIntegerField(default=0)
    max_attempts = models.PositiveSmallIntegerField(default=3)
    available_at = models.DateTimeField(default=timezone.now)
    leased_at = models.DateTimeField(null=True, blank=True)
    lease_expires_at = models.DateTimeField(null=True, blank=True)
    error_code = models.CharField(max_length=80, blank=True)
    error_message = models.CharField(max_length=500, blank=True)
    result_ref = models.JSONField(default=dict, blank=True)
```

- [x] **Step 4: Generate and inspect migration**

Run: `..\.venv\Scripts\python.exe manage.py makemigrations recruitment --name resume_intelligence`.

Expected: migration `0021_resume_intelligence.py` with all five models and constraints; no unrelated changes.

- [x] **Step 5: Run tests and Django checks**

Run: `..\.venv\Scripts\python.exe manage.py test recruitment.tests.test_resume_intelligence_models -v 2` and `..\.venv\Scripts\python.exe manage.py check`.

Expected: PASS and no system-check issues.

- [x] **Step 6: Commit**

```powershell
git add backend/recruitment/models.py backend/recruitment/migrations/0021_resume_intelligence.py backend/recruitment/tests/test_resume_intelligence_models.py
git commit -m "feat: model resume intelligence versions"
```

## Task 3: Local Word, PDF, and image extraction

**Files:**
- Modify: `backend/requirements.txt`
- Create: `backend/recruitment/services/file_extraction.py`
- Create: `backend/recruitment/tests/test_file_extraction.py`

- [x] **Step 1: Add bounded dependencies**

Add:

```text
python-docx>=1.2,<2
pypdf>=6.16,<7
pypdfium2>=5.13,<6
rapidocr>=3.9,<4
onnxruntime>=1.28,<2
```

`pypdf` and `pypdfium2` are selected instead of AGPL PyMuPDF so the local product retains a liberal PDF dependency boundary.

- [x] **Step 2: Write failing extraction tests**

Generate synthetic files during tests. Assert:

- DOCX paragraphs and table cells become ordered blocks.
- `.doc` invokes an injected LibreOffice converter and reports `libreoffice_unavailable` when absent.
- text PDF returns `pdf_text` and page-numbered blocks.
- low-text PDF renders pages and invokes an injected OCR adapter, returning `pdf_ocr`.
- PNG invokes OCR and returns bounding boxes.
- no extractor writes files outside its temporary directory.

- [x] **Step 3: Run tests and verify failure**

Run: `..\.venv\Scripts\python.exe manage.py test recruitment.tests.test_file_extraction -v 2`.

Expected: FAIL because the service does not exist.

- [x] **Step 4: Implement focused adapters**

Expose:

```python
@dataclass(frozen=True)
class TextBlock:
    text: str
    page: int | None
    section: str
    bbox: list[float] | None

@dataclass(frozen=True)
class ExtractionResult:
    method: str
    plain_text: str
    blocks: list[dict]

class ExtractionError(RuntimeError):
    def __init__(self, code: str, message: str): ...

def extract_file(path: Path, *, content_type: str, ocr=None, converter=None) -> ExtractionResult: ...
def extract_docx(path: Path) -> ExtractionResult: ...
def extract_pdf(path: Path, *, ocr) -> ExtractionResult: ...
def extract_image(path: Path, *, ocr) -> ExtractionResult: ...
```

Use `subprocess.run([soffice, "--headless", "--convert-to", "docx", "--outdir", temp_dir, source], shell=False, timeout=60)` for DOC. Treat fewer than 80 non-whitespace PDF characters as scanned. Render OCR pages at 2x scale with `pypdfium2`. Normalize OCR results into `{text, page, section, bbox}`.

- [x] **Step 5: Install dependencies and run tests**

Run: `..\.venv\Scripts\python.exe -m pip install -r requirements.txt` then the extraction test command.

Expected: installation succeeds on Windows and all extraction tests PASS.

- [x] **Step 6: Commit**

```powershell
git add backend/requirements.txt backend/recruitment/services/file_extraction.py backend/recruitment/tests/test_file_extraction.py
git commit -m "feat: extract local job and resume files"
```

## Task 4: AI task queue and automatic ingestion hooks

**Files:**
- Create: `backend/recruitment/services/ai_tasks.py`
- Create: `backend/recruitment/management/commands/run_ai_worker.py`
- Create: `backend/recruitment/tests/test_ai_tasks.py`
- Modify: `backend/recruitment/services/job_documents.py`
- Modify: `backend/recruitment/services/resumes.py`
- Modify: `scripts/start-local.ps1`
- Modify: `scripts/test-startup.ps1`

- [x] **Step 1: Write failing queue and hook tests**

Assert `enqueue_job_standard(job, user)` hashes all current active document versions into one idempotency key; `enqueue_resume_structure(resume, user)` uses resume SHA; uploads enqueue only after transaction commit; missing credentials create `waiting_config`; expired leases return to pending; retryable provider failures increase `available_at`; non-retryable failures stop; repeated enqueue returns the existing task.

- [x] **Step 2: Run tests and verify failure**

Run: `..\.venv\Scripts\python.exe manage.py test recruitment.tests.test_ai_tasks -v 2`.

Expected: FAIL because queue services and command do not exist.

- [x] **Step 3: Implement queue lifecycle**

Expose:

```python
def enqueue_job_standard(*, job, requested_by) -> tuple[AiProcessingTask, bool]: ...
def enqueue_resume_structure(*, resume, requested_by) -> tuple[AiProcessingTask, bool]: ...
def enqueue_resume_score(*, structured_resume, standard, requested_by) -> tuple[AiProcessingTask, bool]: ...
def lease_next_task(*, lease_seconds=180) -> AiProcessingTask | None: ...
def execute_task(task: AiProcessingTask) -> AiProcessingTask: ...
def retry_task(*, task, requested_by) -> AiProcessingTask: ...
```

Lease with `transaction.atomic()` and `select_for_update(skip_locked=True)` when supported; use a locked first row fallback for SQLite. Recover expired leases before selecting. Retry delays are 30, 120, and 300 seconds. Never retry authentication, invalid credential, unsupported model, invalid local file, or invalid schema errors automatically.

- [x] **Step 4: Connect ingestion services**

After a Word version becomes current, call `transaction.on_commit(lambda: enqueue_job_standard(job=document.job, requested_by=actor))`. After PDF or PNG resume archive succeeds, call `transaction.on_commit(lambda: enqueue_resume_structure(resume=resume, requested_by=actor))`. Preserve current workflow events and audit logging.

- [x] **Step 5: Add the AI worker command and launcher**

`run_ai_worker --once` processes at most one task. Continuous mode polls every `AI_POLL_SECONDS`, defaults to 3 seconds, and catches per-task exceptions without stopping the process. Update `start-local.ps1` to start one hidden AI worker beside the existing RPA worker; update startup smoke tests to require exactly one of each.

- [x] **Step 6: Run queue, ingestion, and startup tests**

Run:

```powershell
..\.venv\Scripts\python.exe manage.py test recruitment.tests.test_ai_tasks recruitment.tests.test_job_requirement_documents_api recruitment.tests.test_resume_archive -v 2
powershell -NoProfile -ExecutionPolicy Bypass -File ..\scripts\test-startup.ps1
```

Expected: all tests PASS and startup reports one RPA worker plus one AI worker.

- [x] **Step 7: Commit**

```powershell
git add backend/recruitment/services backend/recruitment/management/commands/run_ai_worker.py backend/recruitment/tests/test_ai_tasks.py scripts/start-local.ps1 scripts/test-startup.ps1
git commit -m "feat: process intelligence tasks in background"
```

## Task 5: Job-standard generation, editing, and publishing API

**Files:**
- Create: `backend/recruitment/services/job_standards.py`
- Create: `backend/recruitment/tests/test_job_standards_api.py`
- Modify: `backend/recruitment/serializers.py`
- Modify: `backend/recruitment/views.py`
- Modify: `backend/recruitment/urls.py`
- Modify: `backend/recruitment/services/ai_tasks.py`

- [x] **Step 1: Write failing service and API tests**

Cover model-generated draft evidence, listing by authorized job, editing draft only, weight sum exactly `100.00`, publish superseding the former version, published rows rejecting edits/deletes, no sensitive criteria keys, evidence block IDs resolving to extracted text, and viewer write denial.

- [x] **Step 2: Run tests and verify failure**

Run: `..\.venv\Scripts\python.exe manage.py test recruitment.tests.test_job_standards_api -v 2`.

Expected: FAIL because services and endpoints do not exist.

- [x] **Step 3: Implement validation and generation**

Expose:

```python
SENSITIVE_CRITERIA_KEYS = {"gender", "sex", "ethnicity", "marital_status", "pregnancy", "age"}

def build_standard_prompt(extractions: list[FileTextExtraction]) -> tuple[str, str]: ...
def validate_criteria(criteria: dict, *, require_publishable: bool) -> dict: ...
def create_standard_draft(*, job, document_versions, gateway, actor) -> JobStandardVersion: ...
def update_standard_draft(*, standard, criteria, unresolved_questions, actor) -> JobStandardVersion: ...
def publish_standard(*, standard, actor) -> JobStandardVersion: ...
```

Criteria shape:

```json
{
  "summary": "岗位目标",
  "dimensions": [{"key": "experience", "name": "相关经验", "weight": 40, "description": "判断说明", "evidence_block_ids": ["doc-12-block-3"]}],
  "required": [{"text": "必须条件", "evidence_block_ids": ["doc-12-block-5"]}],
  "preferred": [],
  "risks": []
}
```

Reject unknown evidence IDs and sensitive keys. Publishing runs inside a transaction, marks the previous published row `superseded`, and then publishes the selected draft.

- [x] **Step 4: Add scoped APIs**

Register `job-standards` with list/retrieve/update. Add actions:

- `POST /api/recruitment/job-standards/generate/` with `job`.
- `POST /api/recruitment/job-standards/<id>/publish/`.
- `POST /api/recruitment/job-standards/<id>/retry/`.

Filter through the same authorized-job queryset used by existing recruitment endpoints. Return 409 when editing a published version or generating without active documents.

- [x] **Step 5: Run tests**

Run the job-standard API tests and all existing job-document tests.

Expected: PASS.

- [x] **Step 6: Commit**

```powershell
git add backend/recruitment
git commit -m "feat: confirm versioned job standards"
```

## Task 6: Structured resume API and evidence rules

**Files:**
- Create: `backend/recruitment/services/resume_intelligence.py`
- Create: `backend/recruitment/tests/test_resume_intelligence_api.py`
- Modify: `backend/recruitment/services/ai_tasks.py`
- Modify: `backend/recruitment/serializers.py`
- Modify: `backend/recruitment/views.py`
- Modify: `backend/recruitment/urls.py`

- [x] **Step 1: Write failing structure tests**

Use both PDF and PNG extraction fixtures. Assert they produce the same schema, evidence points to valid block IDs, missing facts remain null, conflicts enter `warnings`, contact fields are not logged, repeated runs create a new structured version only when the source or model output changed, and unauthorized users cannot read another account's result.

- [x] **Step 2: Run tests and verify failure**

Run: `..\.venv\Scripts\python.exe manage.py test recruitment.tests.test_resume_intelligence_api -v 2`.

Expected: FAIL because structure endpoints do not exist.

- [x] **Step 3: Implement structure validation**

Use this top-level shape:

```json
{
  "basics": {"name": null, "phone": null, "email": null, "city": null, "target_role": null},
  "summary": null,
  "work_experiences": [],
  "project_experiences": [],
  "educations": [],
  "skills": [],
  "certificates": [],
  "languages": [],
  "total_experience_months": null,
  "achievements": [],
  "unknown_fields": []
}
```

Each experience and achievement accepts `evidence_block_ids`. The validator removes sensitive demographic fields, rejects evidence IDs not present in the extraction, and converts unsupported or guessed values to null plus a warning.

- [x] **Step 4: Add scoped APIs**

Add:

- `GET /api/recruitment/structured-resumes/?resume=<id>`.
- `GET /api/recruitment/structured-resumes/<id>/`.
- `POST /api/recruitment/resumes/<id>/retry-structure/`.
- `GET /api/recruitment/ai-tasks/?job=<id>&kind=<kind>&status=<status>`.
- `POST /api/recruitment/ai-tasks/<id>/retry/`.

Resume serializers expose latest structure status and ID but never return full extracted text in list responses.

- [x] **Step 5: Run tests and commit**

Run resume intelligence, resume archive, lifecycle, and permission tests. Expected: PASS.

```powershell
git add backend/recruitment
git commit -m "feat: structure archived resumes with evidence"
```

## Task 7: Evidence-backed scoring and batch API

**Files:**
- Modify: `backend/recruitment/services/resume_intelligence.py`
- Modify: `backend/recruitment/services/ai_tasks.py`
- Modify: `backend/recruitment/serializers.py`
- Modify: `backend/recruitment/views.py`
- Modify: `backend/recruitment/urls.py`
- Modify: `backend/recruitment/tests/test_resume_intelligence_api.py`

- [x] **Step 1: Write failing scoring tests**

Assert scoring without a published standard returns 409; each dimension references a declared criterion and valid resume evidence; dimensions with no evidence are marked `information_missing`; weighted total is recomputed server-side rather than trusted from the model; confidence is bounded 0-1; recommendation is one of three values; batch requests are idempotent; scoring does not modify application stage.

- [x] **Step 2: Run tests and verify failure**

Run the scoring test class only.

Expected: FAIL because scoring actions do not exist.

- [x] **Step 3: Implement assessment validation**

Expose:

```python
def validate_assessment_payload(*, payload: dict, standard: JobStandardVersion, structured: StructuredResumeVersion) -> dict: ...
def create_assessment(*, structured, standard, gateway) -> ResumeAssessment: ...
def enqueue_assessments(*, resume_ids: list[int], job, actor, request_id: uuid.UUID) -> list[AiProcessingTask]: ...
```

Dimension result shape:

```json
{"criterion_key": "experience", "score": 32, "max_score": 40, "status": "supported", "reason": "判断", "resume_evidence_block_ids": ["resume-9-page-1-block-4"]}
```

Allowed status values are `supported`, `not_supported`, and `information_missing`. Recompute total as the sum of clamped dimension scores. A no-evidence nonzero score is invalid. Recommendations remain advisory and never call stage services.

- [x] **Step 4: Add scoring APIs**

Add:

- `GET /api/recruitment/resume-assessments/?job=<id>&resume=<id>`.
- `POST /api/recruitment/resume-assessments/score/` with `request_id`, `job`, and `resume_ids`.
- `POST /api/recruitment/resume-assessments/<id>/rescore/` with a new `request_id`.

Return 409 for missing published standards or incomplete structures; return individual task results for valid batch members instead of discarding the entire batch because one resume is invalid.

- [x] **Step 5: Run tests and commit**

Run all resume-intelligence tests. Expected: PASS.

```powershell
git add backend/recruitment
git commit -m "feat: score resumes with traceable evidence"
```

## Task 8: Model connection and job-standard frontend

**Files:**
- Modify: `frontend/src/stores/modelCredential.js`
- Modify: `frontend/src/stores/modelCredential.test.js`
- Modify: `frontend/src/components/RecruitmentCopilotDrawer.vue`
- Create: `frontend/src/components/JobStandardDrawer.vue`
- Create: `frontend/src/components/JobStandardDrawer.test.js`
- Modify: `frontend/src/views/recruitment/RecruitmentResumesView.vue`
- Modify: `frontend/src/views/recruitment/RecruitmentResumesView.test.js`
- Modify: `frontend/src/style.css`

- [x] **Step 1: Write failing component and store tests**

Test the connection button states, masked credentials, standard status card, unique primary action, drawer loading/error/normal states, dimension add/remove, weights totaling 100, draft save, publish confirmation, and low-frequency actions inside the overflow menu.

- [x] **Step 2: Run tests and verify failure**

Run: `npm test -- --run src/stores/modelCredential.test.js src/components/JobStandardDrawer.test.js src/views/recruitment/RecruitmentResumesView.test.js`.

Expected: FAIL because test connection and the standard drawer do not exist.

- [x] **Step 3: Implement model connection state**

Add store state:

```javascript
connection: { status: 'unknown', model: '', latency_ms: null, detail: '' }
```

Add `testConnection()` POSTing to `account/model-credential/test/`. The drawer disables testing while saving, shows success latency, and shows API errors without exposing request headers or keys.

- [x] **Step 4: Implement the standard workspace**

Replace the NEXT PHASE placeholder with a real status card. `JobStandardDrawer` receives `job`, `standard`, and `documents`; emits `saved`, `published`, and `close`; loads full detail only when opened. Publish stays disabled until dimensions exist and weights total 100. Keep one visible primary action and move retry/history/deactivate to the overflow menu.

- [x] **Step 5: Run tests and build**

Run targeted tests and `npm run build`.

Expected: tests PASS and Vite build succeeds.

- [x] **Step 6: Commit**

```powershell
git add frontend/src
git commit -m "feat: confirm job standards in resume center"
```

## Task 9: Structured resume, assessment, and batch frontend

**Files:**
- Create: `frontend/src/components/ResumeIntelligencePanel.vue`
- Create: `frontend/src/components/ResumeIntelligencePanel.test.js`
- Modify: `frontend/src/views/recruitment/RecruitmentResumesView.vue`
- Modify: `frontend/src/views/recruitment/RecruitmentResumesView.test.js`
- Modify: `frontend/src/style.css`

- [x] **Step 1: Write failing UI tests**

Cover list columns for parse status, score, and recommendation; waiting-config/processing/failed/complete states; tabs for original, structured, evidence, and history; evidence links that activate the original tab and indicate page/region; row overflow retry; checkbox selection; and a floating batch bar that disappears when selection clears.

- [x] **Step 2: Run tests and verify failure**

Run the two component/page test files.

Expected: FAIL because the panel and interactions do not exist.

- [x] **Step 3: Implement the resume intelligence panel**

The component receives `resume`, `structure`, `assessment`, and `tasks`. It emits `retry-structure`, `score`, `rescore`, and `close`. Render unknown fields as “信息不足”, never as inferred facts. Render each dimension with score/max, status, reason, and evidence chips. Show an explicit “AI 建议，需 HR 复核” label beside recommendations.

- [x] **Step 4: Implement list and batch operations**

Load standards, latest structures, assessments, and tasks for the selected job. Add list columns and checkboxes. Create a UUID request ID per batch click and POST selected resume IDs. Poll active task states every three seconds only while active tasks exist; stop polling on unmount or job change.

- [x] **Step 5: Run frontend tests and build**

Run all frontend tests and production build.

Expected: all tests PASS and build succeeds.

- [x] **Step 6: Commit**

```powershell
git add frontend/src
git commit -m "feat: review structured resumes and assessments"
```

## Task 10: Dashboard, docs, and end-to-end verification

**Files:**
- Modify: `backend/recruitment/services/dashboard.py`
- Modify: `backend/recruitment/tests/test_dashboard_api.py`
- Modify: `frontend/src/views/recruitment/RecruitmentDashboardView.vue`
- Modify: `frontend/src/views/recruitment/RecruitmentDashboardView.test.js`
- Modify: `docs/autodev-api.md`
- Modify: `docs/autodev-design.md`
- Modify: `README.md`

- [x] **Step 1: Write failing dashboard tests**

Assert per-job counts for `pending_parse`, `pending_standard_review`, `pending_hr_review`, and `recommended_advance`; confirm archived/demo/current-job filters remain correct; test that each card links to the appropriate resume query.

- [x] **Step 2: Implement dashboard aggregation and cards**

Add a `resume_intelligence` object to the existing dashboard response. Render compact summary cards only when a job is selected; clicking a count routes to `/recruitment/resumes?filter=<status>` without editing data.

- [x] **Step 3: Update operational documentation**

Document the five new entities, endpoint matrix, AI worker, local extraction dependencies, LibreOffice behavior for `.doc`, model configuration, privacy boundary, and backup expectations. Remove the outdated statement that Copilot has no real backend.

- [x] **Step 4: Run migrations and all backend tests**

Run:

```powershell
..\.venv\Scripts\python.exe manage.py migrate --noinput
..\.venv\Scripts\python.exe manage.py test -v 2
..\.venv\Scripts\python.exe manage.py check
```

Expected: migrations apply, all Django tests PASS, and checks report no issues.

- [x] **Step 5: Run all frontend tests and build**

Run:

```powershell
npm test
npm run build
```

Expected: all Vitest tests PASS and Vite production build succeeds.

- [x] **Step 6: Run startup and browser smoke verification**

Run `scripts/test-startup.ps1`, start the app, log in, and verify:

1. Model connection can be tested without exposing the key.
2. Uploading a synthetic DOCX produces a draft.
3. Draft cannot publish unless weights equal 100.
4. A synthetic PDF and PNG both produce structured results.
5. Scoring is blocked before publish and succeeds after publish.
6. Evidence opens the original resume context.
7. Failed tasks show a reason and can be retried.
8. Changing the selected job removes data from the previous job.
9. Browser console has no errors.

- [ ] **Step 7: Commit final integration**

```powershell
git add backend frontend scripts docs README.md
git commit -m "feat: complete phase three resume intelligence"
```

## Plan completion checks

- Every third-phase requirement in the approved design maps to Tasks 1-10.
- Formal scoring is impossible before HR publication of a standard.
- Original files remain local; the model receives only extracted text blocks.
- PDF and PNG share one structured schema.
- All model conclusions require valid evidence IDs or are marked information missing.
- Sensitive demographic properties are removed before scoring.
- Existing BOSS automation, workflow confirmation, file versioning, and archive behavior remain intact.
- The local launcher starts one web process, one RPA worker, and one AI worker.
