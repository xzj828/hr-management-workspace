# BOSS Read-only RPA Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a Windows-only, auditable BOSS RPA vertical slice that supports isolated Chrome/Edge accounts, human login, status checks, and read-only position synchronization through the installed `boss-cli`.

**Architecture:** Django owns account configuration, authorization, task leases, normalized results, and audit history. A separate Django management-command Worker polls authenticated local HTTP endpoints and invokes `boss-cli` with account-scoped browser environment variables; Vue presents account state and task history without exposing outbound actions.

**Tech Stack:** Python 3.13, Django 5, Django REST Framework, SQLite, `@joohw/boss-cli 0.6.6`, Windows Chrome/Edge CDP, Vue 3, Vitest.

---

## File map

- `backend/recruitment/models.py`: browser configuration and RPA persistence.
- `backend/recruitment/rpa/browser.py`: trusted browser discovery, derived profile directories, port checks, and profile locks.
- `backend/recruitment/rpa/cli.py`: `boss-cli` discovery, environment construction, subprocess execution, decoding, and position parsing.
- `backend/recruitment/rpa/status.py`: CDP page inspection and normalized login states.
- `backend/recruitment/rpa/sync.py`: idempotent position upsert.
- `backend/recruitment/rpa/tasks.py`: task creation, leasing, completion, retry, and audit transitions.
- `backend/recruitment/worker_api.py`: token-authenticated Worker HTTP endpoints.
- `backend/recruitment/management/commands/run_rpa_worker.py`: persistent Windows Worker loop.
- `backend/recruitment/serializers.py`, `views.py`, `urls.py`, `permissions.py`: HR-facing API.
- `frontend/src/views/recruitment/RecruitmentAutomationView.vue`: automation workspace.
- `frontend/src/recruitmentAutomation.js`: labels and action availability as testable pure functions.
- `scripts/start-local.ps1`: lifecycle-manage Waitress and the Worker together.

### Task 1: Persist browser and RPA state

**Files:**
- Modify: `backend/recruitment/models.py`
- Create: `backend/recruitment/migrations/0002_readonly_rpa.py`
- Create: `backend/recruitment/tests/__init__.py`
- Move: `backend/recruitment/tests.py` → `backend/recruitment/tests/test_foundation.py`

- [ ] **Step 1: Write failing model tests**

Move the existing foundation tests into `tests/test_foundation.py`, import `BossAccount`, `Candidate`, `JobApplication`, `RecruitmentJob`, `RpaTask`, `RpaTaskEvent`, and `RpaWorker` from `recruitment.models`, and add tests proving browser defaults, task actions/statuses, events, and one active task per account:

```python
from django.db import IntegrityError, transaction
from django.utils import timezone
from recruitment.models import RpaTask, RpaTaskEvent, RpaWorker

def test_boss_account_defaults_to_chrome_and_unverified(self):
    self.assertEqual(self.account.browser_type, BossAccount.BrowserType.CHROME)
    self.assertEqual(self.account.login_status, BossAccount.LoginStatus.UNKNOWN)

def test_account_cannot_have_two_active_tasks(self):
    RpaTask.objects.create(
        boss_account=self.account,
        action=RpaTask.Action.CHECK_STATUS,
        created_by=self.hr,
    )
    with self.assertRaises(IntegrityError), transaction.atomic():
        RpaTask.objects.create(
            boss_account=self.account,
            action=RpaTask.Action.SYNC_POSITIONS,
            created_by=self.hr,
        )

def test_task_event_records_a_timeline_entry(self):
    worker = RpaWorker.objects.create(key="local-worker", hostname="WIN-HR")
    task = RpaTask.objects.create(
        boss_account=self.account,
        action=RpaTask.Action.CHECK_STATUS,
        created_by=self.hr,
        worker=worker,
    )
    event = RpaTaskEvent.objects.create(task=task, event="leased", message="任务已领取")
    self.assertEqual(event.task, task)
```

- [ ] **Step 2: Run the focused tests and confirm RED**

Run:

```powershell
.\.venv\Scripts\python.exe .\backend\manage.py test recruitment.tests.test_foundation.RecruitmentFoundationModelTests --verbosity 2
```

Expected: import/model failures for `RpaTask`, `RpaTaskEvent`, and `RpaWorker`.

- [ ] **Step 3: Add models and migration**

Extend `BossAccount` with:

```python
class BrowserType(models.TextChoices):
    CHROME = "chrome", "Chrome"
    EDGE = "edge", "Edge"

class LoginStatus(models.TextChoices):
    UNKNOWN = "unknown", "未检查"
    BROWSER_STOPPED = "browser_stopped", "浏览器未启动"
    WAITING_LOGIN = "waiting_login", "等待登录"
    WAITING_HUMAN = "waiting_human", "等待人工验证"
    READY = "ready", "已登录"
    ERROR = "error", "异常"

browser_type = models.CharField(max_length=16, choices=BrowserType.choices, default=BrowserType.CHROME)
browser_executable = models.CharField(max_length=500, blank=True)
user_data_dir = models.CharField(max_length=500, blank=True)
login_status = models.CharField(max_length=32, choices=LoginStatus.choices, default=LoginStatus.UNKNOWN)
verification_status = models.CharField(max_length=40, blank=True)
last_checked_at = models.DateTimeField(null=True, blank=True)
```

Add `RpaWorker`, `RpaTask`, `RpaTaskEvent`, and `RecruitmentAuditLog`. `RpaTask` uses a UUID primary key and has only `CHECK_STATUS` and `SYNC_POSITIONS`; use a conditional unique constraint on `boss_account` for `pending`, `leased`, and `running` states. `waiting_human` is a completed task outcome so the HR can create a fresh status check after finishing the manual step.

Use these exact persistence fields:

```text
RpaWorker: key, hostname, version, status, capabilities(JSON), last_seen_at, created_at, updated_at
RpaTask: id(UUID), boss_account, action, status, created_by, worker(nullable), request_payload(JSON), result(JSON), error_code, error_message, lease_expires_at, started_at, completed_at, created_at, updated_at
RpaTaskEvent: task, level, event, message, data(JSON), created_at
RecruitmentAuditLog: actor(nullable), boss_account(nullable), action, target_id, detail(JSON), created_at
```

- [ ] **Step 4: Generate and inspect the migration**

Run:

```powershell
.\.venv\Scripts\python.exe .\backend\manage.py makemigrations recruitment
.\.venv\Scripts\python.exe .\backend\manage.py migrate --plan
```

Expected: one recruitment migration containing only the new fields, models, indexes, and constraint.

- [ ] **Step 5: Run tests and commit**

```powershell
.\.venv\Scripts\python.exe .\backend\manage.py test recruitment --verbosity 2
git add backend/recruitment/models.py backend/recruitment/migrations backend/recruitment/tests.py backend/recruitment/tests
git commit -m "feat: add boss rpa persistence"
```

### Task 2: Derive safe Chrome and Edge configurations

**Files:**
- Create: `backend/recruitment/rpa/__init__.py`
- Create: `backend/recruitment/rpa/browser.py`
- Create: `backend/recruitment/tests/test_rpa_browser.py`
- Modify: `backend/recruitment/serializers.py`
- Modify: `backend/recruitment/views.py`

- [ ] **Step 1: Write failing browser configuration tests**

```python
from pathlib import Path
from django.test import SimpleTestCase, override_settings
from recruitment.rpa.browser import browser_configuration

@override_settings(RPA_PROFILE_ROOT=Path("C:/hr-test/profiles"))
class BrowserConfigurationTests(SimpleTestCase):
    def test_edge_uses_trusted_executable_and_derived_profile(self):
        config = browser_configuration("edge", "boss-account-a", 53471, exists=lambda path: True)
        self.assertTrue(str(config.executable).lower().endswith("microsoft\\edge\\application\\msedge.exe"))
        self.assertEqual(config.user_data_dir, Path("C:/hr-test/profiles/boss-account-a"))
        self.assertEqual(config.port, 53471)

    def test_profile_slug_cannot_escape_root(self):
        with self.assertRaisesMessage(ValueError, "浏览器目录标识无效"):
            browser_configuration("chrome", "../default", 53470, exists=lambda path: True)

    def test_second_profile_lock_is_rejected(self):
        with ProfileLock(Path("C:/hr-test/profiles/boss-account-a")):
            with self.assertRaisesMessage(ProfileLockedError, "浏览器目录正在使用"):
                with ProfileLock(Path("C:/hr-test/profiles/boss-account-a")):
                    pass
```

- [ ] **Step 2: Run tests and confirm RED**

```powershell
.\.venv\Scripts\python.exe .\backend\manage.py test recruitment.tests.test_rpa_browser --verbosity 2
```

- [ ] **Step 3: Implement trusted discovery and derived paths**

Use a frozen configuration object and fixed candidate locations:

```python
@dataclass(frozen=True)
class BrowserConfiguration:
    browser_type: str
    executable: Path
    user_data_dir: Path
    port: int

BROWSER_CANDIDATES = {
    "chrome": (
        Path(os.environ.get("PROGRAMFILES", "C:/Program Files")) / "Google/Chrome/Application/chrome.exe",
        Path(os.environ.get("LOCALAPPDATA", "")) / "Google/Chrome/Application/chrome.exe",
    ),
    "edge": (
        Path(os.environ.get("PROGRAMFILES(X86)", "C:/Program Files (x86)")) / "Microsoft/Edge/Application/msedge.exe",
        Path(os.environ.get("PROGRAMFILES", "C:/Program Files")) / "Microsoft/Edge/Application/msedge.exe",
    ),
}
```

Resolve the final profile path and verify `Path.is_relative_to(settings.RPA_PROFILE_ROOT.resolve())`. Do not accept executable paths or profile paths from request JSON.

Implement `ProfileLock` with a process-local set of resolved profile paths plus a `.worker.lock` file opened in binary append mode and `msvcrt.locking(lock_file.fileno(), msvcrt.LK_NBLCK, 1)` on Windows. Hold the lock for the entire task execution and release both guards in `__exit__`; translate either contention path to `ProfileLockedError("浏览器目录正在使用")`. Add `port_is_available(port)` using a loopback socket bind before the first browser launch, while allowing an existing CDP `/json/version` response for the same configured account.

- [ ] **Step 4: Make account creation server-controlled**

Update `BossAccountSerializer` so the client supplies only `name`, `browser_type`, `daily_contact_limit`, and `active`. Generate `browser_profile = f"boss-{uuid.uuid4().hex[:12]}"`, choose the first free port from `53470..53569`, derive `browser_executable` and `user_data_dir`, and add the creator to `authorized_users` in `BossAccountViewSet.perform_create()`.

- [ ] **Step 5: Test the API and commit**

```powershell
.\.venv\Scripts\python.exe .\backend\manage.py test recruitment --verbosity 2
git add backend/recruitment/rpa backend/recruitment/serializers.py backend/recruitment/views.py backend/recruitment/tests
git commit -m "feat: isolate boss browser profiles"
```

### Task 3: Add RPA task lifecycle and HR API

**Files:**
- Create: `backend/recruitment/rpa/tasks.py`
- Modify: `backend/recruitment/serializers.py`
- Modify: `backend/recruitment/views.py`
- Modify: `backend/recruitment/urls.py`
- Create: `backend/recruitment/tests/test_rpa_api.py`

- [ ] **Step 1: Write failing permission and lifecycle tests**

Cover these requests:

```python
def test_hr_can_create_check_status_task(self):
    self.client.force_login(self.hr)
    response = self.client.post("/api/recruitment/rpa-tasks/", {
        "boss_account": self.account.id,
        "action": "check_status",
        "request_payload": {"open_login": True},
    }, format="json")
    self.assertEqual(response.status_code, 201)

def test_viewer_cannot_create_task(self):
    self.client.force_login(self.viewer)
    response = self.client.post("/api/recruitment/rpa-tasks/", {
        "boss_account": self.account.id,
        "action": "sync_positions",
    }, format="json")
    self.assertEqual(response.status_code, 403)

def test_unapproved_action_is_rejected(self):
    self.client.force_login(self.hr)
    response = self.client.post("/api/recruitment/rpa-tasks/", {
        "boss_account": self.account.id,
        "action": "send_message",
    }, format="json")
    self.assertEqual(response.status_code, 400)
```

- [ ] **Step 2: Confirm RED**

```powershell
.\.venv\Scripts\python.exe .\backend\manage.py test recruitment.tests.test_rpa_api --verbosity 2
```

- [ ] **Step 3: Implement lifecycle services**

Add transaction-wrapped functions:

```python
def append_event(*, task, event, message, data=None, level="info") -> RpaTaskEvent:
    return RpaTaskEvent.objects.create(
        task=task, event=event, message=message, data=data or {}, level=level
    )

@transaction.atomic
def create_task(*, account, action, actor, request_payload=None) -> RpaTask:
    locked = BossAccount.objects.select_for_update().get(pk=account.pk)
    if not is_hr_user(actor) or not locked.authorized_users.filter(pk=actor.pk).exists():
        raise PermissionDenied("无权操作该 BOSS 账号")
    if action not in RpaTask.Action.values:
        raise ValidationError("不支持的自动化动作")
    task = RpaTask.objects.create(
        boss_account=locked, action=action, created_by=actor,
        request_payload=request_payload or {},
    )
    append_event(task=task, event="created", message="任务已创建")
    RecruitmentAuditLog.objects.create(actor=actor, boss_account=locked, action="task_created", target_id=str(task.pk))
    return task

@transaction.atomic
def cancel_task(*, task, actor) -> RpaTask:
    locked = RpaTask.objects.select_for_update().get(pk=task.pk)
    if not is_hr_user(actor) or not locked.boss_account.authorized_users.filter(pk=actor.pk).exists():
        raise PermissionDenied("无权操作该 BOSS 账号")
    if locked.status != RpaTask.Status.PENDING:
        raise ValidationError("当前任务不能取消")
    locked.status = RpaTask.Status.CANCELLED
    locked.completed_at = timezone.now()
    locked.save(update_fields=["status", "completed_at"])
    append_event(task=locked, event="cancelled", message="任务已取消")
    return locked

def retry_task(*, task, actor) -> RpaTask:
    if task.status != RpaTask.Status.FAILED:
        raise ValidationError("只有失败任务可以重试")
    return create_task(account=task.boss_account, action=task.action, actor=actor, request_payload=task.request_payload)
```

`create_task` verifies HR permission, account authorization, active account, action whitelist, and absence of an active task. Every transition creates both an event and an audit record.

- [ ] **Step 4: Expose `RpaTaskViewSet`**

Support list/retrieve/create plus explicit `POST /rpa-tasks/{id}/cancel/` and `/retry/`. Filter accounts and tasks by `authorized_users=request.user` unless the user is superuser. Include nested read-only events in detail responses.

Add `GET /automation/summary/` returning the latest Worker heartbeat, CLI availability/version, counts by task status, and whether any task is active. This endpoint reads persisted state only and never invokes the CLI.

- [ ] **Step 5: Verify and commit**

```powershell
.\.venv\Scripts\python.exe .\backend\manage.py test recruitment --verbosity 2
git add backend/recruitment/rpa/tasks.py backend/recruitment/serializers.py backend/recruitment/views.py backend/recruitment/urls.py backend/recruitment/tests/test_rpa_api.py
git commit -m "feat: add boss rpa task api"
```

### Task 4: Integrate the installed boss-cli safely

**Files:**
- Create: `backend/recruitment/rpa/cli.py`
- Create: `backend/recruitment/tests/test_boss_cli.py`

- [ ] **Step 1: Write failing CLI tests with a temporary executable fixture**

Test discovery order, environment isolation, timeout, non-zero exit, GB18030 fallback, and position parsing. The parser fixture must match `boss-cli 0.6.6` output:

```python
POSITIONS_OUTPUT = """已读取 2 个职位。
状态统计：开放中 1｜待开放 0｜已关闭 1
来源页面：https://www.zhipin.com/web/chat/job/list
职位明细：
1. 实施工程师｜状态:开放中｜北京｜看过我:2｜沟通过:1｜感兴趣:0｜ID:job-101
2. 运维工程师｜状态:已关闭｜上海｜看过我:4｜沟通过:2｜感兴趣:1｜ID:job-102
"""

def test_position_parser_returns_stable_records(self):
    rows = parse_positions(POSITIONS_OUTPUT)
    self.assertEqual(rows[0]["external_id"], "job-101")
    self.assertEqual(rows[0]["title"], "实施工程师")
    self.assertEqual(rows[0]["status"], "open")
```

- [ ] **Step 2: Confirm RED**

```powershell
.\.venv\Scripts\python.exe .\backend\manage.py test recruitment.tests.test_boss_cli --verbosity 2
```

- [ ] **Step 3: Implement `BossCliRunner`**

Core API:

```python
@dataclass(frozen=True)
class CliAccountConfig:
    executable: str
    user_data_dir: str
    cdp_port: int

@dataclass(frozen=True)
class CliResult:
    returncode: int
    stdout: str
    stderr: str

class BossCliRunner:
    ALLOWED = {"login": (), "positions": ()}

    def version(self) -> str:
        return self._run("--version", env=os.environ.copy(), timeout_seconds=20).stdout.strip()

    def login(self, account: CliAccountConfig) -> CliResult:
        return self._run("login", env=self._account_env(account), timeout_seconds=90)

    def positions(self, account: CliAccountConfig) -> list[dict]:
        result = self._run("positions", env=self._account_env(account), timeout_seconds=180)
        return parse_positions(result.stdout)
```

Resolve `BOSS_CLI`, `boss`, then `boss-cli`. Build a fresh environment containing:

```python
{
    "CHROME_PATH": account.browser_executable,
    "BOSS_BROWSER_USER_DATA_DIR": account.user_data_dir,
    "BOSS_BROWSER_REMOTE_DEBUGGING_PORT": str(account.cdp_port),
    "BOSS_BROWSER_HEADLESS": "false",
}
```

Use `subprocess.run([cli_path, command], shell=False, capture_output=True, timeout=timeout_seconds)`. Decode bytes with strict UTF-8 first, then GB18030, then UTF-8 replacement. Cap stored stdout/stderr at 32 KiB and never accept user-provided command arguments.

- [ ] **Step 4: Implement the parser**

Parse only lines beginning with `<number>. `. Extract title, `状态`, and `ID`; derive `external_id = "derived-" + sha256(normalized_line).hexdigest()[:24]` only when the CLI omits ID. Map `开放中 → open`, `已关闭 → closed`, all other states to `paused`.

- [ ] **Step 5: Verify against the installed CLI without opening BOSS**

```powershell
.\.venv\Scripts\python.exe .\backend\manage.py shell -c "from recruitment.rpa.cli import BossCliRunner; print(BossCliRunner().version())"
```

Expected: `0.6.6` or `@joohw/boss-cli 0.6.6`.

- [ ] **Step 6: Run tests and commit**

```powershell
.\.venv\Scripts\python.exe .\backend\manage.py test recruitment.tests.test_boss_cli --verbosity 2
git add backend/recruitment/rpa/cli.py backend/recruitment/tests/test_boss_cli.py
git commit -m "feat: add isolated boss cli adapter"
```

### Task 5: Add Worker authentication, leases, and execution

**Files:**
- Modify: `backend/config/settings.py`
- Create: `backend/recruitment/rpa/status.py`
- Create: `backend/recruitment/worker_api.py`
- Create: `backend/recruitment/management/__init__.py`
- Create: `backend/recruitment/management/commands/__init__.py`
- Create: `backend/recruitment/management/commands/run_rpa_worker.py`
- Modify: `backend/recruitment/urls.py`
- Create: `backend/recruitment/tests/test_worker_api.py`
- Create: `backend/recruitment/tests/test_worker_command.py`

- [ ] **Step 1: Write failing Worker API tests**

Verify rejection without a token, heartbeat upsert, single-task lease, lease expiry, and result submission:

```python
@override_settings(RPA_WORKER_TOKEN="test-worker-secret")
def test_worker_leases_oldest_pending_task(self):
    response = self.client.post(
        "/api/recruitment/worker/tasks/lease/",
        {"worker_key": "local-worker"},
        format="json",
        HTTP_X_RPA_WORKER_TOKEN="test-worker-secret",
    )
    self.assertEqual(response.status_code, 200)
    self.assertEqual(response.data["task"]["id"], self.task.id)
```

- [ ] **Step 2: Confirm RED**

```powershell
.\.venv\Scripts\python.exe .\backend\manage.py test recruitment.tests.test_worker_api recruitment.tests.test_worker_command --verbosity 2
```

- [ ] **Step 3: Add a persistent local Worker secret**

Follow the existing `local_secret.key` pattern with `backend/local_worker.key`, generating `secrets.token_urlsafe(48)` when absent. Expose `RPA_WORKER_TOKEN`, `RPA_PROFILE_ROOT`, `RPA_API_BASE_URL`, and `RPA_POLL_SECONDS` in settings. Ensure both local key files remain ignored by Git.

- [ ] **Step 4: Implement Worker endpoints**

Use `secrets.compare_digest()` in a dedicated DRF permission. Endpoints:

```text
POST worker/heartbeat/
POST worker/tasks/lease/
POST worker/tasks/<uuid>/event/
POST worker/tasks/<uuid>/complete/
```

Lease payload includes only the task UUID, action, `open_login`, and server-controlled browser configuration. Completion accepts normalized status, result, error code, and error message; it cannot change task action or account.

- [ ] **Step 5: Implement the Worker command**

`run_rpa_worker` loops with interruptible waits, heartbeats every 15 seconds, and one task at a time. Execution table is static:

```python
EXECUTORS = {
    "check_status": execute_check_status,
    "sync_positions": execute_sync_positions,
}
```

Wrap both executors in `with ProfileLock(config.user_data_dir):`. `check_status` optionally calls `runner.login(account)` only when `open_login` is true, then inspects `http://127.0.0.1:<port>/json/list`. `sync_positions` calls `runner.positions(account)`. Map login/security URLs and page titles to `waiting_human`; map missing CDP to `browser_stopped`; do not auto-retry `token_invalid` or `risk_control`.

- [ ] **Step 6: Verify and commit**

```powershell
.\.venv\Scripts\python.exe .\backend\manage.py test recruitment --verbosity 2
git add backend/config/settings.py backend/recruitment/worker_api.py backend/recruitment/management backend/recruitment/urls.py backend/recruitment/tests .gitignore
git commit -m "feat: add local boss rpa worker"
```

### Task 6: Synchronize positions idempotently

**Files:**
- Create: `backend/recruitment/rpa/sync.py`
- Modify: `backend/recruitment/worker_api.py`
- Create: `backend/recruitment/tests/test_position_sync.py`

- [ ] **Step 1: Write failing sync tests**

```python
def test_sync_creates_then_updates_without_duplicates(self):
    first = sync_positions(account=self.account, owner=self.hr, rows=[{
        "external_id": "job-101", "title": "实施工程师", "status": "open", "raw": "first"
    }])
    second = sync_positions(account=self.account, owner=self.hr, rows=[{
        "external_id": "job-101", "title": "高级实施工程师", "status": "open", "raw": "second"
    }])
    self.assertEqual(first.created, 1)
    self.assertEqual(second.updated, 1)
    self.assertEqual(RecruitmentJob.objects.filter(boss_account=self.account).count(), 1)
```

- [ ] **Step 2: Confirm RED**

```powershell
.\.venv\Scripts\python.exe .\backend\manage.py test recruitment.tests.test_position_sync --verbosity 2
```

- [ ] **Step 3: Implement transactional upsert**

Use `update_or_create(boss_account=account, external_id=row["external_id"])`. Preserve HR-owned fields (`department`, `owner`, `headcount`) on updates and update only BOSS-owned `title` and `status`. Return `SyncSummary(created, updated, unchanged, total)` and store it as the task result.

- [ ] **Step 4: Verify and commit**

```powershell
.\.venv\Scripts\python.exe .\backend\manage.py test recruitment --verbosity 2
git add backend/recruitment/rpa/sync.py backend/recruitment/worker_api.py backend/recruitment/tests/test_position_sync.py
git commit -m "feat: sync boss positions idempotently"
```

### Task 7: Build the automation workspace in Vue

**Files:**
- Create: `frontend/src/recruitmentAutomation.js`
- Create: `frontend/src/recruitmentAutomation.test.js`
- Create: `frontend/src/views/recruitment/RecruitmentAutomationView.vue`
- Create: `frontend/src/views/recruitment/RecruitmentAutomationView.test.js`
- Modify: `frontend/src/router.js`
- Modify: `frontend/src/styles.css`

- [ ] **Step 1: Write failing state-label tests**

```javascript
import { availableActions, loginStatusLabel } from './recruitmentAutomation'

test('requires human handling for token failures', () => {
  expect(loginStatusLabel('token_invalid')).toBe('登录二维码已失效，请重新打开登录浏览器')
})

test('never exposes outbound actions', () => {
  expect(availableActions({ active: true, has_active_task: false })).toEqual([
    'open_login', 'check_status', 'sync_positions',
  ])
})
```

- [ ] **Step 2: Confirm RED**

```powershell
Set-Location frontend
npm test -- --run src/recruitmentAutomation.test.js
```

- [ ] **Step 3: Implement pure UI policy helpers**

Define complete Chinese labels for `unknown`, `browser_stopped`, `waiting_login`, `waiting_human`, `ready`, `token_invalid`, `risk_control`, and `error`. `availableActions` returns only the three read-only/login actions and disables all actions while a task is active.

- [ ] **Step 4: Write the failing view test**

Mock API responses and verify the page renders Worker/CLI state, Chrome/Edge accounts, task history, and only the approved action menu. Assert that text such as `发送消息`, `打招呼`, and `采集候选人` does not appear.

- [ ] **Step 5: Implement the view**

The page loads:

```text
GET recruitment/automation/summary/
GET recruitment/boss-accounts/
GET recruitment/rpa-tasks/
```

Create tasks with:

```text
POST recruitment/rpa-tasks/
{ boss_account, action: "check_status", request_payload: { open_login: true|false } }
{ boss_account, action: "sync_positions" }
```

Use one understated account toolbar with an overflow menu, a status strip, account table, and task timeline drawer. The account modal asks only for name and Chrome/Edge; profile directory, executable, and port are server-generated and read-only.

- [ ] **Step 6: Route and style the page**

Replace the automation placeholder route with `RecruitmentAutomationView.vue`. Reuse `.panel`, `.data-table`, `.status-badge`, `.text-button`, and `ModalPanel`; add only focused `.automation-*` styles.

- [ ] **Step 7: Verify and commit**

```powershell
npm test -- --run
npm run build
git add src/recruitmentAutomation.js src/recruitmentAutomation.test.js src/views/recruitment/RecruitmentAutomationView.vue src/views/recruitment/RecruitmentAutomationView.test.js src/router.js src/styles.css
git commit -m "feat: add boss automation workspace"
```

### Task 8: Start and stop the Worker with the local system

**Files:**
- Modify: `scripts/start-local.ps1`
- Modify: `README.md`
- Create: `scripts/test-startup.ps1`

- [ ] **Step 1: Add a startup smoke test**

The script starts the service on temporary port `8768`, starts one Worker, waits for both HTTP health and Worker heartbeat, verifies there is exactly one Worker process, then stops only the processes it created in `finally`.

- [ ] **Step 2: Run the smoke test and confirm it fails before startup integration**

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\test-startup.ps1
```

- [ ] **Step 3: Lifecycle-manage the Worker**

In `start-local.ps1`, start the Worker with `Start-Process -WindowStyle Hidden -PassThru`, wait for Waitress as today, and stop the exact Worker PID in `finally`. Do not kill processes by name or broad command-line matching. Print separate `Web service` and `RPA Worker` health lines.

- [ ] **Step 4: Document setup and safety boundary**

Update README with CLI version detection, browser profile location, first manual login, the two allowed actions, and the fact that CAPTCHA/App confirmation is manual. Document that the 314 candidates and six resumes are never used.

- [ ] **Step 5: Verify and commit**

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\test-startup.ps1
git add scripts/start-local.ps1 scripts/test-startup.ps1 README.md
git commit -m "feat: launch boss rpa worker with hr system"
```

### Task 9: Full verification and real read-only acceptance

**Files:**
- Modify only if verification reveals a defect.

- [ ] **Step 1: Run all automated tests**

```powershell
.\.venv\Scripts\python.exe .\backend\manage.py test accounts attendance recruitment --verbosity 1
Set-Location frontend
npm test -- --run
npm run build
```

Expected: all backend and frontend tests pass and Vite exits `0`.

- [ ] **Step 2: Apply migrations and collect static assets**

```powershell
Set-Location ..
.\.venv\Scripts\python.exe .\backend\manage.py migrate
.\.venv\Scripts\python.exe .\backend\manage.py collectstatic --noinput
```

- [ ] **Step 3: Verify Chrome login without outbound activity**

Create one Chrome account, click “打开登录浏览器”, manually log in, then click “检查状态”. Expected: account becomes `READY`; no candidate or communication command is invoked.

- [ ] **Step 4: Verify Chrome position synchronization**

Run `SYNC_POSITIONS` once, compare count/names with the BOSS position page, then run it again. Expected: second run creates zero duplicates.

- [ ] **Step 5: Verify Edge isolation**

Create one Edge account. Confirm its executable, profile directory, and CDP port differ from Chrome. Complete manual login and the same read-only position sync.

- [ ] **Step 6: Verify recovery states**

Close the browser, occupy the configured port with a known temporary process, and test an expired login. Expected: `BROWSER_STOPPED`, `CDP_UNAVAILABLE`, or `WAITING_HUMAN` appears with no automatic loop or outbound action.

- [ ] **Step 7: Browser acceptance**

At `1440×900` and `1024×768`, verify account creation, action menu, task status refresh, event drawer, no console errors, and no outbound action labels.

- [ ] **Step 8: Final repository check**

```powershell
git status --short
git log --oneline -12
```

Expected: clean worktree; only purpose-specific commits; no CLI package, browser profile, Cookie, QR image, candidate export, or resume added to Git.
