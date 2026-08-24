# Executable BOSS Recruitment Workflow Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the workflow canvas into an executable, auditable controlled-DAG runtime with custom connections, node configuration, dry-run/formal run controls, human gates, retry, pause, resume, and cancel.

**Architecture:** Enabled workflow versions produce immutable run snapshots. A Django scheduler activates nodes only after their active upstream nodes finish, preserves edge order for stable branches, pauses at human gates, and delegates BOSS work through existing RPA tasks and approval batches. Formal outbound messages can only enter the existing HR-confirmation path; dry run performs no external writes. Vue edits connections/configuration and observes runtime state without embedding execution logic.

**Tech Stack:** Django 5.2, Django REST Framework, SQLite, existing RPA/approval services, Vue 3, Pointer Events, Vitest, Vite.

---

### Task 1: Persist immutable workflow runs and ordered edges

**Files:**
- Modify: `backend/recruitment/models.py`
- Create: `backend/recruitment/migrations/0013_workflow_runtime.py`
- Test: `backend/recruitment/tests/test_workflow_runtime_models.py`

- [ ] Write failing model tests for ordered edges and `WorkflowRun`, `WorkflowNodeRun`, and `WorkflowRunEvent`, including unique node keys per run, idempotency keys, JSON snapshots, timestamps, attempts, and terminal states.
- [ ] Run `python manage.py test recruitment.tests.test_workflow_runtime_models -v 2` and confirm missing models/fields cause failure.
- [ ] Add `WorkflowEdge.order`; run statuses `queued/running/waiting_human/paused/succeeded/failed/cancelled`; node statuses `blocked/ready/running/waiting_human/succeeded/failed/skipped/cancelled`; and indexed foreign keys to version/account/job/actor.
- [ ] Generate/check the migration, rerun focused tests, and commit with `feat: add recruitment workflow runtime models`.

### Task 2: Implement a deterministic controlled-DAG scheduler

**Files:**
- Create: `backend/recruitment/services/workflow_runtime.py`
- Test: `backend/recruitment/tests/test_workflow_runtime.py`

- [ ] Write failing service tests for immutable snapshots, stable branch order, join waiting, disabled upstream skipping, human pause, failure propagation, idempotent advancement, pause/resume/cancel, retry, and terminal completion.
- [ ] Run the focused test and confirm the runtime service is absent.
- [ ] Implement `create_run`, `advance_run`, `pause_run`, `resume_run`, `cancel_run`, `decide_node`, and `retry_node` under row locks. A join becomes ready only when every active upstream is terminal-success/skipped; no v1 expression evaluator or arbitrary script is accepted.
- [ ] Record every transition as an event, keep advancement idempotent, rerun tests, and commit with `feat: add controlled workflow scheduler`.

### Task 3: Adapt workflow nodes to existing safe execution paths

**Files:**
- Modify: `backend/recruitment/models.py`
- Create: `backend/recruitment/migrations/0014_link_tasks_to_workflow_runs.py`
- Create: `backend/recruitment/services/workflow_nodes.py`
- Modify: `backend/recruitment/worker_api.py`
- Modify: `backend/recruitment/services/communications.py`
- Test: `backend/recruitment/tests/test_workflow_node_execution.py`

- [ ] Write failing tests that dry-run nodes never create outbound work, source/read nodes create linked allow-listed RPA tasks, task completion resumes a run, human gates wait, and formal `greet/request_resume/send_interview` nodes create approval drafts instead of direct sends.
- [ ] Add nullable `workflow_node_run` links to RPA tasks and execution batches, plus uniqueness guards preventing duplicate materialization during retries.
- [ ] Implement node adapters for search/recommend/read/import/wait/end, human gates, and simple communication. Reuse `AutomationApproval`, `ExecutionBatch`, `StepExecution`, and existing account concurrency rules.
- [ ] Resume node runs from task/batch completion callbacks; classify risk/CAPTCHA/unknown write outcomes as `waiting_human`, not success. Run backend tests and commit with `feat: connect workflows to safe recruitment actions`.

### Task 4: Expose workflow run and control APIs

**Files:**
- Modify: `backend/recruitment/serializers.py`
- Modify: `backend/recruitment/views.py`
- Modify: `backend/recruitment/urls.py`
- Test: `backend/recruitment/tests/test_workflow_run_api.py`

- [ ] Write failing API tests for `run`, `runs`, `pause`, `resume`, `cancel`, `decision`, and `retry`, plus object permissions, idempotency, invalid draft/formal execution, and account ownership.
- [ ] Run focused tests and confirm endpoints are missing.
- [ ] Add serializers with read-only snapshots/events and explicit action payloads. Formal run requires an enabled version, selected account, and confirmation; dry run may execute a valid draft without external writes.
- [ ] Return `409` for state conflicts, `400` for graph/config errors, and `403` for unauthorized accounts. Run tests and commit with `feat: expose recruitment workflow run controls`.

### Task 5: Support true custom connections and node configuration

**Files:**
- Modify: `frontend/src/components/WorkflowCanvas.vue`
- Modify: `frontend/src/components/WorkflowCanvas.test.js`
- Modify: `frontend/src/recruitmentAutomation.js`
- Modify: `frontend/src/styles.css`

- [ ] Write failing component tests for pointer-dragging an output port to a chosen input port, live connection preview, invalid/self/cycle rejection, selecting/reconfiguring a node, deleting/reconnecting edges, keyboard deletion, and preserving the graph after save/reload.
- [ ] Run the focused Vitest file and confirm current click-only linking/config omissions fail.
- [ ] Implement pointer-captured connection dragging with SVG preview, hit-testing, graph validation feedback, selected-node configuration drawer, and explicit edge/node removal. Keep automatic layout out of v1 and never silently rewrite user positions.
- [ ] Run focused tests and commit with `feat: make workflow graph connections configurable`.

### Task 6: Add run controls and live runtime visualization

**Files:**
- Modify: `frontend/src/views/recruitment/RecruitmentAutomationView.vue`
- Modify: `frontend/src/views/recruitment/RecruitmentAutomationView.test.js`
- Create: `frontend/src/components/WorkflowRunPanel.vue`
- Create: `frontend/src/components/WorkflowRunPanel.test.js`
- Modify: `frontend/src/styles.css`

- [ ] Write failing tests for dry-run/formal-run buttons, confirmation summary, account/job selection, polling, node status overlays, event timeline, human decision, pause/resume/cancel/retry, terminal results, and API errors.
- [ ] Run focused tests and confirm the controls are absent.
- [ ] Add an always-visible `试运行` control and a guarded `正式运行` control. Poll active runs every 2 seconds, color nodes by runtime state, animate only active edges, and show human actions in a side panel without expanding the canvas.
- [ ] Disable formal execution when the account is not ready or a required node config is incomplete. Run frontend tests/build and commit with `feat: add executable workflow run experience`.

### Task 7: Safety and end-to-end verification

**Files:**
- Modify: `scripts/smoke-recruitment-ui.py`
- Modify: `README.md` only if workflow operation is undocumented

- [ ] Run migration checks, the full Django suite, full Vitest suite, and the production build.
- [ ] Add a smoke path that creates a draft, custom-connects nodes, saves a version, runs dry mode to completion, runs formal mode only up to a human gate, then cancels it.
- [ ] Verify retry/idempotency, stale-account rejection, partial branch failure, join behavior, refresh persistence, and audit events. Automated verification must not send a real BOSS greeting, resume request, or interview invitation.
- [ ] Apply migrations, collect static files, restart services, run startup smoke tests, keep `master` clean, and commit final documentation or smoke changes with `test: verify executable recruitment workflows`.
