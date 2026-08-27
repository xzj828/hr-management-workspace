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

## 增量功能 W17：主动寻访结果批量打招呼（2026-08-27）

技术版本保持 Vue 3.5、Django 5.2、DRF 3.16 与 `@joohw/boss-cli` 0.6.6；不新增依赖和数据库 migration。执行策略为 `single`，因为候选读模型、审批资格和 Worker 回执共享同一状态契约，不适合拆成互不感知的并行修改。

### Task W17-1：统一打招呼资格与候选读模型

**Files:**
- Modify: `backend/recruitment/services/communications.py`
- Modify: `backend/recruitment/services/screening.py`
- Modify: `backend/recruitment/views.py`
- Test: `backend/recruitment/tests/test_communication_service.py`
- Test: `backend/recruitment/tests/test_screening_api.py`

**Inputs:** 当前岗位应聘集合、账号平台身份、历史 `greet` 动作和招聘阶段。

**Outputs:** 可供 UI 使用且不泄露 stable ID 的 `greeting` 投影，以及 prepare 阶段共享的事务内资格校验。

**Risk:** 收紧 `greet` prepare 可能影响旧候选人页的指纹身份操作；回滚方式是只撤销资格共享函数与读模型字段，不修改既有记录。

acceptance_criteria:
- `screening-results` 每条记录返回 `eligible/status/reason_code/reason_label`，响应中不包含 `external_id` 或指纹。
- 缺少 stable ID、招聘终态、已成功打招呼和已有活动打招呼动作均不能创建新审批。
- 同岗位同账号 1–100 个有效目标仍使用同一 `message` 创建一个审批和逐人动作快照。
- 运行对应 Django 测试通过。

status: completed
review_result: PASS（当前任务内完成集成安全复查；用户要求不启动子 Agent，已停止独立 reviewer；资格、事务幂等、读模型字段与 20+ 聚焦测试证据一致。）

### Task W17-2：结果中心批量选择与统一话术确认

**Files:**
- Modify: `frontend/src/views/recruitment/RecruitmentResultsView.vue`
- Modify: `frontend/src/views/recruitment/RecruitmentResultsView.test.js`
- Modify: `frontend/src/components/CommunicationConfirmDrawer.vue`
- Modify: `frontend/src/components/CommunicationConfirmDrawer.test.js`
- Modify: `frontend/src/recruitmentCommunications.js`
- Modify: `frontend/src/recruitmentCommunications.test.js`

**Inputs:** 当前岗位候选结果的 `greeting` 投影、既有复选状态和账号信息。

**Outputs:** “批量打招呼”入口、资格摘要、固定 greet 确认抽屉和统一话术 prepare/approve 调用。

**Risk:** 现有复选状态同时服务 HR 初筛；实现必须保留通过/未通过操作和跨页选择语义，切换岗位仍清空。

acceptance_criteria:
- 选中至少一名可执行候选人时能打开固定打招呼抽屉；抽屉只有一份整批话术，不显示逐人编辑。
- 全部候选人不可执行时不发起写请求，并展示服务端原因。
- 确认使用同一个 UUID prepare，随后 approve；只有返回包含 pending 步骤的批次才显示“已加入队列”。
- 提交失败保留选择与话术，重复点击不产生不同范围的请求。
- 相关 Vitest 通过且 390px 布局不产生新的横向溢出。

status: completed
review_result: PASS（当前任务内完成集成安全复查；确认快照冻结候选人/账号/统一话术，失败保留表单，审批响应必须含 pending 步骤才宣称入队，相关 Vitest 通过。）

### Task W17-3：稳定 ID 原子打招呼适配器

**Files:**
- Modify: `backend/recruitment/rpa/boss_chat_bridge.mjs`
- Modify: `backend/recruitment/rpa/cli.py`
- Modify: `backend/recruitment/management/commands/run_rpa_worker.py`
- Test: `backend/recruitment/tests/test_boss_cli.py`
- Test: `backend/recruitment/tests/test_communication_worker.py`

**Inputs:** 审批冻结的来源、职位、展示名、统一话术和平台 stable ID。

**Outputs:** 默认 `BossCliRunner.greet_by_external_id` 与包含稳定身份、打招呼核验字段的 Worker 回执。

**Risk:** BOSS DOM 和付费/风控弹层属于外部不稳定边界；进入点击后连接异常必须分类为 `external_result_uncertain`，禁止自动重试。回滚只撤销新增 bridge operation，保留失败关闭路径。

acceptance_criteria:
- 适配器在同一受管 CDP 会话内按来源与职位刷新列表，只接受唯一 stable ID，并复核展示名。
- 姓名相同、stable ID 不同或无 stable ID 时不点击；列表序号和组合指纹不授权外发。
- 成功回执包含 `verified/greeting_verified/expected_external_id/observed_external_id` 且 ID 完全一致。
- 验证码、风控、付费弹层和点击后未知结果均不回写成功；测试不连接真实 BOSS 账号。
- 对应 Django/Python 契约测试通过。

status: completed
review_result: PASS（当前任务内完成集成安全复查；列表对齐不一致不注入 stable ID，写前按来源重拉并用 stable ID + 展示名唯一复核，未知外部结果失败关闭。）

### Task W17-4：批次完成、阶段推进与人工事项闭环

**Files:**
- Modify: `backend/recruitment/services/communications.py`
- Test: `backend/recruitment/tests/test_communication_service.py`
- Test: `backend/recruitment/tests/test_stage_service.py`

**Inputs:** 已核验的逐项 Worker 完成回执。

**Outputs:** 逐项/批次状态、`greeted` 阶段历史、审计日志和 `greeting_required` 人工事项解决状态。

acceptance_criteria:
- 成功项推进到 `greeted` 并只解决同一应聘的开放打招呼事项。
- 可确定的单项身份问题进入 `waiting_human`；外部结果不确定时取消剩余未开始项并创建核查事项。
- 成功项不会被重新排队，批次最终状态按 succeeded/partial/failed/waiting_human 正确汇总。
- 对应服务测试通过。

status: completed
review_result: PASS（当前任务内完成集成安全复查；greeting_verified 为成功必需字段，未核验成功转 external_result_uncertain 并停止剩余项，成功只关闭同账号同应聘开放事项。）

### Task W17-5：回归验证与文档同步

**Files:**
- Modify: `docs/autodev-ideation.md`
- Modify: `docs/autodev-design.md`
- Modify: `docs/autodev-ui.md`
- Modify: `docs/autodev-api.md`
- Modify: `docs/autodev-index.md`
- Modify: `docs/autodev-rules.md`

acceptance_criteria:
- `python manage.py makemigrations --check --dry-run` 不产生 migration。
- 招聘相关 Django 测试、完整 Vitest 和 `npm run build` 通过。
- 降阶信号词扫描在本增量计划中无命中。
- 文档状态与代码、测试和真实账号人工验收边界一致，不宣称自动测试完成真实外发。

status: completed
review_result: PASS（五层验收完成：无 migration，Django 530/530、Vitest 258/258、Node 语法、Django check 与 Vite 生产构建通过；本地结果中心验证不可执行失败关闭及 390px 无横向溢出；真实 BOSS 外发明确保留人工验收。）
