# Recruitment Automation Phases 1 and 2 Implementation Plan

> **Implementation status (2026-08-25):** completed on `master`. Final acceptance requires the full Django recruitment suite, full Vitest suite, production frontend build, migration checks, and local live smoke checks. Real BOSS write acceptance remains limited to a user-designated test candidate.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver two runnable BOSS recruitment automation schemes, complete conversation ingestion, native resume requests, active resume discovery, job-bound Word documents, human-attention tasks, and recoverable business runs while deferring resume scoring.

**Architecture:** Extend the existing Django recruitment domain instead of creating a parallel automation service. Standard schemes compile into the existing versioned workflow graph, and the current workflow runtime remains the only executor. New focused services own documents, message ingestion and intent, human attention, campaign progress, and resume assets; Vue 3 presents these through standard-scheme, run, attention, and advanced-canvas sections.

**Tech Stack:** Django 5, Django REST Framework, SQLite, Vue 3, Pinia, Vitest, Django TestCase, BOSS CLI 0.6.6, Windows RPA worker.

---

### Task 1: Add phase-one and phase-two domain models

**Files:**
- Modify: `backend/recruitment/models.py`
- Create: `backend/recruitment/migrations/0016_recruitment_automation_phases.py`
- Test: `backend/recruitment/tests/test_recruitment_automation_phase_models.py`

- [ ] **Step 1: Write failing model tests**

Create tests that assert: a job document has ordered immutable versions and one current version; an account policy validates an interval from 1 to 1440 minutes; conversation messages deduplicate by thread and external key; human-attention records reference a job/application/run; search campaigns retain target, scan counts, stop reason and status.

- [ ] **Step 2: Run the model tests and verify missing-model failures**

Run: `.venv\Scripts\python.exe backend\manage.py test recruitment.tests.test_recruitment_automation_phase_models -v 2`

Expected: import failures for the new model names.

- [ ] **Step 3: Add focused models**

Add `JobRequirementDocument`, `JobRequirementDocumentVersion`, `MessageSyncPolicy`, `ConversationMessage`, `MessageAttachment`, `HumanAttention`, and `SearchCampaign`. Use `PROTECT` for audit-bearing job, version and run references; use conditional unique constraints for non-empty external message IDs and SHA-256 values; expose explicit status/type choices.

- [ ] **Step 4: Generate and inspect the migration**

Run: `.venv\Scripts\python.exe backend\manage.py makemigrations recruitment`

Expected: one migration containing only the planned models, fields, indexes and constraints.

- [ ] **Step 5: Run model tests and migrations**

Run: `.venv\Scripts\python.exe backend\manage.py test recruitment.tests.test_recruitment_automation_phase_models -v 2`

Expected: all new model tests pass.

- [ ] **Step 6: Commit**

```powershell
git add backend/recruitment/models.py backend/recruitment/migrations/0016_recruitment_automation_phases.py backend/recruitment/tests/test_recruitment_automation_phase_models.py
git commit -m "feat: add recruitment automation phase models"
```

### Task 2: Implement job requirement document versioning

**Files:**
- Create: `backend/recruitment/services/job_documents.py`
- Modify: `backend/recruitment/serializers.py`
- Modify: `backend/recruitment/views.py`
- Modify: `backend/recruitment/urls.py`
- Test: `backend/recruitment/tests/test_job_requirement_documents_api.py`

- [ ] **Step 1: Write API tests**

Cover `.doc` and `.docx` upload, 25 MB limit, SHA-256 generation, monotonically increasing versions, current-version switching, job ownership, download, deletion of unreferenced versions, and archive-only behavior for referenced versions.

- [ ] **Step 2: Run the tests and verify 404 or import failures**

Run: `.venv\Scripts\python.exe backend\manage.py test recruitment.tests.test_job_requirement_documents_api -v 2`

- [ ] **Step 3: Implement the document service and API**

Create transaction-safe `create_document_version`, `set_current_version`, and `remove_document_version` functions. Add nested serializers and a job-scoped viewset with multipart upload actions and authenticated file download.

- [ ] **Step 4: Run focused tests**

Run: `.venv\Scripts\python.exe backend\manage.py test recruitment.tests.test_job_requirement_documents_api -v 2`

Expected: all document API tests pass.

- [ ] **Step 5: Commit**

```powershell
git add backend/recruitment/services/job_documents.py backend/recruitment/serializers.py backend/recruitment/views.py backend/recruitment/urls.py backend/recruitment/tests/test_job_requirement_documents_api.py
git commit -m "feat: manage versioned job requirement documents"
```

### Task 3: Add human-attention and policy APIs

**Files:**
- Create: `backend/recruitment/services/human_attention.py`
- Modify: `backend/recruitment/serializers.py`
- Modify: `backend/recruitment/views.py`
- Modify: `backend/recruitment/urls.py`
- Test: `backend/recruitment/tests/test_human_attention_api.py`

- [ ] **Step 1: Write failing API tests**

Test account-scoped policy create/update with 1 and 1440 minute boundaries, active attention filtering, resolve/archive actions, idempotent attention creation, and workflow wake-up after a resolvable attention item is completed.

- [ ] **Step 2: Run the failing tests**

Run: `.venv\Scripts\python.exe backend\manage.py test recruitment.tests.test_human_attention_api -v 2`

- [ ] **Step 3: Implement service, serializers and viewsets**

`ensure_attention` must deduplicate open tasks by idempotency key. `resolve_attention` records actor, note and time, then invokes the workflow resume service only when the attention type is configured to resume its node.

- [ ] **Step 4: Run focused tests**

Run: `.venv\Scripts\python.exe backend\manage.py test recruitment.tests.test_human_attention_api -v 2`

- [ ] **Step 5: Commit**

```powershell
git add backend/recruitment/services/human_attention.py backend/recruitment/serializers.py backend/recruitment/views.py backend/recruitment/urls.py backend/recruitment/tests/test_human_attention_api.py
git commit -m "feat: add recruitment human attention center"
```

### Task 4: Compile and validate the two standard workflows

**Files:**
- Create: `backend/recruitment/services/standard_workflows.py`
- Modify: `backend/recruitment/services/workflows.py`
- Modify: `backend/recruitment/services/workflow_nodes.py`
- Modify: `backend/recruitment/serializers.py`
- Modify: `backend/recruitment/views.py`
- Test: `backend/recruitment/tests/test_standard_workflows.py`
- Test: `backend/recruitment/tests/test_workflow_service.py`

- [ ] **Step 1: Write failing compiler and validation tests**

Assert that passive and active standard schemes create ordinary `WorkflowTemplate` and `WorkflowVersion` rows with editable nodes and edges. Assert validation rejects a missing start/end, disconnected nodes, missing wait event, missing required node configuration, duplicate edges, and cycles.

- [ ] **Step 2: Run focused tests**

Run: `.venv\Scripts\python.exe backend\manage.py test recruitment.tests.test_standard_workflows recruitment.tests.test_workflow_service -v 2`

- [ ] **Step 3: Implement standard workflow compilation**

Passive graph: `start -> sync_messages -> classify_intent -> request_resume/human_attention/stop -> wait_resume -> archive_resume -> end`.

Active graph: `start -> search_and_pull_resumes -> human_attention -> end`.

The compiler writes ordinary graph nodes and never injects hidden runtime steps.

- [ ] **Step 4: Strengthen graph validation and expose create-standard action**

Return node-keyed validation errors so the canvas can highlight invalid nodes. Preserve current saved-version behavior and create an immutable graph snapshot on run creation.

- [ ] **Step 5: Run focused tests**

Run: `.venv\Scripts\python.exe backend\manage.py test recruitment.tests.test_standard_workflows recruitment.tests.test_workflow_service recruitment.tests.test_workflow_runtime -v 2`

- [ ] **Step 6: Commit**

```powershell
git add backend/recruitment/services/standard_workflows.py backend/recruitment/services/workflows.py backend/recruitment/services/workflow_nodes.py backend/recruitment/serializers.py backend/recruitment/views.py backend/recruitment/tests/test_standard_workflows.py backend/recruitment/tests/test_workflow_service.py
git commit -m "feat: add standard recruitment workflow schemes"
```

### Task 5: Correct CLI contracts and workflow search parameters

**Files:**
- Modify: `backend/recruitment/rpa/cli.py`
- Modify: `backend/recruitment/rpa/capabilities.py`
- Modify: `backend/recruitment/management/commands/run_rpa_worker.py`
- Modify: `backend/recruitment/services/workflow_nodes.py`
- Test: `backend/recruitment/tests/test_conversation_cli.py`
- Test: `backend/recruitment/tests/test_workflow_node_execution.py`
- Test: `backend/recruitment/tests/test_communication_worker.py`

- [ ] **Step 1: Update tests to the real BOSS CLI 0.6.6 contract**

Assert native resume request executes `chat <name> --strict` followed by `action request-attachment-resume`. Assert first-contact mode executes `send --text <approved text> --request-resume`. Assert search node payloads expose top-level `job`, `job_title`, `keyword`, `core`, and `bonus` fields expected by the worker.

- [ ] **Step 2: Run tests and observe the current `action resume` mismatch**

Run: `.venv\Scripts\python.exe backend\manage.py test recruitment.tests.test_conversation_cli recruitment.tests.test_workflow_node_execution recruitment.tests.test_communication_worker -v 2`

- [ ] **Step 3: Implement the corrected CLI wrapper and payload adapter**

Add explicit `request_attachment_resume` behavior, keep `preview` separate, and remove interview sending from the standard workflow palette without deleting historical model choices.

- [ ] **Step 4: Run focused tests**

Run: `.venv\Scripts\python.exe backend\manage.py test recruitment.tests.test_conversation_cli recruitment.tests.test_workflow_node_execution recruitment.tests.test_communication_worker -v 2`

- [ ] **Step 5: Commit**

```powershell
git add backend/recruitment/rpa/cli.py backend/recruitment/rpa/capabilities.py backend/recruitment/management/commands/run_rpa_worker.py backend/recruitment/services/workflow_nodes.py backend/recruitment/tests/test_conversation_cli.py backend/recruitment/tests/test_workflow_node_execution.py backend/recruitment/tests/test_communication_worker.py
git commit -m "fix: use native boss resume request action"
```

### Task 6: Ingest complete conversations and classify new messages

**Files:**
- Create: `backend/recruitment/services/conversation_ingestion.py`
- Create: `backend/recruitment/services/message_intent.py`
- Modify: `backend/recruitment/rpa/conversations.py`
- Modify: `backend/recruitment/management/commands/run_rpa_worker.py`
- Modify: `backend/recruitment/worker_api.py`
- Test: `backend/recruitment/tests/test_conversation_ingestion.py`
- Test: `backend/recruitment/tests/test_message_intent.py`
- Test: `backend/recruitment/tests/test_conversation_sync.py`

- [ ] **Step 1: Write ingestion and intent tests**

Cover first full import, later incremental import, fallback fingerprints, older-message PDF discovery, explicit rejection, explicit observation, ordinary interest, greeting-only messages, already-requested suppression, and candidate/job/account identity isolation.

- [ ] **Step 2: Run tests and verify failures**

Run: `.venv\Scripts\python.exe backend\manage.py test recruitment.tests.test_conversation_ingestion recruitment.tests.test_message_intent recruitment.tests.test_conversation_sync -v 2`

- [ ] **Step 3: Implement structured CLI parsing and ingestion**

The worker result must return every loaded message with direction, content, timestamp, external key when available, and attachment metadata. The API upserts messages and attachments transactionally and advances the cursor only after successful persistence.

- [ ] **Step 4: Implement deterministic keyword classification**

Priority: resume attachment, explicit rejection, explicit observation/company-or-job-learning, otherwise request resume. Empty/system/HR-only updates produce no outbound action.

- [ ] **Step 5: Connect classification to attention and native request tasks**

Create one idempotent outbound action per application and one idempotent attention item per observation event. Do not retry an uncertain write.

- [ ] **Step 6: Run focused tests**

Run: `.venv\Scripts\python.exe backend\manage.py test recruitment.tests.test_conversation_ingestion recruitment.tests.test_message_intent recruitment.tests.test_conversation_sync -v 2`

- [ ] **Step 7: Commit**

```powershell
git add backend/recruitment/services/conversation_ingestion.py backend/recruitment/services/message_intent.py backend/recruitment/rpa/conversations.py backend/recruitment/management/commands/run_rpa_worker.py backend/recruitment/worker_api.py backend/recruitment/tests/test_conversation_ingestion.py backend/recruitment/tests/test_message_intent.py backend/recruitment/tests/test_conversation_sync.py
git commit -m "feat: ingest and classify complete boss conversations"
```

### Task 7: Wake waiting workflow nodes from business events

**Files:**
- Create: `backend/recruitment/services/workflow_events.py`
- Modify: `backend/recruitment/services/workflow_nodes.py`
- Modify: `backend/recruitment/services/workflow_runtime.py`
- Modify: `backend/recruitment/services/resumes.py`
- Modify: `backend/recruitment/services/conversation_ingestion.py`
- Test: `backend/recruitment/tests/test_workflow_event_wakeup.py`

- [ ] **Step 1: Write event-correlation tests**

Assert a candidate reply wakes only the matching account/job/application `wait_reply`; a newly archived resume wakes only matching `wait_resume`; duplicate events are no-ops; a resumed node advances from the frozen snapshot.

- [ ] **Step 2: Run tests and verify waiting nodes remain stuck**

Run: `.venv\Scripts\python.exe backend\manage.py test recruitment.tests.test_workflow_event_wakeup -v 2`

- [ ] **Step 3: Implement event publication and correlation**

Publish `candidate_message.received` and `resume.archived` after transaction commit. Store event identity in node output and use row locks when waking nodes.

- [ ] **Step 4: Run focused and existing runtime tests**

Run: `.venv\Scripts\python.exe backend\manage.py test recruitment.tests.test_workflow_event_wakeup recruitment.tests.test_workflow_runtime recruitment.tests.test_workflow_node_execution -v 2`

- [ ] **Step 5: Commit**

```powershell
git add backend/recruitment/services/workflow_events.py backend/recruitment/services/workflow_nodes.py backend/recruitment/services/workflow_runtime.py backend/recruitment/services/resumes.py backend/recruitment/services/conversation_ingestion.py backend/recruitment/tests/test_workflow_event_wakeup.py
git commit -m "feat: wake recruitment workflows from messages and resumes"
```

### Task 8: Implement active search campaigns and online resume archiving

**Files:**
- Create: `backend/recruitment/services/search_campaigns.py`
- Modify: `backend/recruitment/rpa/cli.py`
- Modify: `backend/recruitment/management/commands/run_rpa_worker.py`
- Modify: `backend/recruitment/worker_api.py`
- Modify: `backend/recruitment/serializers.py`
- Modify: `backend/recruitment/views.py`
- Test: `backend/recruitment/tests/test_search_campaigns.py`
- Test: `backend/recruitment/tests/test_online_resume_worker.py`

- [ ] **Step 1: Write campaign and worker tests**

Cover target pull count, maximum scan count, duplicate skips, CLI preview output path parsing, PNG content validation, candidate/application creation, online-resume source labeling, per-candidate progress, stop reasons, and attention creation.

- [ ] **Step 2: Run tests and verify failures**

Run: `.venv\Scripts\python.exe backend\manage.py test recruitment.tests.test_search_campaigns recruitment.tests.test_online_resume_worker -v 2`

- [ ] **Step 3: Implement one business action `search_and_pull_resumes`**

Create a campaign, run the selected search source, scan unique discoveries, preview and save up to the target count, and stop on target, scan limit, account/risk error, paywall, quota, or user cancellation.

- [ ] **Step 4: Archive online-resume images separately from PDF attachments**

Allow validated `image/png` BOSS online-resume files in the resume service while retaining PDF-only validation for chat attachments and manual resume upload. Never overwrite an existing attachment resume.

- [ ] **Step 5: Run focused tests**

Run: `.venv\Scripts\python.exe backend\manage.py test recruitment.tests.test_search_campaigns recruitment.tests.test_online_resume_worker recruitment.tests.test_resume_archive -v 2`

- [ ] **Step 6: Commit**

```powershell
git add backend/recruitment/services/search_campaigns.py backend/recruitment/rpa/cli.py backend/recruitment/management/commands/run_rpa_worker.py backend/recruitment/worker_api.py backend/recruitment/serializers.py backend/recruitment/views.py backend/recruitment/tests/test_search_campaigns.py backend/recruitment/tests/test_online_resume_worker.py
git commit -m "feat: run active boss resume search campaigns"
```

### Task 9: Build the standard automation workspace UI

**Files:**
- Create: `frontend/src/components/StandardAutomationSchemes.vue`
- Create: `frontend/src/components/HumanAttentionCenter.vue`
- Create: `frontend/src/components/SearchCampaignPanel.vue`
- Modify: `frontend/src/views/recruitment/RecruitmentAutomationView.vue`
- Modify: `frontend/src/recruitmentAutomation.js`
- Modify: `frontend/src/styles.css`
- Test: `frontend/src/views/recruitment/RecruitmentAutomationView.test.js`
- Test: `frontend/src/components/HumanAttentionCenter.test.js`

- [ ] **Step 1: Write failing UI tests**

Assert four visible areas: standard schemes, run center, human attention, advanced canvas. Test interval boundary values, active search inputs, create/run actions, attention resolve/archive, run progress, empty/loading/error states, and removal of interview invitation from standard automation.

- [ ] **Step 2: Run focused Vitest tests**

Run: `npm test -- --run src/views/recruitment/RecruitmentAutomationView.test.js src/components/HumanAttentionCenter.test.js`

Working directory: `frontend`

- [ ] **Step 3: Implement focused components and API helpers**

Keep destructive actions behind the existing confirmation modal. Use current local line icons and `currentColor`. Preserve the current visual system and responsive desktop layout without adding mobile-only navigation.

- [ ] **Step 4: Run focused tests**

Run: `npm test -- --run src/views/recruitment/RecruitmentAutomationView.test.js src/components/HumanAttentionCenter.test.js`

- [ ] **Step 5: Commit**

```powershell
git add frontend/src/components/StandardAutomationSchemes.vue frontend/src/components/HumanAttentionCenter.vue frontend/src/components/SearchCampaignPanel.vue frontend/src/views/recruitment/RecruitmentAutomationView.vue frontend/src/recruitmentAutomation.js frontend/src/styles.css frontend/src/views/recruitment/RecruitmentAutomationView.test.js frontend/src/components/HumanAttentionCenter.test.js
git commit -m "feat: add standard recruitment automation workspace"
```

### Task 10: Add job document UI and resume source presentation

**Files:**
- Create: `frontend/src/components/JobRequirementDocuments.vue`
- Modify: `frontend/src/views/recruitment/RecruitmentJobsView.vue`
- Modify: `frontend/src/views/recruitment/RecruitmentResumesView.vue`
- Modify: `frontend/src/styles.css`
- Test: `frontend/src/components/JobRequirementDocuments.test.js`
- Test: `frontend/src/views/recruitment/RecruitmentResumesView.test.js`

- [ ] **Step 1: Write failing component tests**

Test Word upload, type selection, version list, current-version switch, download, delete/archive confirmation, job binding, and distinct “BOSS 在线简历” versus “附件简历” badges with a working preview/download entry.

- [ ] **Step 2: Run focused tests**

Run: `npm test -- --run src/components/JobRequirementDocuments.test.js src/views/recruitment/RecruitmentResumesView.test.js`

Working directory: `frontend`

- [ ] **Step 3: Implement the UI**

Mount requirement documents inside the selected job detail experience. Reuse existing modal, toast, icon and lifecycle patterns. Do not expose parsing or scoring controls.

- [ ] **Step 4: Run focused tests and build**

Run: `npm test -- --run src/components/JobRequirementDocuments.test.js src/views/recruitment/RecruitmentResumesView.test.js && npm run build`

- [ ] **Step 5: Commit**

```powershell
git add frontend/src/components/JobRequirementDocuments.vue frontend/src/views/recruitment/RecruitmentJobsView.vue frontend/src/views/recruitment/RecruitmentResumesView.vue frontend/src/styles.css frontend/src/components/JobRequirementDocuments.test.js frontend/src/views/recruitment/RecruitmentResumesView.test.js
git commit -m "feat: manage job documents and resume sources"
```

### Task 11: Finish canvas node configuration and lifecycle actions

**Files:**
- Modify: `frontend/src/components/WorkflowCanvas.vue`
- Modify: `frontend/src/components/WorkflowCanvas.test.js`
- Modify: `frontend/src/views/recruitment/RecruitmentAutomationView.vue`
- Modify: `frontend/src/views/recruitment/RecruitmentAutomationView.test.js`
- Modify: `frontend/src/styles.css`

- [ ] **Step 1: Write failing canvas tests**

Cover new business node types, node-specific required fields, conditional branches, graph validation display, version deletion/archive, run-current-version behavior, and removal of interview nodes from new standard workflows.

- [ ] **Step 2: Run tests and verify failures**

Run: `npm test -- --run src/components/WorkflowCanvas.test.js src/views/recruitment/RecruitmentAutomationView.test.js`

Working directory: `frontend`

- [ ] **Step 3: Implement node editors and lifecycle controls**

Do not change the existing free connection, drag, delete and auto-arrange behavior. Ensure saved graph data contains every configured field used by the backend executor.

- [ ] **Step 4: Run focused tests**

Run: `npm test -- --run src/components/WorkflowCanvas.test.js src/views/recruitment/RecruitmentAutomationView.test.js`

- [ ] **Step 5: Commit**

```powershell
git add frontend/src/components/WorkflowCanvas.vue frontend/src/components/WorkflowCanvas.test.js frontend/src/views/recruitment/RecruitmentAutomationView.vue frontend/src/views/recruitment/RecruitmentAutomationView.test.js frontend/src/styles.css
git commit -m "feat: complete recruitment workflow canvas controls"
```

### Task 12: Full verification, documentation and local smoke test

**Files:**
- Modify: `README.md`
- Modify: `docs/autodev-api.md`
- Modify: `docs/superpowers/plans/2026-08-25-recruitment-automation-phases-1-2.md`

- [ ] **Step 1: Run all backend tests**

Run: `.venv\Scripts\python.exe backend\manage.py test recruitment -v 2`

Expected: all recruitment tests pass.

- [ ] **Step 2: Run all frontend tests and production build**

Run: `npm test`

Run: `npm run build`

Working directory: `frontend`

Expected: all Vitest tests pass and Vite build completes.

- [ ] **Step 3: Apply migrations and run Django checks**

Run: `.venv\Scripts\python.exe backend\manage.py migrate`

Run: `.venv\Scripts\python.exe backend\manage.py check`

Expected: no unapplied migrations and no system-check issues.

- [ ] **Step 4: Perform safe local smoke checks**

Start the normal local server and worker. Verify standard-scheme creation, Word upload/version switch, dry-run snapshots, human-attention resolution, complete-message Mock ingestion, active-search Mock progress, archive/delete controls, and API error states. Do not send to a real candidate unless the user names the test candidate.

- [ ] **Step 5: Update documentation and mark completed plan items**

Document the corrected native request command, message-sync interval, file-type distinction, two standard schemes, human-attention behavior, active-search stop conditions, and real-account acceptance limits.

- [ ] **Step 6: Commit**

```powershell
git add README.md docs/autodev-api.md docs/superpowers/plans/2026-08-25-recruitment-automation-phases-1-2.md
git commit -m "docs: complete recruitment automation rollout"
```
