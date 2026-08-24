# BOSS Candidate Discovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a safe BOSS candidate discovery pool with recommendation, keyword search, confirmed deep matching, structured local import, and deterministic duplicate detection.

**Architecture:** Django owns discovery records, identity quality, approval snapshots, quota enforcement, and import deduplication. The Windows Worker calls the installed `@joohw/boss-cli 0.6.6`, parses its text into normalized candidate rows, and returns them to a completion service that upserts the temporary pool. Vue 3 presents candidate-library and discovery tabs, scoped search controls, task progress, selectable cards, and a floating import bar; no external message is sent in this batch.

**Tech Stack:** Django 5, Django REST Framework, SQLite, Python subprocess, `@joohw/boss-cli 0.6.6`, Vue 3, Vitest.

---

### Task 1: Add discovery and external identity models

**Files:**
- Modify: `backend/recruitment/models.py`
- Create: `backend/recruitment/migrations/0007_candidate_discovery.py`
- Create: `backend/recruitment/tests/test_candidate_discovery_models.py`

- [ ] **Step 1: Write failing model tests**

```python
class CandidateDiscoveryModelTests(TestCase):
    def test_same_account_fingerprint_is_unique(self):
        CandidateDiscovery.objects.create(
            boss_account=self.account, job=self.job, source="recommend",
            fingerprint="f" * 64, display_name="林晓",
            expires_at=timezone.now() + timedelta(days=7),
        )
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                CandidateDiscovery.objects.create(
                    boss_account=self.account, job=self.job, source="search",
                    fingerprint="f" * 64, display_name="林晓",
                    expires_at=timezone.now() + timedelta(days=7),
                )

    def test_external_identity_cannot_bind_two_candidates(self):
        first = Candidate.objects.create(identity_key="boss:1:first", name="林晓")
        second = Candidate.objects.create(identity_key="boss:1:second", name="林晓")
        CandidateExternalIdentity.objects.create(
            boss_account=self.account, candidate=first,
            external_id="", fingerprint="e" * 64,
            identity_quality="fingerprint",
        )
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                CandidateExternalIdentity.objects.create(
                    boss_account=self.account, candidate=second,
                    external_id="", fingerprint="e" * 64,
                    identity_quality="fingerprint",
                )
```

- [ ] **Step 2: Run the tests and verify the models are missing**

Run: `.venv\Scripts\python.exe backend\manage.py test recruitment.tests.test_candidate_discovery_models`

Expected: FAIL because `CandidateDiscovery` and `CandidateExternalIdentity` do not exist.

- [ ] **Step 3: Add focused models**

Add `CandidateDiscovery` with UUID primary key, account/job/source, optional platform ID, deterministic fingerprint, display fields, JSON tags/source payload, search criteria, contact hint, identity quality, expiry, import target, and timestamps. Add `CandidateExternalIdentity` with account/candidate/platform ID/fingerprint/quality/last-seen timestamps. Use a unique `(boss_account, fingerprint)` constraint for both models; names are display data only and never identity keys.

```python
class CandidateDiscovery(models.Model):
    class Source(models.TextChoices):
        RECOMMEND = "recommend", "推荐候选人"
        SEARCH = "search", "常规搜索"
        DEEP_SEARCH = "deep_search", "深度搜索"

    class IdentityQuality(models.TextChoices):
        PLATFORM = "platform", "平台标识"
        FINGERPRINT = "fingerprint", "组合指纹"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    boss_account = models.ForeignKey(BossAccount, on_delete=models.CASCADE, related_name="candidate_discoveries")
    job = models.ForeignKey(RecruitmentJob, on_delete=models.CASCADE, related_name="candidate_discoveries")
    source = models.CharField(max_length=24, choices=Source.choices)
    external_id = models.CharField(max_length=160, blank=True)
    fingerprint = models.CharField(max_length=64)
    identity_quality = models.CharField(max_length=20, choices=IdentityQuality.choices)
    display_name = models.CharField(max_length=100)
    current_title = models.CharField(max_length=160, blank=True)
    city = models.CharField(max_length=80, blank=True)
    experience = models.CharField(max_length=160, blank=True)
    education = models.CharField(max_length=160, blank=True)
    advantage = models.TextField(blank=True)
    tags = models.JSONField(default=list, blank=True)
    criteria = models.JSONField(default=dict, blank=True)
    source_payload = models.JSONField(default=dict, blank=True)
    contact_hint = models.CharField(max_length=40, blank=True)
    imported_candidate = models.ForeignKey(Candidate, on_delete=models.SET_NULL, null=True, blank=True, related_name="discovery_sources")
    expires_at = models.DateTimeField()
    imported_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]
        constraints = [models.UniqueConstraint(fields=["boss_account", "job", "fingerprint"], name="unique_account_job_discovery_fingerprint")]
```

- [ ] **Step 4: Create the migration and run focused tests**

Run: `.venv\Scripts\python.exe backend\manage.py makemigrations recruitment`

Run: `.venv\Scripts\python.exe backend\manage.py test recruitment.tests.test_candidate_discovery_models`

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add backend/recruitment/models.py backend/recruitment/migrations/0007_candidate_discovery.py backend/recruitment/tests/test_candidate_discovery_models.py
git commit -m "feat: add candidate discovery identity models"
```

### Task 2: Parse candidate output and safely call BOSS CLI

**Files:**
- Modify: `backend/recruitment/rpa/cli.py`
- Create: `backend/recruitment/rpa/candidates.py`
- Create: `backend/recruitment/tests/test_candidate_cli.py`

- [ ] **Step 1: Write parser and command-contract tests**

```python
class CandidateCliTests(SimpleTestCase):
    def test_recommend_parser_keeps_structured_fields(self):
        rows = parse_candidate_output(RECOMMEND_OUTPUT, source="recommend")
        self.assertEqual(rows[0]["display_name"], "林晓")
        self.assertEqual(rows[0]["identity_quality"], "fingerprint")
        self.assertEqual(rows[0]["tags"], ["Vue", "ToB"])

    @patch("recruitment.rpa.cli.subprocess.run")
    def test_search_arguments_are_passed_without_shell(self, run):
        run.return_value = subprocess.CompletedProcess([], 0, SEARCH_OUTPUT.encode(), b"")
        BossCliRunner(cli_path="C:/tools/boss.cmd").search(self.account, "Vue")
        self.assertEqual(run.call_args.args[0], ["C:/tools/boss.cmd", "search", "Vue"])
        self.assertFalse(run.call_args.kwargs["shell"])

    def test_deep_search_requires_explicit_match_flag(self):
        args = deep_search_args(job="前端", core=["Vue 3"], bonus=["ToB"], match=True)
        self.assertEqual(args, ["deep-search", "--job", "前端", "--core", "Vue 3", "--bonus", "ToB", "--match"])
```

- [ ] **Step 2: Run tests and verify failure**

Run: `.venv\Scripts\python.exe backend\manage.py test recruitment.tests.test_candidate_cli`

Expected: FAIL because candidate parsing and runner methods are absent.

- [ ] **Step 3: Implement normalization and deterministic fingerprints**

Create `normalize_candidate_row(row, account_id, job_id)` and format-specific parsers for the actual 0.6.6 headings: `推荐列表`, `常规搜索结果`, and `本次新增推荐简历（最新20条）`. Hash a canonical JSON array of account, normalized name, title/meta, city, experience, education, and advantage when the CLI output does not expose a platform ID. Preserve raw parsed fields in `source_payload`; never infer phone or email.

```python
def candidate_fingerprint(*, account_id, row):
    stable = [account_id, row.get("external_id", ""), row["display_name"], row.get("current_title", ""), row.get("city", ""), row.get("experience", ""), row.get("education", ""), row.get("advantage", "")]
    return hashlib.sha256(json.dumps(stable, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()
```

- [ ] **Step 4: Expand the runner with an argument allowlist**

Change `_run` to accept a list, validate the first token against `{"--version", "login", "positions", "recommend", "search", "deep-search"}`, reject NUL/newline arguments, keep `shell=False`, and add `recommend`, `search`, and `deep_search` methods. Enforce the CLI limits: keyword at most 20 characters and core/bonus entries non-empty and at most 200 characters.

- [ ] **Step 5: Run CLI tests**

Run: `.venv\Scripts\python.exe backend\manage.py test recruitment.tests.test_boss_cli recruitment.tests.test_candidate_cli`

Expected: PASS.

- [ ] **Step 6: Commit**

```powershell
git add backend/recruitment/rpa/cli.py backend/recruitment/rpa/candidates.py backend/recruitment/tests/test_candidate_cli.py
git commit -m "feat: parse boss candidate discovery output"
```

### Task 3: Upsert discovery results and import selected candidates

**Files:**
- Create: `backend/recruitment/services/discovery.py`
- Create: `backend/recruitment/tests/test_discovery_service.py`

- [ ] **Step 1: Write failing service tests**

Cover: repeated sync updates one discovery row; exact account fingerprint imports only one `Candidate`; the same candidate/job creates one application; same names with different fingerprints stay separate; imported records retain source account identity; unauthorized IDs are rejected by the API layer rather than silently ignored.

```python
def test_same_name_different_fingerprint_stays_separate(self):
    first = self.discovery(fingerprint="a" * 64, display_name="林晓")
    second = self.discovery(fingerprint="b" * 64, display_name="林晓")
    result = import_discoveries(discoveries=[first, second], actor=self.hr)
    self.assertEqual(result.created_candidates, 2)
    self.assertEqual(Candidate.objects.filter(name="林晓").count(), 2)
```

- [ ] **Step 2: Run and verify failure**

Run: `.venv\Scripts\python.exe backend\manage.py test recruitment.tests.test_discovery_service`

Expected: FAIL because the service is absent.

- [ ] **Step 3: Implement atomic upsert and import services**

`sync_discoveries(account, job, source, criteria, rows)` validates required display names, normalizes list fields, sets a seven-day expiry, and `update_or_create`s by account/job/fingerprint. `import_discoveries(discoveries, actor)` locks rows, resolves the account-wide `CandidateExternalIdentity`, creates candidates with `boss:{account_id}:{external_id}` or `boss-fp:{account_id}:{fingerprint}`, creates `JobApplication(stage="new", source="boss")`, marks imported rows, and returns created/existing/application counts. Discovering the same person for a second job therefore creates a second pool entry and application while reusing the same candidate identity.

- [ ] **Step 4: Run service tests**

Run: `.venv\Scripts\python.exe backend\manage.py test recruitment.tests.test_discovery_service`

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add backend/recruitment/services/discovery.py backend/recruitment/tests/test_discovery_service.py
git commit -m "feat: sync and import candidate discoveries"
```

### Task 4: Enable discovery capabilities in the Worker

**Files:**
- Modify: `backend/recruitment/models.py`
- Modify: `backend/recruitment/migrations/0007_candidate_discovery.py`
- Modify: `backend/recruitment/rpa/capabilities.py`
- Modify: `backend/recruitment/management/commands/run_rpa_worker.py`
- Modify: `backend/recruitment/worker_api.py`
- Modify: `backend/recruitment/services/usage.py`
- Create: `backend/recruitment/tests/test_candidate_worker.py`

- [ ] **Step 1: Write failing Worker contract tests**

Assert `recommend_candidates` and `search_candidates` are enabled/read-only, `deep_match` is enabled/approval-required/consumes `deep_match`, leased tasks include validated `request_payload`, Worker dispatches the correct runner method, successful completion upserts discovery rows, and quota consumption blocks task creation past the configured limit.

- [ ] **Step 2: Run and verify failure**

Run: `.venv\Scripts\python.exe backend\manage.py test recruitment.tests.test_candidate_worker`

Expected: FAIL because discovery actions are not registered.

- [ ] **Step 3: Add actions and capability declarations**

Add `RECOMMEND_CANDIDATES` and `SEARCH_CANDIDATES` to `RpaTask.Action`; keep `DEEP_MATCH`. Register:

```python
"recommend_candidates": CapabilitySpec("recommend_candidates", "cli", True, False, enabled=True),
"search_candidates": CapabilitySpec("search_candidates", "cli", True, False, consumes="search", enabled=True),
"deep_match": CapabilitySpec("deep_match", "cli", False, True, consumes="deep_match", enabled=True),
```

- [ ] **Step 4: Execute and complete discovery tasks**

Lease responses include a copy of `request_payload`. Worker executors call runner methods and return `{candidates: [...]}`. On successful completion, `worker_api.complete_task_view` validates list shape, calls `sync_discoveries`, replaces raw rows with a compact sync summary, and marks the account ready. Consume configured search/deep-match quota when the task is created so retries cannot bypass limits; idempotent duplicate creation must not consume twice.

- [ ] **Step 5: Run Worker and regression tests**

Run: `.venv\Scripts\python.exe backend\manage.py test recruitment.tests.test_candidate_worker recruitment.tests.test_worker_api recruitment.tests.test_rpa_api recruitment.tests.test_automation_usage`

Expected: PASS.

- [ ] **Step 6: Commit**

```powershell
git add backend/recruitment/models.py backend/recruitment/migrations/0007_candidate_discovery.py backend/recruitment/rpa/capabilities.py backend/recruitment/management/commands/run_rpa_worker.py backend/recruitment/worker_api.py backend/recruitment/services/usage.py backend/recruitment/tests/test_candidate_worker.py
git commit -m "feat: run candidate discovery through boss worker"
```

### Task 5: Add discovery, approval, and import APIs

**Files:**
- Modify: `backend/recruitment/serializers.py`
- Modify: `backend/recruitment/views.py`
- Modify: `backend/recruitment/urls.py`
- Create: `backend/recruitment/tests/test_candidate_discovery_api.py`

- [ ] **Step 1: Write failing API tests**

Cover account authorization, job/account consistency, keyword and deep requirement validation, idempotent request IDs, deep match returning a draft confirmation before task creation, approval snapshot immutability, filtering discoveries by account/job/source/imported state, bulk import, and inability to import another HR's account discoveries.

- [ ] **Step 2: Run and verify failure**

Run: `.venv\Scripts\python.exe backend\manage.py test recruitment.tests.test_candidate_discovery_api`

Expected: FAIL with missing routes/serializers.

- [ ] **Step 3: Add API contracts**

Register a read-only `CandidateDiscoveryViewSet` with `POST search`, `POST prepare-deep-match`, and `POST import-selected`. Register `AutomationApprovalViewSet` with read/create and `POST approve`; scope both querysets to authorized accounts. `search` creates recommendation or keyword-search tasks. `prepare-deep-match` creates a draft snapshot containing account, job, core/bonus arrays, estimated consumption `1`, and request ID. `approve` uses `services.approvals.approve`, then creates the idempotent `deep_match` task from the immutable snapshot.

- [ ] **Step 4: Run API tests**

Run: `.venv\Scripts\python.exe backend\manage.py test recruitment.tests.test_candidate_discovery_api`

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add backend/recruitment/serializers.py backend/recruitment/views.py backend/recruitment/urls.py backend/recruitment/tests/test_candidate_discovery_api.py
git commit -m "feat: expose safe candidate discovery api"
```

### Task 6: Build the candidate discovery workspace

**Files:**
- Create: `frontend/src/candidateDiscovery.js`
- Create: `frontend/src/candidateDiscovery.test.js`
- Create: `frontend/src/components/CandidateDiscoveryCard.vue`
- Create: `frontend/src/components/CandidateDiscoveryCard.test.js`
- Create: `frontend/src/components/DeepMatchConfirmDrawer.vue`
- Modify: `frontend/src/views/recruitment/RecruitmentCandidatesView.vue`
- Modify: `frontend/src/views/recruitment/RecruitmentCandidatesView.test.js`

- [ ] **Step 1: Write failing frontend tests**

Test candidate-library/discovery tab switching, account/job/mode controls, keyword validation, recommendation and normal-search task creation, deep-match drawer content, task polling, card selection, floating batch bar, import summary, duplicate labels, and selection reset after import.

```javascript
it('imports checked discoveries and returns to the library', async () => {
  const wrapper = mount(RecruitmentCandidatesView)
  await flushPromises()
  await wrapper.get('[data-test="candidate-tab-discovery"]').trigger('click')
  await wrapper.get('[data-test="discovery-check-d1"]').setValue(true)
  expect(wrapper.get('[data-test="discovery-batch-bar"]').text()).toContain('已选择 1 人')
  await wrapper.get('[data-test="import-selected"]').trigger('click')
  await flushPromises()
  expect(apiMock).toHaveBeenCalledWith('recruitment/candidate-discoveries/import-selected/', expect.objectContaining({ method: 'POST' }))
})
```

- [ ] **Step 2: Run and verify failure**

Run: `npm test -- --run src/candidateDiscovery.test.js src/components/CandidateDiscoveryCard.test.js src/views/recruitment/RecruitmentCandidatesView.test.js`

Expected: FAIL because discovery UI is absent.

- [ ] **Step 3: Implement focused helpers and components**

`candidateDiscovery.js` owns discovery mode labels, request payload creation, terminal statuses, and safe task summaries. Cards use the local `AppIcon`, show identity quality and duplicate/import state, and make the checkbox the only bulk-selection affordance. The confirm drawer clearly states that deep matching consumes one match and sends no message.

- [ ] **Step 4: Integrate the discovery tab**

Keep the existing candidate table under “候选人库”. Add “发现候选人” with a compact filter strip and results grid. Poll tasks every 900 ms and stop on unmount. The floating batch bar uses a 220 ms entrance transition and only exposes “加入候选人库”; “加入并打招呼” remains disabled until the communication batch is implemented.

- [ ] **Step 5: Run focused frontend tests**

Run: `npm test -- --run src/candidateDiscovery.test.js src/components/CandidateDiscoveryCard.test.js src/views/recruitment/RecruitmentCandidatesView.test.js`

Expected: PASS.

- [ ] **Step 6: Commit**

```powershell
git add frontend/src/candidateDiscovery.js frontend/src/candidateDiscovery.test.js frontend/src/components/CandidateDiscoveryCard.vue frontend/src/components/CandidateDiscoveryCard.test.js frontend/src/components/DeepMatchConfirmDrawer.vue frontend/src/views/recruitment/RecruitmentCandidatesView.vue frontend/src/views/recruitment/RecruitmentCandidatesView.test.js
git commit -m "feat: add polished candidate discovery workspace"
```

### Task 7: Add responsive-safe desktop styling and final verification

**Files:**
- Modify: `frontend/src/styles.css`
- Modify: `README.md`

- [ ] **Step 1: Add desktop discovery styles**

Add restrained tabs, a low-contrast filter surface, two-column candidate cards on common desktop widths, teal hover/selection states, a fixed bottom selection bar within the content area, drawer transitions, skeleton loading, and `prefers-reduced-motion` overrides. Do not introduce mobile navigation or looped animation.

- [ ] **Step 2: Document the read-only boundary**

Update the README automation section: recommendation and normal search are read-only; deep match requires HR confirmation and consumes quota; importing writes only to the local database; no greeting or message is sent in this batch; fingerprint identities require target revalidation before future external actions.

- [ ] **Step 3: Run migration and backend verification**

Run: `.venv\Scripts\python.exe backend\manage.py makemigrations --check --dry-run`

Run: `.venv\Scripts\python.exe backend\manage.py test accounts attendance recruitment`

Expected: no migration drift and all tests pass.

- [ ] **Step 4: Run frontend verification and build**

Run: `npm test -- --run`

Run: `npm run build`

Expected: all Vitest files pass and Vite completes; the existing ECharts chunk-size warning is allowed.

- [ ] **Step 5: Run Windows startup smoke test**

Run: `powershell -NoProfile -ExecutionPolicy Bypass -File scripts\test-startup.ps1`

Expected: `Startup smoke test passed: web service and one RPA Worker are healthy.`

- [ ] **Step 6: Commit**

```powershell
git add frontend/src/styles.css README.md
git commit -m "docs: explain candidate discovery safety boundary"
```

- [ ] **Step 7: Verify the branch is clean**

Run: `git diff --check`

Run: `git status --short --branch`

Expected: no whitespace errors and no uncommitted files.
