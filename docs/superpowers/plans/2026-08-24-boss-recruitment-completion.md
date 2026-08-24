# BOSS Recruitment Automation Completion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete the approved first-stage BOSS recruitment automation: HR-confirmed simple communications, conversation and resume synchronization, auditable stage advancement, and a controlled workflow editor.

**Architecture:** Django owns immutable approval snapshots, per-candidate execution state, resume metadata, workflow validation, and audit history. The Windows worker translates only registered capabilities into allow-listed boss-cli or Playwright/CDP operations, and marks uncertain writes as waiting for human review. Vue 3 exposes approvals, batch progress, PDF access, pipeline history, and a constrained node editor without enabling arbitrary scripts or unconfirmed sends.

**Tech Stack:** Django 5.2, Django REST Framework, SQLite, Windows worker, `@joohw/boss-cli 0.6.6`, Playwright/CDP, Vue 3, Vitest, Vite.

---

### Task 1: Conversation and stage domain models

**Files:**
- Modify: `backend/recruitment/models.py`
- Create: `backend/recruitment/migrations/0010_conversation_resume_workflow.py`
- Test: `backend/recruitment/tests/test_conversation_models.py`

- [ ] Write failing model tests for immutable message snapshots, structured interview invitations, resume hashes and versions, conversation cursors, stage history, workflow versions/nodes/edges, and unique per-account candidate contacts.
- [ ] Run `python manage.py test recruitment.tests.test_conversation_models -v 2` and confirm failures are caused by missing models.
- [ ] Add focused models: `ConversationAction`, `InterviewInvitation`, `ConversationSyncState`, `ApplicationStageHistory`, resume hash/version/source metadata, `WorkflowTemplate`, `WorkflowVersion`, `WorkflowNode`, and `WorkflowEdge`.
- [ ] Generate the migration, rerun the focused test, then commit with `feat: add recruitment communication and workflow models`.

### Task 2: HR confirmation batches and safe stage transitions

**Files:**
- Create: `backend/recruitment/services/communications.py`
- Create: `backend/recruitment/services/stages.py`
- Modify: `backend/recruitment/services/approvals.py`
- Modify: `backend/recruitment/rpa/tasks.py`
- Test: `backend/recruitment/tests/test_communication_service.py`
- Test: `backend/recruitment/tests/test_stage_service.py`

- [ ] Write failing tests proving prepare is a draft only, approval freezes edited text, each candidate gets one step, deterministic duplicates are skipped, quota is consumed once per executed item, and uncertain/failed writes do not advance stage.
- [ ] Run the focused tests and confirm the expected failures.
- [ ] Implement prepare/approve/batch materialization, per-step idempotency, duplicate-contact checks, action-specific stage transitions, and auditable manual stage corrections requiring a reason.
- [ ] Run focused and recruitment test suites, then commit with `feat: add safe communication approval batches`.

### Task 3: Worker adapters for simple BOSS communication

**Files:**
- Modify: `backend/recruitment/rpa/capabilities.py`
- Modify: `backend/recruitment/rpa/cli.py`
- Create: `backend/recruitment/rpa/conversations.py`
- Modify: `backend/recruitment/management/commands/run_rpa_worker.py`
- Modify: `backend/recruitment/worker_api.py`
- Test: `backend/recruitment/tests/test_conversation_cli.py`
- Test: `backend/recruitment/tests/test_communication_worker.py`

- [ ] Write failing contract tests for allow-listed `list`, `chat`, `greet`, `send`, and `action resume` commands; strict identity checks; no retry after uncertain send; and partial batch continuation.
- [ ] Run the focused tests and confirm the expected failures.
- [ ] Add CLI parsers and worker executors for greet, resume request, interview text, and read-only conversation sync. Require exact refreshed context before writes; classify CAPTCHA, risk control, ambiguous identity, and unknown outcome as `waiting_human`.
- [ ] Complete steps one at a time through the worker API, persist evidence, update batch counters, and advance stages only on verified success.
- [ ] Run focused and recruitment test suites, then commit with `feat: execute confirmed boss communication batches`.

### Task 4: Conversation sync and resume archive

**Files:**
- Create: `backend/recruitment/services/resumes.py`
- Create: `backend/recruitment/rpa/resumes.py`
- Modify: `backend/recruitment/rpa/playwright_adapter.py`
- Modify: `backend/recruitment/worker_api.py`
- Modify: `backend/recruitment/views.py`
- Modify: `backend/recruitment/serializers.py`
- Modify: `backend/recruitment/urls.py`
- Test: `backend/recruitment/tests/test_resume_archive.py`
- Test: `backend/recruitment/tests/test_resume_api.py`

- [ ] Write failing tests for attachment MIME validation, SHA-256 deduplication, candidate/job association, monotonic versions, online PDF approval, same-origin preview/download, and stage advancement after a valid archive.
- [ ] Run focused tests and confirm missing behavior.
- [ ] Implement controlled file ingestion, version/hash metadata, conversation cursor updates, online-resume PDF task preparation, Playwright result ingestion, preview/download/version APIs, and audit events.
- [ ] Use fixture files and mocked CDP only; never open a real candidate resume during automated tests.
- [ ] Run focused and recruitment test suites, then commit with `feat: archive boss resumes with versioned pdf access`.

### Task 5: Controlled workflow validator and execution API

**Files:**
- Create: `backend/recruitment/services/workflows.py`
- Modify: `backend/recruitment/views.py`
- Modify: `backend/recruitment/serializers.py`
- Modify: `backend/recruitment/urls.py`
- Test: `backend/recruitment/tests/test_workflow_service.py`
- Test: `backend/recruitment/tests/test_workflow_api.py`

- [ ] Write failing tests rejecting cycles, arbitrary node types, send paths without human approval, missing account/source, mutation of enabled versions, and concurrent control of one account.
- [ ] Run focused tests and confirm failures.
- [ ] Implement draft/version/create/copy/enable/disable APIs, graph validation, safe node configuration schemas, and creation of approval batches rather than direct outbound execution.
- [ ] Run focused and recruitment test suites, then commit with `feat: add controlled recruitment workflow engine`.

### Task 6: Vue communication, resume, pipeline and workflow UX

**Files:**
- Create: `frontend/src/recruitmentCommunications.js`
- Create: `frontend/src/recruitmentCommunications.test.js`
- Create: `frontend/src/components/CommunicationConfirmDrawer.vue`
- Create: `frontend/src/components/AutomationBatchPanel.vue`
- Create: `frontend/src/components/WorkflowCanvas.vue`
- Modify: `frontend/src/views/recruitment/RecruitmentCandidatesView.vue`
- Modify: `frontend/src/views/recruitment/RecruitmentAutomationView.vue`
- Modify: `frontend/src/views/recruitment/RecruitmentPipelineView.vue`
- Modify: `frontend/src/views/recruitment/RecruitmentResumesView.vue`
- Modify: `frontend/src/styles.css`
- Test: corresponding Vue view/component test files

- [ ] Write failing Vitest tests for candidate selection, editable confirmation snapshot, structured interview form, per-item progress, required stage reason, resume versions/PDF entry, and safe workflow validation feedback.
- [ ] Run `npm test -- --run` and confirm expected failures.
- [ ] Implement a restrained desktop UI with local line icons, teal interaction states, drawers, progress transitions, contextual empty/error states, and reduced-motion support.
- [ ] Keep AI scoring visibly reserved but inactive, and make all outbound controls create confirmations instead of direct tasks.
- [ ] Run frontend tests and `npm run build`, then commit with `feat: complete recruitment automation workspace ui`.

### Task 7: End-to-end verification and integration

**Files:**
- Modify: `README.md`
- Modify: Windows launch scripts only if verification exposes a startup defect

- [ ] Run `python manage.py makemigrations --check --dry-run` and the full Django test suite.
- [ ] Run the full Vitest suite and production Vite build.
- [ ] Start a temporary Django/worker environment and verify account isolation, draft approval, batch partial failure, conversation fixtures, resume PDF preview/download, manual stage correction, and workflow validation via HTTP/browser smoke tests.
- [ ] Confirm no test invokes a real outbound BOSS write and document the explicit real-account acceptance checklist.
- [ ] Merge locally to `master`, rerun all verification on the merged tree, apply migrations, collect static files, restart the web service and worker, then verify `http://127.0.0.1:8000/` responds.

