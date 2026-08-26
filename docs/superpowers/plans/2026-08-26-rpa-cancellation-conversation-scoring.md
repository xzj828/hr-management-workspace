# Safer Recruitment Automation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make running RPA tasks interruptible, restrict message automation to unread conversations for the selected job, and turn all hard/core requirements into double-weight scoring inputs without automatic rejection.

**Architecture:** Add a worker-visible cancellation state and make boss-cli execution poll it while running. Freeze the selected job in conversation-sync tasks and filter unread conversation metadata before opening any chat, then enforce the same job boundary while persisting. Keep legacy scoring fields readable, but adapt hard requirements into priority scoring dimensions and remove every automatic rejection path.

**Tech Stack:** Django 5/DRF, Python subprocess management, SQLite migrations, Vue 3, Vitest, Django test runner.

---

### Task 1: Add a cancellable RPA task state and control endpoint

**Files:**
- Modify: `backend/recruitment/models.py`
- Create: `backend/recruitment/migrations/0028_rpatask_cancel_requested.py`
- Modify: `backend/recruitment/rpa/tasks.py`
- Modify: `backend/recruitment/worker_api.py`
- Modify: `backend/recruitment/urls.py`
- Modify: `backend/recruitment/views.py`
- Test: `backend/recruitment/tests/test_rpa_api.py`
- Test: `backend/recruitment/tests/test_worker_api.py`

- [ ] **Step 1: Write failing API tests for pending and running cancellation**

Add tests proving that pending tasks become `cancelled`, running tasks become `cancel_requested`, repeat cancellation is idempotent, and a late success callback cannot overwrite cancellation:

```python
def test_running_task_requests_worker_cancellation(self):
    task = RpaTask.objects.create(
        boss_account=self.account, action=RpaTask.Action.SYNC_POSITIONS,
        status=RpaTask.Status.RUNNING, created_by=self.hr, worker=self.worker,
    )
    self.client.force_login(self.hr)
    response = self.client.post(f"/api/recruitment/rpa-tasks/{task.pk}/cancel/")
    self.assertEqual(response.status_code, 200)
    self.assertEqual(response.data["status"], "cancel_requested")
```

```python
def test_cancel_requested_task_rejects_late_success_result(self):
    task = self.make_leased_task(status=RpaTask.Status.CANCEL_REQUESTED)
    response = self.worker_client.post(
        f"/api/recruitment/worker/tasks/{task.pk}/complete/",
        {"worker_key": self.worker.key, "status": "succeeded", "result": {}},
        format="json", HTTP_X_RPA_WORKER_TOKEN=settings.RPA_WORKER_TOKEN,
    )
    self.assertEqual(response.data["status"], "cancelled")
```

- [ ] **Step 2: Run the focused tests and verify RED**

Run:

```powershell
cd backend
python manage.py test recruitment.tests.test_rpa_api recruitment.tests.test_worker_api -v 2
```

Expected: failures because `cancel_requested` and the worker control endpoint do not exist.

- [ ] **Step 3: Implement the cancellation state and server contract**

Add `CANCEL_REQUESTED = "cancel_requested", "正在取消"` to `RpaTask.Status`, include it in the per-account active constraint, and generate migration `0028`. Change `cancel_task` to use this rule:

```python
if locked.status == RpaTask.Status.PENDING:
    locked.status = RpaTask.Status.CANCELLED
    locked.completed_at = timezone.now()
elif locked.status in {RpaTask.Status.LEASED, RpaTask.Status.RUNNING}:
    locked.status = RpaTask.Status.CANCEL_REQUESTED
else:
    return locked
```

Add a worker-authenticated GET endpoint returning only the control state for the assigned task:

```python
@api_view(["GET"])
@permission_classes([HasRpaWorkerToken])
def task_control_view(request, task_id):
    task = RpaTask.objects.filter(pk=task_id).only("status", "worker_id").first()
    if task is None:
        return Response({"detail": "任务不存在"}, status=404)
    return Response({"status": task.status, "cancel_requested": task.status == RpaTask.Status.CANCEL_REQUESTED})
```

Make the completion endpoint convert a `cancel_requested` task to `cancelled` before any result-specific persistence. Do not ingest conversation rows, archive files, change stages, or record success after cancellation.

- [ ] **Step 4: Run focused tests and verify GREEN**

Run the command from Step 2. Expected: all tests pass.

- [ ] **Step 5: Commit the server cancellation contract**

```powershell
git add backend/recruitment/models.py backend/recruitment/migrations/0028_rpatask_cancel_requested.py backend/recruitment/rpa/tasks.py backend/recruitment/worker_api.py backend/recruitment/urls.py backend/recruitment/views.py backend/recruitment/tests/test_rpa_api.py backend/recruitment/tests/test_worker_api.py
git commit -m "feat: request cancellation for running rpa tasks"
```

### Task 2: Interrupt boss-cli without closing the isolated browser

**Files:**
- Modify: `backend/recruitment/rpa/cli.py`
- Modify: `backend/recruitment/management/commands/run_rpa_worker.py`
- Test: `backend/recruitment/tests/test_boss_cli.py`
- Test: `backend/recruitment/tests/test_worker_command.py`

- [ ] **Step 1: Write failing process-cancellation tests**

Test that a polling callback terminates the boss-cli process and raises a dedicated cancellation exception while never calling a browser-close function:

```python
@patch("recruitment.rpa.cli.subprocess.Popen")
def test_run_terminates_cli_when_cancellation_is_requested(self, popen):
    process = popen.return_value
    process.poll.return_value = None
    process.communicate.side_effect = [subprocess.TimeoutExpired("boss", 0.25), (b"", b"")]
    runner = BossCliRunner(cli_path="C:/tools/boss.exe", cancel_requested=lambda: True)
    with self.assertRaises(BossCliCancelled):
        runner.positions(self.account)
    process.terminate.assert_called_once()
```

Add a Worker test proving `WorkerApiClient.control(task_id)` is polled and the final callback reports `cancelled`.

- [ ] **Step 2: Run tests and verify RED**

```powershell
cd backend
python manage.py test recruitment.tests.test_boss_cli recruitment.tests.test_worker_command -v 2
```

Expected: failures because execution still uses blocking `subprocess.run`.

- [ ] **Step 3: Implement monitored Popen execution**

Introduce `BossCliCancelled`, a task-scoped cancellation callback, and a `Popen.communicate(timeout=0.25)` loop. On cancellation, call `terminate()`, wait briefly, then `kill()` only for the boss-cli process if needed. Use `CREATE_NO_WINDOW` on Windows for the CLI process. Do not target Edge/Chrome PIDs and do not call `stop_login`.

Bind the callback in `WorkerEngine.execute_task` to:

```python
lambda: self.api.control(task["id"]).get("cancel_requested") is True
```

Catch `BossCliCancelled` separately and submit `{"status": "cancelled", "error_code": "cancelled_by_user"}`. Check the same callback at multi-row loop boundaries before starting another browser action.

- [ ] **Step 4: Run focused tests and verify GREEN**

Run the command from Step 2. Expected: all tests pass.

- [ ] **Step 5: Commit Worker interruption**

```powershell
git add backend/recruitment/rpa/cli.py backend/recruitment/management/commands/run_rpa_worker.py backend/recruitment/tests/test_boss_cli.py backend/recruitment/tests/test_worker_command.py
git commit -m "fix: interrupt cancelled boss cli commands"
```

### Task 3: Filter conversations by unread state and selected job before opening

**Files:**
- Modify: `backend/recruitment/rpa/conversations.py`
- Modify: `backend/recruitment/management/commands/run_rpa_worker.py`
- Modify: `backend/recruitment/services/communications.py`
- Modify: `backend/recruitment/worker_api.py`
- Test: `backend/recruitment/tests/test_conversation_sync.py`
- Test: `backend/recruitment/tests/test_worker_command.py`
- Test: `backend/recruitment/tests/test_communication_service.py`
- Test: `backend/recruitment/tests/test_worker_api.py`

- [ ] **Step 1: Write failing parser and Worker filtering tests**

```python
def test_parses_conversation_job_title(self):
    row = parse_conversation_list("1. 林然｜产品经理｜未读 2")[0]
    self.assertEqual(row["job_title"], "产品经理")
```

```python
def test_sync_opens_only_unread_conversations_for_selected_job(self):
    task = {"request_payload": {"job": 7, "job_title": "产品经理"}}
    outcome = execute_sync_conversations(task, self.account, runner)
    runner.conversations.assert_called_once_with(self.account, unread=True)
    runner.open_chat.assert_called_once_with(self.account, "目标候选人")
    self.assertEqual(len(outcome["result"]["conversations"]), 1)
```

The fixture must include an already-read target-job row, an unread other-job row, and one unread target-job row.

- [ ] **Step 2: Run focused tests and verify RED**

```powershell
cd backend
python manage.py test recruitment.tests.test_conversation_sync recruitment.tests.test_worker_command recruitment.tests.test_communication_service recruitment.tests.test_worker_api -v 2
```

Expected: parser lacks `job_title`, Worker calls `list` without `--unread`, and service matching ignores the selected job.

- [ ] **Step 3: Implement fail-closed conversation filtering**

Parse the first unlabeled field after the candidate name as `job_title`. In `execute_sync_conversations`, require `request_payload.job` and `job_title`, call `runner.conversations(account, unread=True)`, normalize whitespace, and filter before `open_chat`. Return skipped counts/reasons separately from eligible rows.

Change persistence to require the frozen job:

```python
def sync_conversation_states(*, account, job, rows, actor=None):
    applications = list(
        JobApplication.objects.filter(job=job, job__boss_account=account, candidate__name=name)[:2]
    )
```

In `complete_task_view`, resolve the job by both ID and account. If missing or mismatched, reject the result without ingesting messages or attachments. Stable external candidate IDs take precedence; name-only matching is allowed only when unique within the selected job.

- [ ] **Step 4: Run focused tests and verify GREEN**

Run the command from Step 2. Expected: all tests pass and only the eligible row opens.

- [ ] **Step 5: Commit selected-job unread filtering**

```powershell
git add backend/recruitment/rpa/conversations.py backend/recruitment/management/commands/run_rpa_worker.py backend/recruitment/services/communications.py backend/recruitment/worker_api.py backend/recruitment/tests/test_conversation_sync.py backend/recruitment/tests/test_worker_command.py backend/recruitment/tests/test_communication_service.py backend/recruitment/tests/test_worker_api.py
git commit -m "fix: sync only unread conversations for selected job"
```

### Task 4: Convert hard requirements into double-weight priority scoring

**Files:**
- Modify: `backend/recruitment/services/job_standards.py`
- Modify: `backend/recruitment/services/resume_intelligence.py`
- Modify: `backend/recruitment/services/stages.py`
- Modify: `frontend/src/components/JobStandardDrawer.vue`
- Modify: `frontend/src/components/ResumeIntelligencePanel.vue`
- Test: `backend/recruitment/tests/test_job_standards_api.py`
- Test: `backend/recruitment/tests/test_resume_intelligence_api.py`
- Test: `frontend/src/components/JobStandardDrawer.test.js`
- Test: `frontend/src/components/ResumeIntelligencePanel.test.js`

- [ ] **Step 1: Write failing scoring tests**

Add tests proving legacy hard requirements are adapted into priority dimensions at twice the ordinary average weight, normalized to 100, and never change recommendation or application stage:

```python
def test_legacy_hard_failure_is_weighted_but_never_rejects(self):
    criteria = scoring_criteria()
    criteria["hard_requirements"] = [{
        "key": "degree", "text": "本科及以上", "evidence_block_ids": [],
        "rule": {"field": "highest_degree", "operator": "gte", "value": "本科"},
    }]
    criteria["auto_reject_on_hard_fail"] = True
    JobStandardVersion.objects.filter(pk=self.standard.pk).update(criteria=criteria)
    self.standard.refresh_from_db()
    payload = assessment_payload(self.block_id)
    payload["recommendation"] = ResumeAssessment.Recommendation.RECOMMEND
    assessment = create_assessment(
        standard=self.standard, structured=self.structured,
        gateway=FakeGateway(payload), request_id=uuid.uuid4(), actor=self.user,
    )
    self.application.refresh_from_db()
    self.assertFalse(assessment.auto_rejected)
    self.assertNotEqual(self.application.stage, JobApplication.Stage.REJECTED)
    self.assertEqual(assessment.recommendation, payload["recommendation"])
```

Add UI assertions that “硬性指标”, “淘汰条件”, “自动淘汰”, and the checkbox are absent, while “重点评分项” and the `2 倍权重` explanation are present.

- [ ] **Step 2: Run focused tests and verify RED**

```powershell
cd backend
python manage.py test recruitment.tests.test_job_standards_api recruitment.tests.test_resume_intelligence_api -v 2
cd ..\frontend
npm test -- JobStandardDrawer ResumeIntelligencePanel
```

Expected: existing auto-rejection behavior and old UI wording cause failures.

- [ ] **Step 3: Implement priority-dimension normalization**

Add one pure helper that converts legacy `hard_requirements` to priority dimensions. If ordinary dimension weights are `w1..wn`, give each priority item raw weight `2 * average(w1..wn)`, combine all raw weights, then proportionally normalize and round so the final dimension total is exactly 100. Preserve explicit HR-edited dimension weights relative to each other.

Remove the deterministic override that sets recommendation to `hold` and remove the call to `reject_for_hard_requirements`. Keep legacy input fields accepted for compatibility, but normalize `auto_reject_on_hard_fail` to `False` for new/updated standards. Update prompts to call these items priority scoring evidence, never gates.

Update the Vue components to edit/display “重点评分项”, explain double weight, and render unmet items as score gaps. Remove the automatic-rejection toggle and footer text.

- [ ] **Step 4: Run focused backend and frontend tests and verify GREEN**

Run the commands from Step 2. Expected: all tests pass.

- [ ] **Step 5: Commit scoring behavior**

```powershell
git add backend/recruitment/services/job_standards.py backend/recruitment/services/resume_intelligence.py backend/recruitment/services/stages.py backend/recruitment/tests/test_job_standards_api.py backend/recruitment/tests/test_resume_intelligence_api.py frontend/src/components/JobStandardDrawer.vue frontend/src/components/ResumeIntelligencePanel.vue frontend/src/components/JobStandardDrawer.test.js frontend/src/components/ResumeIntelligencePanel.test.js
git commit -m "fix: score priority requirements without auto rejection"
```

### Task 5: Full regression verification

**Files:**
- Modify only if a regression test exposes an in-scope defect.

- [ ] **Step 1: Run all backend tests**

```powershell
cd backend
python manage.py test -v 1
```

Expected: all backend tests pass.

- [ ] **Step 2: Run all frontend tests and production build**

```powershell
cd frontend
npm test
npm run build
```

Expected: all Vitest suites pass and Vite build exits successfully.

- [ ] **Step 3: Verify migrations and worktree scope**

```powershell
cd backend
python manage.py makemigrations --check --dry-run
cd ..
git diff --check
git status --short
```

Expected: no missing migrations, no whitespace errors, and the user-owned untracked `tools/` directory remains untouched.

- [ ] **Step 4: Review branch commits**

```powershell
git log --oneline --decorate -10
```

Expected: separate commits exist for cancellation contract, Worker interruption, conversation filtering, and scoring behavior.
