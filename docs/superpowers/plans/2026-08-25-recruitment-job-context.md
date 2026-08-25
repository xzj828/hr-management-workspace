# Recruitment Job Context Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Separate global recruitment operations from a persistent, secure single-job workspace for candidates, pipeline, and resumes.

**Architecture:** A Pinia recruitment-context store owns the accessible open-job list, URL synchronization, and per-user persistence. Scoped pages require `?job=<id>` and send it to Django endpoints; Django validates both job state and user access and filters applications and resumes at the database boundary. The recruitment dashboard remains global and provides job-card drill-down into the scoped workspace.

**Tech Stack:** Vue 3.5, Vue Router 4.5, Pinia 3, Vitest/Vue Test Utils, Django 5.2, Django REST Framework 3.16, Django TestCase/APITestCase.

---

## File map

- Create `frontend/src/stores/recruitmentContext.js`: open-job loading, URL selection, per-user persistence, invalidation.
- Create `frontend/src/stores/recruitmentContext.test.js`: store behavior and stale-response coverage.
- Create `frontend/src/components/RecruitmentJobContext.vue`: top-bar selector/global-view indicator.
- Create `frontend/src/components/RecruitmentJobContext.test.js`: selector and global-page interaction tests.
- Modify `frontend/src/components/AppLayout.vue`: mount context component and preserve `job` across scoped navigation.
- Modify `frontend/src/components/AppLayout.test.js`: header routing and context tests.
- Modify `frontend/src/router.js`: mark scoped/global recruitment routes in route metadata.
- Modify `backend/recruitment/views.py`: accessible-job helper, status filter, application access control, candidate prefetch scoping, resume job filter.
- Create `backend/recruitment/services/access.py`: reusable authorized-job queryset for views and serializers.
- Modify `backend/recruitment/models.py`: add recoverable JobApplication archival state.
- Create `backend/recruitment/migrations/0015_jobapplication_archived_at.py`: persist JobApplication archival state.
- Modify `backend/recruitment/serializers.py`: application-centric candidate rows and safe related-application output.
- Modify `backend/recruitment/services/dashboard.py`: actionable per-job progress fields and scoped drill-down routes.
- Modify `backend/recruitment/tests/test_recruitment_pages_api.py`: authorization and job-isolation regressions.
- Modify `backend/recruitment/tests/test_dashboard_api.py`: global dashboard and drill-down contract.
- Modify `frontend/src/views/recruitment/RecruitmentCandidatesView.vue`: require current job and make JobApplication the library row.
- Modify `frontend/src/views/recruitment/RecruitmentCandidatesView.test.js`: single-job library/discovery behavior.
- Modify `frontend/src/views/recruitment/RecruitmentPipelineView.vue`: scoped requests and job summary/empty state.
- Modify `frontend/src/views/recruitment/RecruitmentPipelineView.test.js`: job query and state transitions.
- Modify `frontend/src/views/recruitment/RecruitmentResumesView.vue`: scoped request and job-aware empty/detail states.
- Modify `frontend/src/views/recruitment/RecruitmentResumesView.test.js`: job query and no-selection gate.
- Modify `frontend/src/views/recruitment/RecruitmentDashboardView.vue`: global-view hierarchy and job drill-down.
- Modify `frontend/src/views/recruitment/RecruitmentDashboardView.test.js`: global metrics, empty state, and drill-down.
- Modify `frontend/src/styles.css`: selector, global indicator, scoped empty states, job cards, responsive and reduced-motion styles.

### Task 1: Enforce backend job access and isolation

**Files:**
- Modify: `backend/recruitment/models.py`
- Create: `backend/recruitment/migrations/0015_jobapplication_archived_at.py`
- Modify: `backend/recruitment/views.py`
- Modify: `backend/recruitment/serializers.py`
- Test: `backend/recruitment/tests/test_recruitment_pages_api.py`

- [x] **Step 1: Write failing API tests for open jobs and cross-account isolation**

Add fixtures for a second HR, authorized BOSS account, open/closed jobs, a shared candidate with one application per job, and a resume per application. Add assertions equivalent to:

```python
def test_open_job_filter_and_application_scope_do_not_leak_other_accounts(self):
    jobs = self.client.get("/api/recruitment/jobs/?status=open")
    self.assertEqual({item["id"] for item in jobs.data["results"]}, {self.visible_open_job.id})

    applications = self.client.get(f"/api/recruitment/applications/?job={self.visible_open_job.id}")
    self.assertEqual(applications.data["count"], 1)
    self.assertEqual(applications.data["results"][0]["job"], self.visible_open_job.id)

    hidden = self.client.get(f"/api/recruitment/applications/{self.hidden_application.id}/")
    self.assertEqual(hidden.status_code, 404)
```

Add a candidate assertion that `applications` contains only the requested job, plus resume assertions that `?job=<id>` returns only that job and a hidden resume detail returns 404. Add an application lifecycle assertion: archiving one JobApplication hides only that application, leaves the shared Candidate and its other application active, and restore returns it.

- [x] **Step 2: Run the focused backend tests and verify failure**

Run:

```powershell
..\.venv\Scripts\python.exe manage.py test recruitment.tests.test_recruitment_pages_api -v 2
```

Expected: FAIL because job status is ignored, application detail is not user-scoped, candidate serialization contains unrelated applications, or resume job filtering is absent.

- [x] **Step 3: Implement shared accessible-job and related queryset rules**

In `views.py`, introduce a focused helper and apply it consistently:

```python
def accessible_jobs(user):
    queryset = RecruitmentJob.objects.all()
    if user.is_superuser:
        return queryset
    return queryset.filter(
        Q(boss_account__authorized_users=user)
        | Q(boss_account__isnull=True, owner=user)
    ).distinct()
```

Filter `RecruitmentJobViewSet` by `status` when supplied. Filter `JobApplicationViewSet` with `job__in=accessible_jobs(request.user)` before applying `job` and `stage`. Filter `ResumeViewSet` by accessible jobs for every user and apply `application__job_id` when `job` is supplied.

Add `archived_at = models.DateTimeField(null=True, blank=True, db_index=True)` to `JobApplication`, generate migration `0015_jobapplication_archived_at.py`, and apply `ArchivableViewSetMixin` to `JobApplicationViewSet`. Archive/restore actions must operate only on the already user-scoped queryset.

For `CandidateViewSet`, build a `Prefetch("applications", queryset=JobApplication.objects.select_related("job", "owner").filter(job_id=job_id), to_attr="scoped_applications")` whenever `job` is present. In `CandidateSerializer`, return `scoped_applications` when available and fall back to the prefetched `applications` manager otherwise.

- [x] **Step 4: Run focused backend tests**

Run the command from Step 2.

Expected: all `RecruitmentPagesApiTests` pass.

- [x] **Step 5: Commit the backend isolation slice**

```powershell
git add backend/recruitment/models.py backend/recruitment/migrations/0015_jobapplication_archived_at.py backend/recruitment/views.py backend/recruitment/serializers.py backend/recruitment/tests/test_recruitment_pages_api.py
git commit -m "fix: isolate recruitment data by job"
```

### Task 2: Add the persistent recruitment context store

**Files:**
- Create: `frontend/src/stores/recruitmentContext.js`
- Create: `frontend/src/stores/recruitmentContext.test.js`

- [x] **Step 1: Write failing store tests**

Cover open-job loading, URL priority, per-user persistence, invalid selection clearing, and stale load suppression. Use a storage key shaped as `ximing-hr:recruitment-job:<user-id>` and assert:

```javascript
await store.loadJobs({ userId: 7 })
expect(apiMock).toHaveBeenCalledWith('recruitment/jobs/?status=open')
store.selectJob(12, { userId: 7 })
expect(localStorage.getItem('ximing-hr:recruitment-job:7')).toBe('12')
expect(store.currentJob.id).toBe(12)
```

Also resolve two deferred `loadJobs` calls in reverse order and assert the newest response remains in state.

- [x] **Step 2: Run the store test and verify failure**

```powershell
npm.cmd test -- src/stores/recruitmentContext.test.js
```

Expected: FAIL because the store does not exist.

- [x] **Step 3: Implement the store**

Implement state `jobs`, `selectedJobId`, `loading`, `error`, `loadedUserId`, and `requestSequence`; getters `currentJob` and `hasJobs`; actions `loadJobs`, `selectJob`, `restoreSelection`, `invalidateSelection`, and `reset`.

`loadJobs` must call only `recruitment/jobs/?status=open`, ignore stale responses by sequence number, restore only IDs still present in `jobs`, and never auto-select the first item. `selectJob` must accept only IDs present in `jobs` and persist by user ID.

- [x] **Step 4: Run the store tests**

Run the command from Step 2.

Expected: PASS.

- [x] **Step 5: Commit the store**

```powershell
git add frontend/src/stores/recruitmentContext.js frontend/src/stores/recruitmentContext.test.js
git commit -m "feat: add persistent recruitment job context"
```

### Task 3: Integrate the top-bar job context

**Files:**
- Create: `frontend/src/components/RecruitmentJobContext.vue`
- Create: `frontend/src/components/RecruitmentJobContext.test.js`
- Modify: `frontend/src/components/AppLayout.vue`
- Modify: `frontend/src/components/AppLayout.test.js`
- Modify: `frontend/src/router.js`
- Modify: `frontend/src/navigation.js`
- Modify: `frontend/src/styles.css`

- [x] **Step 1: Write failing component and layout tests**

Mark routes with `recruitmentScope: 'global' | 'job'`. Test that global routes render “全部职位 · 全局视图”; job routes render a searchable/selectable control; selecting job 12 pushes the same route with `{ query: { ...route.query, job: '12' } }`; scoped navigation links preserve `job`; and global navigation links omit it.

- [x] **Step 2: Run focused tests and verify failure**

```powershell
npm.cmd test -- src/components/RecruitmentJobContext.test.js src/components/AppLayout.test.js
```

Expected: FAIL because route metadata and the context component do not exist.

- [x] **Step 3: Implement route metadata and context UI**

Add route metadata:

```javascript
meta: { module: 'recruitment', recruitmentScope: 'job', title: '候选人' }
```

Use `global` for dashboard/jobs/automation and `job` for candidates/pipeline/resumes. In `AppLayout`, load jobs once authentication is restored, mount `RecruitmentJobContext`, and replace literal top-navigation targets with a function that includes `job` only for target routes whose metadata/definition is job-scoped.

The component must show job title as primary text and department/account as secondary text, emit selection through the store, update the route, and show “全部职位 · 全局视图” on global pages.

- [x] **Step 4: Add top-bar styles**

Add compact selector/global badge styles, a 320px maximum dropdown width, keyboard focus, 180ms open/close transition, long-label ellipsis, a stacked secondary label, responsive behavior below 1180px, and a `prefers-reduced-motion` override.

- [x] **Step 5: Run focused tests and build**

```powershell
npm.cmd test -- src/components/RecruitmentJobContext.test.js src/components/AppLayout.test.js
npm.cmd run build
```

Expected: tests PASS and Vite build succeeds.

- [x] **Step 6: Commit the navigation slice**

```powershell
git add frontend/src/components/RecruitmentJobContext.vue frontend/src/components/RecruitmentJobContext.test.js frontend/src/components/AppLayout.vue frontend/src/components/AppLayout.test.js frontend/src/router.js frontend/src/navigation.js frontend/src/styles.css
git commit -m "feat: add recruitment job selector"
```

### Task 4: Convert the candidate workspace to JobApplication scope

**Files:**
- Modify: `frontend/src/views/recruitment/RecruitmentCandidatesView.vue`
- Modify: `frontend/src/views/recruitment/RecruitmentCandidatesView.test.js`
- Modify: `backend/recruitment/serializers.py`

- [x] **Step 1: Write failing candidate-workspace tests**

Mount with current job 12. Assert the library calls `recruitment/applications/?job=12`, discovery calls `recruitment/candidate-discoveries/?imported=false&job=12`, the old “全部职位” and “来源职位” selects do not exist, and communication payload uses selected application IDs.

Add a no-selection test asserting neither applications nor discoveries are requested and the page renders “请先选择在招职位”.

- [x] **Step 2: Run candidate tests and verify failure**

```powershell
npm.cmd test -- src/views/recruitment/RecruitmentCandidatesView.test.js
```

Expected: FAIL because the page still fetches candidates and owns separate job selections.

- [x] **Step 3: Implement application-centric rows**

Replace `candidates` with `applications`. Render `application.candidate.name`, `application.candidate.current_title`, `application.stage_label`, `application.owner_name`, and `application.candidate.resume_count`. Use application IDs for selection and communication. Derive the BOSS account from `currentJob.boss_account`; keep the account visible but read-only in discovery.

All discovery search/deep-match payloads use `currentJob.id`. “移出当前职位” calls `POST recruitment/applications/<application-id>/archive/`; archived rows use `?job=<id>&archived=1` and restore calls the matching application restore endpoint. Candidate archival is removed from the primary job-workspace action because it affects all positions.

Extend `CandidateSummarySerializer` only with fields required by the application row; do not duplicate application state into Candidate.

- [x] **Step 4: Run candidate and serializer regression tests**

```powershell
npm.cmd test -- src/views/recruitment/RecruitmentCandidatesView.test.js
..\.venv\Scripts\python.exe manage.py test recruitment.tests.test_recruitment_pages_api recruitment.tests.test_communication_api -v 2
```

Expected: all focused suites pass.

- [x] **Step 5: Commit the candidate slice**

```powershell
git add frontend/src/views/recruitment/RecruitmentCandidatesView.vue frontend/src/views/recruitment/RecruitmentCandidatesView.test.js backend/recruitment/serializers.py
git commit -m "feat: scope candidate workspace to applications"
```

### Task 5: Scope pipeline and resume pages

**Files:**
- Modify: `frontend/src/views/recruitment/RecruitmentPipelineView.vue`
- Modify: `frontend/src/views/recruitment/RecruitmentPipelineView.test.js`
- Modify: `frontend/src/views/recruitment/RecruitmentResumesView.vue`
- Modify: `frontend/src/views/recruitment/RecruitmentResumesView.test.js`
- Modify: `frontend/src/styles.css`

- [ ] **Step 1: Write failing pipeline and resume tests**

With job 12 selected, assert calls to `recruitment/applications/?job=12` and `recruitment/resumes/?job=12`. Without a selection, assert no business request and the shared choice prompt. Assert pipeline empty state links to `{ name: 'recruitment-candidates', query: { job: '12' } }`. Assert archived resumes keep `job=12&archived=1`.

- [ ] **Step 2: Run focused tests and verify failure**

```powershell
npm.cmd test -- src/views/recruitment/RecruitmentPipelineView.test.js src/views/recruitment/RecruitmentResumesView.test.js
```

Expected: FAIL because both pages currently request unscoped lists.

- [ ] **Step 3: Implement scoped loading and states**

Read the current job from the context store and watch its ID. On a valid ID, clear only page-local selection and reload with `job`; on no ID, render the job-choice state. Resume preview detail must display both `candidate_name` and `job_title`. Pipeline hero must show job headcount and current application count.

- [ ] **Step 4: Run focused tests and build**

```powershell
npm.cmd test -- src/views/recruitment/RecruitmentPipelineView.test.js src/views/recruitment/RecruitmentResumesView.test.js
npm.cmd run build
```

Expected: tests PASS and build succeeds.

- [ ] **Step 5: Commit the scoped pages**

```powershell
git add frontend/src/views/recruitment/RecruitmentPipelineView.vue frontend/src/views/recruitment/RecruitmentPipelineView.test.js frontend/src/views/recruitment/RecruitmentResumesView.vue frontend/src/views/recruitment/RecruitmentResumesView.test.js frontend/src/styles.css
git commit -m "feat: scope pipeline and resumes by job"
```

### Task 6: Turn the recruitment dashboard into a global command center

**Files:**
- Modify: `backend/recruitment/services/dashboard.py`
- Modify: `backend/recruitment/tests/test_dashboard_api.py`
- Modify: `frontend/src/views/recruitment/RecruitmentDashboardView.vue`
- Modify: `frontend/src/views/recruitment/RecruitmentDashboardView.test.js`
- Modify: `frontend/src/styles.css`

- [ ] **Step 1: Write failing dashboard contract tests**

Assert every job-progress entry contains `candidates`, `to_screen`, `to_interview`, `account_name`, `account_status`, `updated_at`, and route `/recruitment/candidates?job=<id>`. Assert the endpoint ignores any incoming `?job=` and still returns all authorized open jobs.

In Vue tests, click a job card and assert `router.push('/recruitment/candidates?job=7')`. For an empty dashboard, assert the primary action routes to `/recruitment/jobs` and says “同步职位”, not “连接 BOSS 账号”.

- [ ] **Step 2: Run focused dashboard tests and verify failure**

```powershell
..\.venv\Scripts\python.exe manage.py test recruitment.tests.test_dashboard_api -v 2
npm.cmd test -- src/views/recruitment/RecruitmentDashboardView.test.js
```

Expected: FAIL on the new job-card fields, route, and empty-state action.

- [ ] **Step 3: Extend dashboard aggregation**

Annotate authorized open jobs with application-stage counts and select the BOSS account. Produce job cards with explicit account health and update time. Keep metrics/funnel/trend global and do not read a request job parameter in `dashboard_view`.

- [ ] **Step 4: Reorder and refine dashboard UI**

Label metrics “全部在招职位”, place today actions before risks, expand job cards with pending counts/account health, retain global funnel/trend below, and route every card to its job workspace. Replace the empty state with one action to职位管理同步职位.

- [ ] **Step 5: Run focused dashboard tests**

Run both commands from Step 2.

Expected: all focused tests pass.

- [ ] **Step 6: Commit the dashboard slice**

```powershell
git add backend/recruitment/services/dashboard.py backend/recruitment/tests/test_dashboard_api.py frontend/src/views/recruitment/RecruitmentDashboardView.vue frontend/src/views/recruitment/RecruitmentDashboardView.test.js frontend/src/styles.css
git commit -m "feat: make recruitment dashboard a global command center"
```

### Task 7: Refresh context after position synchronization

**Files:**
- Modify: `frontend/src/views/recruitment/RecruitmentJobsView.vue`
- Modify: `frontend/src/views/recruitment/RecruitmentJobsView.test.js`
- Modify: `frontend/src/stores/recruitmentContext.js`
- Modify: `frontend/src/stores/recruitmentContext.test.js`

- [ ] **Step 1: Write failing synchronization tests**

Assert the context store reloads only after the sync task reaches `succeeded`; failed/waiting-human tasks leave the old list intact. Assert a selected job absent from the successful reload is invalidated and the store exposes a user-readable invalidation reason.

- [ ] **Step 2: Run focused tests and verify failure**

```powershell
npm.cmd test -- src/views/recruitment/RecruitmentJobsView.test.js src/stores/recruitmentContext.test.js
```

Expected: FAIL because position sync does not notify the context store.

- [ ] **Step 3: Connect successful sync to the context store**

After existing RPA polling reports `succeeded`, call `context.loadJobs({ userId: auth.user.id, force: true })`. Do not reload the store on failed, cancelled, or waiting-human states. Preserve the old `jobs` array during refresh and invalidate selection only after a successful replacement list proves it absent.

- [ ] **Step 4: Run focused tests**

Run the command from Step 2.

Expected: PASS.

- [ ] **Step 5: Commit sync integration**

```powershell
git add frontend/src/views/recruitment/RecruitmentJobsView.vue frontend/src/views/recruitment/RecruitmentJobsView.test.js frontend/src/stores/recruitmentContext.js frontend/src/stores/recruitmentContext.test.js
git commit -m "feat: refresh job context after position sync"
```

### Task 8: Full regression and browser acceptance

**Files:**
- Verification only; any failure returns to the task that owns the affected file before this task can complete.

- [ ] **Step 1: Run the complete backend suite**

```powershell
..\.venv\Scripts\python.exe manage.py test -v 1
```

Expected: all Django tests pass.

- [ ] **Step 2: Run the complete frontend suite and production build**

```powershell
npm.cmd test
npm.cmd run build
```

Expected: all Vitest tests pass and Vite produces `backend/frontend_dist` without errors.

- [ ] **Step 3: Run Windows startup smoke checks**

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/test-startup.ps1
```

Expected: startup, SPA assets, API health, and content types pass.

- [ ] **Step 4: Rebuild/restart and complete browser acceptance**

Verify: global pages show “全部职位 · 全局视图”; no-selection job pages do not load mixed data; a job selection persists across candidates/pipeline/resumes and refresh; dashboard stays global; job cards drill down; rapid job switching never flashes old rows; successful sync refreshes the selector; failed sync preserves it.

- [ ] **Step 5: Verify a clean tree**

```powershell
git status --short --branch
```

Expected: clean worktree and local `master` containing all feature commits. If Step 1–4 exposed a defect, return to the owning task, add a focused regression test, implement the fix, rerun that task, and commit it before repeating Task 8.
