# BOSS Automation Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the first independently testable slice of the confirmed BOSS recruitment automation design: durable approval/batch primitives, a capability registry, safe Playwright/CDP connectivity, and a polished one-click position synchronization flow.

**Architecture:** Keep Django responsible for business state, authorization, approvals, idempotency, and audit history. Keep the Windows worker responsible for browser and CLI execution behind a capability registry. This batch does not send candidate messages; it creates the safety foundation that later discovery, resume, and workflow plans will reuse.

**Tech Stack:** Django 5.2, Django REST Framework 3.16, SQLite, Python Playwright over CDP, existing `@joohw/boss-cli`, Vue 3, Vue Router, Vitest.

---

## Scope decomposition

The approved design spans four independently verifiable plans:

1. **This plan — automation foundation and position sync:** approvals, execution batches, evidence, capability registry, CDP adapter, and one-click sync UX.
2. **Candidate discovery plan:** recommendation, normal search, deep search, discovery pool, structured candidate import, and cross-account deduplication.
3. **Communication and resume plan:** greeting, resume request, attachment download, online resume PDF, interview invitation, and stage advancement.
4. **Workflow canvas plan:** controlled nodes, versioned workflows, cross-day waits, visual canvas, recovery, and final interaction polish.

Each plan must pass its own backend, frontend, migration, build, and Windows startup checks before the next plan begins.

## File map

- `backend/recruitment/models.py`: durable approval, batch, step, evidence, and account quota fields.
- `backend/recruitment/migrations/0004_automation_foundation.py`: schema migration generated from the models.
- `backend/recruitment/services/approvals.py`: approval lifecycle and immutable payload snapshots.
- `backend/recruitment/services/usage.py`: per-account daily usage checks and increments.
- `backend/recruitment/rpa/capabilities.py`: the only registry of worker actions and their safety properties.
- `backend/recruitment/rpa/playwright_adapter.py`: CDP connection and page inventory; no BOSS selectors in this batch.
- `backend/recruitment/rpa/tasks.py`: idempotent task creation and approval enforcement.
- `backend/recruitment/serializers.py`: account limits, sync request, approval, batch, and step API shapes.
- `backend/recruitment/views.py`: one-click sync and read-only execution history endpoints.
- `backend/recruitment/urls.py`: register the new API resources.
- `backend/recruitment/management/commands/run_rpa_worker.py`: report the capability registry through heartbeat.
- `backend/recruitment/tests/test_automation_models.py`: schema constraints and state defaults.
- `backend/recruitment/tests/test_approval_service.py`: approval snapshots, expiry, and permission behavior.
- `backend/recruitment/tests/test_capability_registry.py`: action policy and adapter selection.
- `backend/recruitment/tests/test_playwright_adapter.py`: mocked CDP connection behavior.
- `backend/recruitment/tests/test_position_sync_api.py`: one-click sync task and result contract.
- `frontend/src/recruitmentJobs.js`: sync state labels and summary formatting.
- `frontend/src/recruitmentJobs.test.js`: sync helper tests.
- `frontend/src/components/TaskProgressBar.vue`: reusable staged task progress.
- `frontend/src/components/TaskProgressBar.test.js`: progress rendering and reduced-motion behavior.
- `frontend/src/views/recruitment/RecruitmentJobsView.vue`: account picker, one-click sync, polling, result feedback.
- `frontend/src/views/recruitment/RecruitmentJobsView.test.js`: end-to-end component behavior.
- `frontend/src/styles.css`: restrained motion, floating feedback, hover, and reduced-motion rules.
- `backend/requirements.txt`: Python Playwright dependency.

### Task 1: Add automation safety models

**Files:**
- Modify: `backend/recruitment/models.py`
- Create: `backend/recruitment/migrations/0004_automation_foundation.py`
- Create: `backend/recruitment/tests/test_automation_models.py`

- [ ] **Step 1: Write failing model tests**

Create `backend/recruitment/tests/test_automation_models.py` with factories for an HR user and BOSS account, then assert the immutable relationships and defaults:

```python
from django.contrib.auth.models import User
from django.db import IntegrityError, transaction
from django.test import TestCase

from recruitment.models import (
    AutomationApproval,
    AutomationEvidence,
    BossAccount,
    ExecutionBatch,
    StepExecution,
)


class AutomationModelTests(TestCase):
    def setUp(self):
        self.hr = User.objects.create_user(username="foundation-hr")
        self.account = BossAccount.objects.create(
            name="foundation-account",
            browser_profile="boss-foundation",
            cdp_port=53480,
        )

    def test_approval_batch_and_step_defaults(self):
        approval = AutomationApproval.objects.create(
            action=AutomationApproval.Action.SYNC_POSITIONS,
            boss_account=self.account,
            created_by=self.hr,
            payload={"account_id": self.account.id},
            item_count=1,
        )
        batch = ExecutionBatch.objects.create(
            approval=approval,
            boss_account=self.account,
            action=approval.action,
            idempotency_key="sync:foundation:1",
            created_by=self.hr,
        )
        step = StepExecution.objects.create(batch=batch, target_key="account")

        self.assertEqual(approval.status, "draft")
        self.assertEqual(batch.status, "pending")
        self.assertEqual(step.status, "pending")

    def test_batch_idempotency_key_is_unique(self):
        first = ExecutionBatch.objects.create(
            boss_account=self.account,
            action="sync_positions",
            idempotency_key="same-key",
            created_by=self.hr,
        )
        self.assertIsNotNone(first.pk)
        with self.assertRaises(IntegrityError), transaction.atomic():
            ExecutionBatch.objects.create(
                boss_account=self.account,
                action="sync_positions",
                idempotency_key="same-key",
                created_by=self.hr,
            )

    def test_evidence_never_requires_sensitive_browser_data(self):
        batch = ExecutionBatch.objects.create(
            boss_account=self.account,
            action="sync_positions",
            idempotency_key="evidence-key",
            created_by=self.hr,
        )
        step = StepExecution.objects.create(batch=batch, target_key="account")
        evidence = AutomationEvidence.objects.create(
            step=step,
            kind="page_state",
            summary="职位列表已读取",
            metadata={"url_path": "/web/chat/job/list"},
        )
        self.assertEqual(evidence.file.name, "")
```

- [ ] **Step 2: Run the new tests and verify they fail**

Run:

```powershell
..\.venv\Scripts\python.exe manage.py test recruitment.tests.test_automation_models -v 2
```

Expected: import failure because the four automation models do not exist.

- [ ] **Step 3: Add the models and account limits**

Append focused models to `backend/recruitment/models.py`. Use these exact states and relationships:

```python
class AutomationApproval(models.Model):
    class Action(models.TextChoices):
        SYNC_POSITIONS = "sync_positions", "同步职位"
        GREET = "greet", "打招呼"
        REQUEST_RESUME = "request_resume", "索要简历"
        VIEW_ONLINE_RESUME = "view_online_resume", "查看在线简历"
        SEND_INTERVIEW = "send_interview", "发送面试邀约"
        DEEP_MATCH = "deep_match", "深度匹配"

    class Status(models.TextChoices):
        DRAFT = "draft", "待确认"
        APPROVED = "approved", "已确认"
        REJECTED = "rejected", "已拒绝"
        EXPIRED = "expired", "已过期"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    action = models.CharField(max_length=40, choices=Action.choices)
    boss_account = models.ForeignKey(BossAccount, on_delete=models.PROTECT, related_name="automation_approvals")
    created_by = models.ForeignKey(User, on_delete=models.PROTECT, related_name="created_automation_approvals")
    approved_by = models.ForeignKey(User, on_delete=models.PROTECT, null=True, blank=True, related_name="approved_automation_approvals")
    payload = models.JSONField(default=dict)
    item_count = models.PositiveIntegerField(default=1)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.DRAFT)
    expires_at = models.DateTimeField(null=True, blank=True)
    approved_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)


class ExecutionBatch(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "待执行"
        RUNNING = "running", "执行中"
        WAITING_HUMAN = "waiting_human", "等待人工"
        PARTIAL = "partial", "部分完成"
        SUCCEEDED = "succeeded", "成功"
        FAILED = "failed", "失败"
        CANCELLED = "cancelled", "已取消"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    approval = models.OneToOneField(AutomationApproval, on_delete=models.PROTECT, null=True, blank=True, related_name="batch")
    boss_account = models.ForeignKey(BossAccount, on_delete=models.PROTECT, related_name="execution_batches")
    action = models.CharField(max_length=40)
    status = models.CharField(max_length=24, choices=Status.choices, default=Status.PENDING)
    idempotency_key = models.CharField(max_length=160, unique=True)
    created_by = models.ForeignKey(User, on_delete=models.PROTECT, related_name="created_execution_batches")
    total_items = models.PositiveIntegerField(default=1)
    succeeded_items = models.PositiveIntegerField(default=0)
    failed_items = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)


class StepExecution(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "待执行"
        LEASED = "leased", "已领取"
        RUNNING = "running", "执行中"
        VERIFYING = "verifying", "核验中"
        WAITING_HUMAN = "waiting_human", "等待人工"
        SUCCEEDED = "succeeded", "成功"
        FAILED = "failed", "失败"
        SKIPPED = "skipped", "已跳过"
        CANCELLED = "cancelled", "已取消"

    batch = models.ForeignKey(ExecutionBatch, on_delete=models.CASCADE, related_name="steps")
    target_key = models.CharField(max_length=160)
    target_payload = models.JSONField(default=dict, blank=True)
    status = models.CharField(max_length=24, choices=Status.choices, default=Status.PENDING)
    attempt = models.PositiveSmallIntegerField(default=0)
    result = models.JSONField(default=dict, blank=True)
    error_code = models.CharField(max_length=64, blank=True)
    error_message = models.TextField(blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["batch", "target_key"], name="unique_batch_target")]


class AutomationEvidence(models.Model):
    step = models.ForeignKey(StepExecution, on_delete=models.CASCADE, related_name="evidence")
    kind = models.CharField(max_length=32)
    summary = models.CharField(max_length=300)
    metadata = models.JSONField(default=dict, blank=True)
    file = models.FileField(upload_to="recruitment/evidence/%Y/%m", blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
```

Add these fields to `BossAccount`:

```python
daily_search_limit = models.PositiveIntegerField(default=100)
daily_resume_view_limit = models.PositiveIntegerField(default=20)
daily_message_limit = models.PositiveIntegerField(default=50)
```

- [ ] **Step 4: Generate and inspect the migration**

Run:

```powershell
..\.venv\Scripts\python.exe manage.py makemigrations recruitment --name automation_foundation
..\.venv\Scripts\python.exe manage.py sqlmigrate recruitment 0004
```

Expected: migration `0004_automation_foundation.py` creates four tables, one unique batch key, one unique batch/target constraint, and three account limit columns. Confirm it contains no deletion or rename operation.

- [ ] **Step 5: Run model tests and migration checks**

Run:

```powershell
..\.venv\Scripts\python.exe manage.py test recruitment.tests.test_automation_models -v 2
..\.venv\Scripts\python.exe manage.py makemigrations --check --dry-run
```

Expected: tests pass and Django prints `No changes detected`.

- [ ] **Step 6: Commit the schema**

```powershell
git add backend/recruitment/models.py backend/recruitment/migrations/0004_automation_foundation.py backend/recruitment/tests/test_automation_models.py
git commit -m "feat: add recruitment automation execution models"
```

### Task 2: Implement approval snapshots and daily usage policy

**Files:**
- Create: `backend/recruitment/services/__init__.py`
- Create: `backend/recruitment/services/approvals.py`
- Create: `backend/recruitment/services/usage.py`
- Create: `backend/recruitment/tests/test_approval_service.py`
- Modify: `backend/recruitment/models.py`
- Create: `backend/recruitment/migrations/0005_automation_usage.py`

- [ ] **Step 1: Write failing approval and usage tests**

Create tests that assert approval payloads are copied, expired approvals fail, and daily limits cannot be exceeded:

```python
from datetime import timedelta

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from recruitment.models import AutomationApproval, AutomationUsage, BossAccount
from recruitment.services.approvals import approve
from recruitment.services.usage import consume


class ApprovalServiceTests(TestCase):
    def setUp(self):
        self.hr = User.objects.create_user(username="approval-hr")
        self.account = BossAccount.objects.create(name="approval-account", browser_profile="approval-profile", cdp_port=53481)
        self.account.authorized_users.add(self.hr)

    def test_approve_keeps_an_immutable_payload_snapshot(self):
        source = {"text": "您好", "candidate_ids": [1, 2]}
        approval = AutomationApproval.objects.create(
            action="greet", boss_account=self.account, created_by=self.hr, payload=source, item_count=2
        )
        approve(approval=approval, actor=self.hr)
        source["text"] = "changed"
        approval.refresh_from_db()
        self.assertEqual(approval.payload["text"], "您好")
        self.assertEqual(approval.status, "approved")

    def test_expired_approval_cannot_be_approved(self):
        approval = AutomationApproval.objects.create(
            action="greet",
            boss_account=self.account,
            created_by=self.hr,
            payload={},
            expires_at=timezone.now() - timedelta(seconds=1),
        )
        with self.assertRaises(ValidationError):
            approve(approval=approval, actor=self.hr)

    def test_daily_limit_is_atomic(self):
        self.account.daily_message_limit = 2
        self.account.save(update_fields=["daily_message_limit"])
        consume(account=self.account, metric=AutomationUsage.Metric.MESSAGE, amount=2)
        with self.assertRaises(ValidationError):
            consume(account=self.account, metric=AutomationUsage.Metric.MESSAGE, amount=1)
```

- [ ] **Step 2: Run the test and verify missing services/models**

Run:

```powershell
..\.venv\Scripts\python.exe manage.py test recruitment.tests.test_approval_service -v 2
```

Expected: import errors for `AutomationUsage`, `approve`, and `consume`.

- [ ] **Step 3: Add `AutomationUsage` and services**

Add the daily usage model:

```python
class AutomationUsage(models.Model):
    class Metric(models.TextChoices):
        SEARCH = "search", "候选人搜索"
        DEEP_MATCH = "deep_match", "深度匹配"
        RESUME_VIEW = "resume_view", "在线简历查看"
        CONTACT = "contact", "打招呼"
        MESSAGE = "message", "发送消息"

    boss_account = models.ForeignKey(BossAccount, on_delete=models.CASCADE, related_name="automation_usage")
    day = models.DateField()
    metric = models.CharField(max_length=24, choices=Metric.choices)
    used = models.PositiveIntegerField(default=0)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["boss_account", "day", "metric"], name="unique_daily_automation_usage")]
```

Implement `approve()` with `transaction.atomic()`, `select_for_update()`, authorized-user validation, expiry validation, status transition to `approved`, `approved_by`, and `approved_at`. Implement `consume()` with `select_for_update().get_or_create()`, mapping metrics to the three account limit fields; map both `contact` and `message` to their explicit limits and reject `used + amount > limit`. Do not silently clamp values.

- [ ] **Step 4: Generate migration and run tests**

Run:

```powershell
..\.venv\Scripts\python.exe manage.py makemigrations recruitment --name automation_usage
..\.venv\Scripts\python.exe manage.py test recruitment.tests.test_approval_service -v 2
..\.venv\Scripts\python.exe manage.py makemigrations --check --dry-run
```

Expected: all approval tests pass and no model changes remain.

- [ ] **Step 5: Commit policy services**

```powershell
git add backend/recruitment/models.py backend/recruitment/migrations/0005_automation_usage.py backend/recruitment/services backend/recruitment/tests/test_approval_service.py
git commit -m "feat: enforce automation approvals and daily limits"
```

### Task 3: Add the capability registry and safe CDP adapter

**Files:**
- Modify: `backend/requirements.txt`
- Create: `backend/recruitment/rpa/capabilities.py`
- Create: `backend/recruitment/rpa/playwright_adapter.py`
- Modify: `backend/recruitment/management/commands/run_rpa_worker.py`
- Create: `backend/recruitment/tests/test_capability_registry.py`
- Create: `backend/recruitment/tests/test_playwright_adapter.py`

- [ ] **Step 1: Write failing capability tests**

```python
from django.test import SimpleTestCase

from recruitment.rpa.capabilities import REGISTRY, capability_payload


class CapabilityRegistryTests(SimpleTestCase):
    def test_sync_positions_is_read_only_and_cli_backed(self):
        spec = REGISTRY["sync_positions"]
        self.assertTrue(spec.read_only)
        self.assertFalse(spec.requires_approval)
        self.assertEqual(spec.adapter, "cli")

    def test_future_write_actions_are_declared_but_disabled(self):
        spec = REGISTRY["greet"]
        self.assertFalse(spec.enabled)
        self.assertTrue(spec.requires_approval)

    def test_heartbeat_payload_is_json_safe(self):
        payload = capability_payload()
        self.assertEqual(payload["sync_positions"]["adapter"], "cli")
```

Add a mocked Playwright test:

```python
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from recruitment.rpa.playwright_adapter import BrowserInventory


class PlaywrightAdapterTests(SimpleTestCase):
    @patch("recruitment.rpa.playwright_adapter.sync_playwright")
    def test_inventory_connects_to_loopback_cdp_only(self, sync_playwright):
        page = MagicMock(url="https://www.zhipin.com/web/chat/job/list")
        page.title.return_value = "职位管理"
        browser = MagicMock(contexts=[MagicMock(pages=[page])])
        sync_playwright.return_value.__enter__.return_value.chromium.connect_over_cdp.return_value = browser

        rows = BrowserInventory(53470).pages()

        self.assertEqual(rows[0]["title"], "职位管理")
        sync_playwright.return_value.__enter__.return_value.chromium.connect_over_cdp.assert_called_once_with(
            "http://127.0.0.1:53470"
        )
        browser.close.assert_not_called()
        sync_playwright.return_value.__exit__.assert_called_once()
```

- [ ] **Step 2: Run tests and verify missing modules**

Run:

```powershell
..\.venv\Scripts\python.exe manage.py test recruitment.tests.test_capability_registry recruitment.tests.test_playwright_adapter -v 2
```

Expected: import failures for both new modules.

- [ ] **Step 3: Add Playwright and the registry**

Add `playwright>=1.54,<2` to `backend/requirements.txt`. Do not add `playwright install` to any setup script, because the adapter connects to the already installed Edge/Chrome over CDP.

Create a frozen `CapabilitySpec` dataclass with fields `name`, `adapter`, `read_only`, `requires_approval`, `consumes`, and `enabled`. Register `check_status` and `sync_positions` as enabled; register the approved future actions as disabled so the UI and worker cannot execute them prematurely.

Implement `BrowserInventory` so its constructor accepts only ports from `53470..53569`, connects to `http://127.0.0.1:<port>`, and returns `[{"url": page.url, "title": page.title()}]`. Exit the Playwright driver context to disconnect, but never call `browser.close()` on a browser attached through CDP because that can close the HR's persistent isolated browser.

- [ ] **Step 4: Report registry capabilities in worker heartbeat**

Replace the existing `{"boss_cli": True}` heartbeat capability with:

```python
heartbeat = {
    "hostname": socket.gethostname(),
    "version": version,
    "capabilities": {
        "boss_cli": True,
        "actions": capability_payload(),
    },
}
```

Keep the existing executor whitelist as the final enforcement layer.

- [ ] **Step 5: Install, test, and commit**

Run:

```powershell
..\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt
..\.venv\Scripts\python.exe manage.py test recruitment.tests.test_capability_registry recruitment.tests.test_playwright_adapter recruitment.tests.test_worker_command -v 2
```

Expected: all listed tests pass without downloading Chromium.

```powershell
git add backend/requirements.txt backend/recruitment/rpa/capabilities.py backend/recruitment/rpa/playwright_adapter.py backend/recruitment/management/commands/run_rpa_worker.py backend/recruitment/tests/test_capability_registry.py backend/recruitment/tests/test_playwright_adapter.py
git commit -m "feat: register safe boss automation capabilities"
```

### Task 4: Make task creation idempotent and approval-aware

**Files:**
- Modify: `backend/recruitment/models.py`
- Create: `backend/recruitment/migrations/0006_rpa_task_safety.py`
- Modify: `backend/recruitment/rpa/tasks.py`
- Modify: `backend/recruitment/serializers.py`
- Modify: `backend/recruitment/tests/test_rpa_api.py`

- [ ] **Step 1: Add failing API tests**

Add tests proving repeated client requests return the same task and future write actions require an approved record:

```python
def test_idempotency_key_returns_the_existing_task(self):
    self.client.force_login(self.hr)
    body = {"boss_account": self.account.id, "action": "sync_positions", "idempotency_key": "sync-click-1"}
    first = self.client.post("/api/recruitment/rpa-tasks/", body, format="json")
    second = self.client.post("/api/recruitment/rpa-tasks/", body, format="json")
    self.assertEqual(first.status_code, 201)
    self.assertEqual(second.status_code, 200)
    self.assertEqual(first.data["id"], second.data["id"])

def test_disabled_write_action_is_rejected_even_with_payload(self):
    response = self.create_task(action="greet", payload={"candidate_ids": [1]})
    self.assertEqual(response.status_code, 400)
    self.assertIn("尚未开放", str(response.data))
```

- [ ] **Step 2: Run the targeted tests and verify failure**

Run:

```powershell
..\.venv\Scripts\python.exe manage.py test recruitment.tests.test_rpa_api -v 2
```

Expected: idempotency field/response behavior is missing.

- [ ] **Step 3: Extend `RpaTask` and task creation**

Add nullable `approval`, nullable `execution_batch`, and blank nullable unique `idempotency_key` fields to `RpaTask`. Generate migration `0006_rpa_task_safety.py`.

Update `create_task()` to:

1. Load the capability from `REGISTRY` and reject unknown or disabled actions.
2. Require an approved, unexpired `AutomationApproval` when `requires_approval` is true.
3. Return the existing authorized task when the same non-empty idempotency key exists.
4. Preserve the existing one-active-task-per-account rule.
5. Record capability name, adapter, approval id, and idempotency key in the audit detail.

Use this compatible signature so existing callers continue receiving a task while the sync endpoint can obtain the created flag:

```python
def create_task(
    *, account, action, actor, request_payload=None, approval=None,
    idempotency_key="", return_created=False,
):
    # validation and transactional creation
    return (task, created) if return_created else task
```

Extend `RpaTask.Action` with `greet`, `request_resume`, `view_online_resume`, `send_interview`, and `deep_match`. They remain disabled in `REGISTRY`, so serializers can return the explicit “尚未开放” policy error instead of treating them as malformed input.

Update `RpaTaskSerializer` to accept `approval` and `idempotency_key`, expose both fields, and return HTTP 200 for an existing idempotent task by setting `serializer.instance._was_existing = True`; override `RpaTaskViewSet.create()` to select 200 or 201 from that marker.

- [ ] **Step 4: Run task, worker, and migration tests**

Run:

```powershell
..\.venv\Scripts\python.exe manage.py test recruitment.tests.test_rpa_api recruitment.tests.test_worker_api recruitment.tests.test_worker_command -v 2
..\.venv\Scripts\python.exe manage.py makemigrations --check --dry-run
```

Expected: all tests pass and no migration drift exists.

- [ ] **Step 5: Commit task safety**

```powershell
git add backend/recruitment/models.py backend/recruitment/migrations/0006_rpa_task_safety.py backend/recruitment/rpa/tasks.py backend/recruitment/serializers.py backend/recruitment/views.py backend/recruitment/tests/test_rpa_api.py
git commit -m "feat: make boss tasks approval aware and idempotent"
```

### Task 5: Add one-click position sync API with result history

**Files:**
- Modify: `backend/recruitment/serializers.py`
- Modify: `backend/recruitment/views.py`
- Modify: `backend/recruitment/urls.py`
- Create: `backend/recruitment/tests/test_position_sync_api.py`

- [ ] **Step 1: Write failing endpoint tests**

```python
from django.contrib.auth.models import User
from rest_framework.test import APITestCase

from attendance.models import AccountProfile
from recruitment.models import BossAccount, RpaTask


class PositionSyncApiTests(APITestCase):
    def setUp(self):
        self.hr = User.objects.create_user(username="sync-api-hr")
        AccountProfile.objects.create(user=self.hr, role=AccountProfile.Role.HR)
        self.account = BossAccount.objects.create(name="sync-api", browser_profile="sync-api", cdp_port=53482)
        self.account.authorized_users.add(self.hr)
        self.client.force_login(self.hr)

    def test_one_click_sync_creates_an_idempotent_task(self):
        response = self.client.post(
            "/api/recruitment/jobs/sync/",
            {"boss_account": self.account.id, "request_id": "11111111-1111-4111-8111-111111111111"},
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.data)
        task = RpaTask.objects.get(pk=response.data["task_id"])
        self.assertEqual(task.action, "sync_positions")
        self.assertEqual(task.idempotency_key, f"position-sync:{self.account.id}:11111111-1111-4111-8111-111111111111")

    def test_unassigned_account_is_rejected(self):
        other = BossAccount.objects.create(name="other-sync", browser_profile="other-sync", cdp_port=53483)
        response = self.client.post(
            "/api/recruitment/jobs/sync/",
            {"boss_account": other.id, "request_id": "22222222-2222-4222-8222-222222222222"},
            format="json",
        )
        self.assertEqual(response.status_code, 403)
```

- [ ] **Step 2: Run the endpoint tests and verify 404**

Run:

```powershell
..\.venv\Scripts\python.exe manage.py test recruitment.tests.test_position_sync_api -v 2
```

Expected: `/api/recruitment/jobs/sync/` returns 404.

- [ ] **Step 3: Implement the sync action**

Add `PositionSyncRequestSerializer` with `boss_account` as a queryset, `request_id = serializers.UUIDField()`, and `validate_boss_account()` that raises `PermissionDenied("无权操作该 BOSS 账号")` unless the requester is a superuser or is present in `authorized_users`.

Add this collection action to `RecruitmentJobViewSet`:

```python
@action(detail=False, methods=["post"], url_path="sync")
def sync(self, request):
    serializer = PositionSyncRequestSerializer(data=request.data, context={"request": request})
    serializer.is_valid(raise_exception=True)
    account = serializer.validated_data["boss_account"]
    request_id = serializer.validated_data["request_id"]
    task, created = create_task(
        account=account,
        action=RpaTask.Action.SYNC_POSITIONS,
        actor=request.user,
        idempotency_key=f"position-sync:{account.pk}:{request_id}",
        return_created=True,
    )
    return Response(
        {"task_id": str(task.pk), "status": task.status},
        status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
    )
```

Do not add a second URL entry; the router exposes the collection action.

- [ ] **Step 4: Run endpoint and existing position sync tests**

Run:

```powershell
..\.venv\Scripts\python.exe manage.py test recruitment.tests.test_position_sync_api recruitment.tests.test_position_sync recruitment.tests.test_rpa_api -v 2
```

Expected: all tests pass.

- [ ] **Step 5: Commit the endpoint**

```powershell
git add backend/recruitment/serializers.py backend/recruitment/views.py backend/recruitment/tests/test_position_sync_api.py
git commit -m "feat: add one-click boss position sync api"
```

### Task 6: Build the polished position sync interaction

**Files:**
- Create: `frontend/src/recruitmentJobs.js`
- Create: `frontend/src/recruitmentJobs.test.js`
- Create: `frontend/src/components/TaskProgressBar.vue`
- Create: `frontend/src/components/TaskProgressBar.test.js`
- Modify: `frontend/src/views/recruitment/RecruitmentJobsView.vue`
- Modify: `frontend/src/views/recruitment/RecruitmentJobsView.test.js`
- Modify: `frontend/src/styles.css`

- [ ] **Step 1: Write helper and component tests first**

Test summary formatting:

```javascript
import { describe, expect, it } from 'vitest'
import { positionSyncSummary, taskProgress } from './recruitmentJobs'

describe('recruitment job sync helpers', () => {
  it('formats persisted sync counts', () => {
    expect(positionSyncSummary({ sync: { created: 2, updated: 1, unchanged: 4, total: 7 } }))
      .toBe('新增 2 · 更新 1 · 未变化 4 · 共 7 个职位')
  })

  it('maps worker states to stable progress', () => {
    expect(taskProgress('pending')).toEqual({ label: '等待执行', percent: 12 })
    expect(taskProgress('running')).toEqual({ label: '正在读取 BOSS 职位', percent: 62 })
    expect(taskProgress('succeeded')).toEqual({ label: '同步完成', percent: 100 })
  })
})
```

Test `TaskProgressBar` with `status="running"`, assert `role="progressbar"`, `aria-valuenow="62"`, the visible label, and the absence of a looping animation class when `reducedMotion` is true.

Extend `RecruitmentJobsView.test.js` so the API mock supports:

```javascript
if (path === 'recruitment/boss-accounts/') return Promise.resolve({ results: [{ id: 8, name: '北京账号', login_status: 'ready' }] })
if (path === 'recruitment/jobs/sync/') return Promise.resolve({ task_id: 'task-1', status: 'pending' })
if (path === 'recruitment/rpa-tasks/task-1/') return Promise.resolve({ id: 'task-1', status: 'succeeded', result: { sync: { created: 2, updated: 1, unchanged: 4, total: 7 } } })
```

Assert that selecting account 8 and clicking `data-test="sync-positions"` posts a UUID request id, renders progress, reloads jobs, and displays the formatted result.

- [ ] **Step 2: Run frontend tests and verify failure**

Run:

```powershell
npm test -- src/recruitmentJobs.test.js src/components/TaskProgressBar.test.js src/views/recruitment/RecruitmentJobsView.test.js
```

Expected: missing modules/components and missing sync control failures.

- [ ] **Step 3: Implement helpers and progress component**

`recruitmentJobs.js` must export fixed status mappings and return `null` when no valid sync result exists. `TaskProgressBar.vue` accepts `status` and `reducedMotion`, renders an accessible progressbar, and uses a single inner transform for progress.

- [ ] **Step 4: Implement one-click sync in the jobs view**

On mount, load jobs and authorized BOSS accounts in parallel. Add a compact account select and one primary text-style “同步职位” control beside the existing demo menu. Generate `crypto.randomUUID()` for each user click, POST to `recruitment/jobs/sync/`, and poll `recruitment/rpa-tasks/<id>/` every 900ms until `succeeded`, `failed`, or `waiting_human`.

Requirements:

- disable the control while a task is active;
- clear the poll timer in `onUnmounted`;
- on success, reload jobs and show the count summary;
- on `waiting_human`, show “需要在隔离浏览器中完成验证”；
- on failure, show `error_message` without discarding the task id;
- do not start a background schedule after completion.

- [ ] **Step 5: Add restrained motion and reduced-motion styles**

Add these interaction rules to `styles.css` using existing color variables:

```css
.job-sync-feedback { transition: opacity 180ms ease, transform 220ms cubic-bezier(.2,.8,.2,1); }
.job-sync-feedback-enter-from { opacity: 0; transform: translateY(-6px); }
.task-progress__bar { transition: transform 260ms cubic-bezier(.2,.8,.2,1); transform-origin: left; }
.recruitment-row { transition: background-color 140ms ease, transform 160ms ease, box-shadow 160ms ease; }
.recruitment-row:hover { transform: translateY(-1px); }
@media (prefers-reduced-motion: reduce) {
  .job-sync-feedback, .task-progress__bar, .recruitment-row { transition-duration: 1ms; }
  .recruitment-row:hover { transform: none; }
}
```

- [ ] **Step 6: Run focused tests and build**

Run:

```powershell
npm test -- src/recruitmentJobs.test.js src/components/TaskProgressBar.test.js src/views/recruitment/RecruitmentJobsView.test.js
npm run build
```

Expected: focused tests pass and Vite builds `backend/frontend_dist` successfully.

- [ ] **Step 7: Commit the UI slice**

```powershell
git add frontend/src/recruitmentJobs.js frontend/src/recruitmentJobs.test.js frontend/src/components/TaskProgressBar.vue frontend/src/components/TaskProgressBar.test.js frontend/src/views/recruitment/RecruitmentJobsView.vue frontend/src/views/recruitment/RecruitmentJobsView.test.js frontend/src/styles.css
git commit -m "feat: add polished one-click position sync"
```

### Task 7: Run the complete foundation acceptance gate

**Files:**
- Modify only if verification reveals a defect in files owned by Tasks 1–6.

- [ ] **Step 1: Run all backend tests**

```powershell
..\.venv\Scripts\python.exe manage.py test -v 2
```

Expected: all Django tests pass with no errors or failures.

- [ ] **Step 2: Run all frontend tests and production build**

```powershell
npm test
npm run build
```

Expected: all Vitest files pass and Vite production build succeeds. The existing ECharts large-chunk warning is allowed; new warnings are not.

- [ ] **Step 3: Verify migrations and static publication**

```powershell
..\.venv\Scripts\python.exe manage.py makemigrations --check --dry-run
..\.venv\Scripts\python.exe manage.py migrate --plan
..\.venv\Scripts\python.exe manage.py collectstatic --noinput
git diff --check
```

Expected: no migration drift, only the expected recruitment migrations in the plan, collectstatic succeeds, and `git diff --check` is silent.

- [ ] **Step 4: Run the Windows startup smoke test**

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\test-startup.ps1
```

Expected: web service and RPA worker both start, CSRF endpoint returns HTTP 200, and the test stops only the processes it created.

- [ ] **Step 5: Perform read-only browser acceptance**

Start the application with `scripts\start-local.ps1`, sign in, open “招聘管理 → 职位管理”, choose an already logged-in test BOSS account, and click “同步职位”. Verify the staged progress feedback, final counts, refreshed rows, hover/transition behavior, and task history. Do not load demo data and do not execute candidate write actions.

- [ ] **Step 6: Commit verification fixes if any**

If no files changed, do not create an empty commit. If a defect was fixed, rerun the failing gate, stage only the exact Task 1–6 files reported by `git status --short`, and commit with message `fix: complete automation foundation acceptance`.

## Completion criteria

This plan is complete only when:

- the new schema migrates cleanly on a copy of the current local database;
- approval, batch, step, evidence, usage, and idempotency tests pass;
- the worker heartbeat exposes enabled and disabled capabilities accurately;
- Playwright connects only to the configured loopback CDP port and does not download or launch another browser;
- the position page creates exactly one task per click, reports progress, displays persisted sync counts, and never schedules background synchronization;
- all existing recruitment, attendance, authentication, frontend, build, collectstatic, and Windows startup checks remain green.
