# BOSS Account Status and Recruitment Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make BOSS account state accurate and recoverable, preserve isolated Edge login sessions, replace the empty recruitment dashboard with an actionable HR workspace, and prevent blank pages after deployment.

**Architecture:** Django remains the source of truth for account observations, stale-task recovery, permission-scoped dashboard aggregates, and audit history. The Windows worker observes CDP sessions periodically outside the normal task queue, while explicit open/re-login operations still use the allow-listed worker path. Vue polls lightweight status data and renders actionable dashboard regions. Deployment verification validates the MIME type of every Vite asset referenced by the served HTML.

**Tech Stack:** Django 5.2, Django REST Framework, SQLite, Windows worker, Edge CDP, Vue 3, Vitest, Vite, PowerShell.

---

### Task 1: Prevent blank pages caused by stale static assets

**Files:**
- Modify: `scripts/test-startup.ps1`
- Modify: `scripts/start-local.ps1`
- Test: `scripts/test-windows-compat.ps1`

- [ ] Add a failing compatibility assertion that startup checks fetch `/`, extract every `/static/assets/*.js` and `.css` URL, and reject HTML MIME responses.
- [ ] Run `powershell -ExecutionPolicy Bypass -File scripts/test-windows-compat.ps1` and confirm the new assertion fails against the current script.
- [ ] Update startup order to run the production frontend build when requested, `collectstatic --noinput`, migrations, then restart services. Extend `test-startup.ps1` to require JavaScript MIME containing `javascript` and CSS MIME containing `text/css`.
- [ ] Run both PowerShell tests and commit with `fix: verify collected frontend assets at startup`.

### Task 2: Recover stale running RPA tasks

**Files:**
- Create: `backend/recruitment/services/task_recovery.py`
- Modify: `backend/recruitment/worker_api.py`
- Modify: `backend/recruitment/rpa/tasks.py`
- Test: `backend/recruitment/tests/test_task_recovery.py`
- Test: `backend/recruitment/tests/test_worker_api.py`

- [ ] Write failing tests proving expired `leased` work can be re-leased, expired `running` work becomes failed with `worker_lease_expired`, an audit event is appended, and its account leaves the misleading running state.
- [ ] Run `python manage.py test recruitment.tests.test_task_recovery recruitment.tests.test_worker_api -v 2` and confirm the stale-running cases fail.
- [ ] Implement `recover_stale_tasks(now=None)` inside a transaction. Requeue expired leases, fail expired running work, clear worker/lease fields, and derive account state from `login_status` and `verification_status`.
- [ ] Extend the lease whenever a worker reports progress so active work is not reclaimed, invoke recovery before leasing, rerun focused tests, and commit with `fix: recover abandoned recruitment tasks`.

### Task 3: Add independent real-time account observations

**Files:**
- Modify: `backend/recruitment/worker_api.py`
- Modify: `backend/recruitment/urls.py`
- Modify: `backend/recruitment/views.py`
- Modify: `backend/recruitment/management/commands/run_rpa_worker.py`
- Modify: `backend/recruitment/rpa/status.py`
- Test: `backend/recruitment/tests/test_account_status_api.py`
- Test: `backend/recruitment/tests/test_worker_command.py`

- [ ] Write failing API tests for permission-scoped status targets, worker-token-authenticated batch observations, immediate CDP inspection, and transitions among `browser_stopped`, `waiting_login`, `waiting_human`, `ready`, `error`, and verification failures.
- [ ] Write a failing worker-loop test proving every enabled account is inspected about every 30 seconds even while another account has a normal task.
- [ ] Add `GET /worker/status-targets/`, `POST /worker/status-observations/`, and `POST /boss-accounts/<id>/check-status/`. Persist timestamps and verification detail atomically; never store a BOSS password or cookie in Django.
- [ ] Add a worker observation timer that calls the existing CDP inspector using each account's fixed `user_data_dir`/port. This persistent profile preserves valid BOSS cookies across restarts, while BOSS can still invalidate the session.
- [ ] Run focused and full recruitment backend tests, then commit with `feat: monitor boss account sessions in real time`.

### Task 4: Make account login controls honest and recoverable

**Files:**
- Modify: `frontend/src/recruitmentAutomation.js`
- Modify: `frontend/src/views/recruitment/RecruitmentAutomationView.vue`
- Modify: `frontend/src/views/recruitment/RecruitmentAutomationView.test.js`
- Modify: `frontend/src/styles.css`

- [ ] Write failing Vitest cases for 5-second polling, readable state labels, last-check time, `立即检查`, `打开登录`, and `重新登录`, including verification/risk guidance.
- [ ] Run `npm test -- --run RecruitmentAutomationView.test.js` and confirm the new cases fail.
- [ ] Add API helpers and a compact account-row status treatment. Re-login must open the same isolated Edge profile and trigger an observation after the user completes login; it must not delete the profile automatically.
- [ ] Ensure timers stop on unmount, reduced-motion is respected, and failed requests preserve the last good status with a non-blocking warning.
- [ ] Run focused frontend tests and commit with `feat: add live boss login status controls`.

### Task 5: Build a permission-scoped recruitment dashboard API

**Files:**
- Create: `backend/recruitment/services/dashboard.py`
- Modify: `backend/recruitment/views.py`
- Test: `backend/recruitment/tests/test_dashboard_api.py`

- [ ] Write failing tests for superuser/non-superuser scope and a stable payload containing `metrics`, `today_actions`, `alerts`, `funnel`, `job_progress`, `trend`, and `recent_tasks`.
- [ ] Use fixtures covering active jobs, candidate stages, missing resumes, interviews, hires, non-ready accounts, waiting-human tasks, and failures; run the focused test and confirm failure.
- [ ] Implement one service that scopes jobs through authorized BOSS accounts, groups the recruitment funnel, computes 7-day trend buckets, ranks urgent actions/alerts, calculates per-job hiring progress, and serializes recent automation outcomes with route/action metadata.
- [ ] Keep database aggregation bounded and return empty arrays rather than omitting sections. Run backend tests and commit with `feat: add actionable recruitment dashboard data`.

### Task 6: Replace the dashboard placeholder with an HR work surface

**Files:**
- Modify: `frontend/src/views/recruitment/RecruitmentDashboardView.vue`
- Create: `frontend/src/views/recruitment/RecruitmentDashboardView.test.js`
- Modify: `frontend/src/styles.css`

- [ ] Write failing component tests for metric cards, today's work, alerts, funnel, job progress, 7-day trend, recent automation, section-level loading errors, and a useful all-empty state.
- [ ] Run the focused Vitest file and confirm it fails against the current placeholder.
- [ ] Implement a responsive desktop layout using the existing restrained teal visual language and local line icons. Cards navigate to filtered destination pages; alerts expose one clear action; charts use accessible labels and CSS/SVG rather than decorative animation.
- [ ] Run focused/full frontend tests and `npm run build`, then commit with `feat: build recruitment operations dashboard`.

### Task 7: Integrated verification and local deployment

**Files:**
- Modify: `README.md` only if an operator step is missing

- [ ] Run `python manage.py makemigrations --check --dry-run`, the full Django suite, full Vitest suite, and `npm run build`.
- [ ] Run migrations, `collectstatic --noinput`, restart Django and exactly one worker, then run both PowerShell startup checks.
- [ ] Verify in the browser that account statuses update without creating normal tasks, re-login reuses its profile, the dashboard has populated demo-backed sections, and every referenced JS/CSS asset returns the correct MIME type.
- [ ] Commit any documentation correction with `docs: document boss session monitoring`, leave `master` clean, and report real-account verification steps without sending any BOSS message.
