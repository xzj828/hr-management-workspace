# 招聘自动化修复开发交接

> 交接日期：2026-08-26  
> 仓库：`C:\Users\35059\OneDrive\Desktop\hr\hr`  
> 当前分支：`fix/browser-cdp-identity`  
> 当前状态：第一阶段“运行中任务可中断”已提交；消息筛选、评分规则及领域取消入口尚未实现。

## 接手后先做什么

不要重新设计，直接按已经确认的设计和计划继续：

- 设计：[RPA 取消、消息筛选与重点评分设计](superpowers/specs/2026-08-26-rpa-cancellation-conversation-scoring-design.md)
- 实施计划：[Safer Recruitment Automation Implementation Plan](superpowers/plans/2026-08-26-rpa-cancellation-conversation-scoring.md)

用户最终确认的业务规则：

1. 取消任务时不关闭隔离浏览器，但正在运行的自动化必须停止，不能继续点击、跳页或把浏览器抢到前台。
2. 只有“未读消息 + 投递岗位等于当前选择岗位”的会话才能打开；其他聊天框不能打开，也不能触发索要简历。
3. 核心要求、硬性要求都不是强制门槛，只在评分时使用；重点项按普通项的 **2 倍权重**计算，不自动淘汰、不强制改成暂缓。

开始前执行：

```powershell
cd C:\Users\35059\OneDrive\Desktop\hr\hr
git switch fix/browser-cdp-identity
git status --short --branch
git log --oneline master..HEAD
```

预期工作树只有用户自己的未跟踪目录：

```text
?? tools/
```

不要添加、修改或删除 `tools/`。

## 当前分支已有提交

按从新到旧排列：

| 提交 | 内容 | 状态 |
|---|---|---|
| `c0628e2` | 运行中 RPA 任务请求取消并中断 boss-cli | 已完成，相关 80 个测试通过 |
| `999c00a` | 本轮完整实施计划 | 文档 |
| `11fd18c` | 重点评分权重从 1.25 倍改为 2 倍 | 文档 |
| `846cf63` | 三项问题的确认设计 | 文档 |
| `9535420` | 兼容当前 BOSS 职位列表并成功同步 17 个真实职位 | 已完成 |
| `7e7269a` | 删除前端演示入口并清理本地假数据 | 已完成 |
| `2e116f1` | 修复隔离浏览器启动时 CDP 身份记录竞态 | 已完成 |

这些提交尚未推送 GitHub。接手 Agent 应继续在当前分支提交，不要改写已有提交历史。

## 已经完成的代码

### 运行中任务取消

提交 `c0628e2` 已完成以下内容：

- `RpaTask.Status` 新增 `cancel_requested`。
- 待执行任务取消后直接进入 `cancelled`。
- 已领取或运行中任务取消后进入 `cancel_requested`。
- Worker 新增控制查询接口：

```http
GET /api/recruitment/worker/tasks/{task_id}/control/?worker_key={worker_key}
X-RPA-Worker-Token: <configured token>
```

- `BossCliRunner` 在有取消回调时使用可监控的 `Popen`，每 0.25 秒检查一次。
- 收到取消后只结束当前 boss-cli 进程，不结束 Edge/Chrome。
- Windows 下 boss-cli 使用 `CREATE_NO_WINDOW`，避免额外控制台窗口。
- 已请求取消的任务收到晚到成功回执时，服务端仍保存为 `cancelled`，不会写入成功结果。
- 新增迁移：`backend/recruitment/migrations/0028_remove_rpatask_unique_active_rpa_task_per_account_and_more.py`。

主要实现位置：

| 文件 | 责任 |
|---|---|
| `backend/recruitment/models.py` | `cancel_requested` 状态和活动任务唯一约束 |
| `backend/recruitment/rpa/tasks.py` | 用户取消状态流转 |
| `backend/recruitment/rpa/cli.py` | 可中断的 boss-cli 子进程 |
| `backend/recruitment/management/commands/run_rpa_worker.py` | Worker 绑定取消回调并报告取消 |
| `backend/recruitment/worker_api.py` | 控制状态接口和取消回执保护 |
| `backend/recruitment/urls.py` | Worker 控制接口路由 |

相关测试已运行：

```powershell
cd C:\Users\35059\OneDrive\Desktop\hr\hr\backend
python manage.py test recruitment.tests.test_boss_cli recruitment.tests.test_worker_command recruitment.tests.test_rpa_api recruitment.tests.test_worker_api -v 1
```

最后一次结果：共运行 80 个测试，全部通过。

### 改动前基线

在 `c0628e2` 之前已运行完整基线：

```text
后端：403 tests，全部通过
前端：38 个测试文件、194 tests，全部通过
```

注意：`c0628e2` 之后还没有重新运行完整 403 个后端测试，只跑了上述 80 个相关测试。

## 还需要完成的工作

### 让所有取消入口通知运行中的 Worker

当前普通 `RpaTaskViewSet.cancel` 已支持运行中取消，但领域入口仍沿用旧逻辑：

- `backend/recruitment/services/search_campaigns.py::stop_search_campaign`
  - 目前遇到 `leased/running` 会直接报错“当前适配器无法安全中断”。
  - 应改为把活动任务设为 `cancel_requested` 并写事件，让 Worker 真正停下来。
- `backend/recruitment/services/communications.py::cancel_workflow_communication`
  - 目前只取消未开始的任务，活动任务继续执行。
  - 应给活动任务写入 `cancel_requested`，并让对应步骤和沟通动作收敛为取消。
- `backend/recruitment/services/workflow_runtime.py::cancel_run`
  - 目前记录了活动节点，但没有把活动 `RpaTask` 设为 `cancel_requested`。
  - 应确保普通节点、沟通节点、主动寻访节点都通知 Worker。
- `frontend/src/recruitmentJobs.js` 以及展示任务状态的组件
  - 新增 `cancel_requested` 文案“正在取消”和非终态进度展示。

需要更新或新增的测试：

- `backend/recruitment/tests/test_search_campaigns.py`
  - 现有 `test_stop_refuses_to_claim_cancellation_after_browser_execution_started` 应改成期望活动任务进入 `cancel_requested`。
- `backend/recruitment/tests/test_workflow_runtime.py`
  - 增加取消运行中节点后底层任务进入 `cancel_requested` 的断言。
- `backend/recruitment/tests/test_communication_service.py`
  - 增加运行中沟通任务被请求取消的断言。
- `frontend/src/recruitmentJobs.test.js`
  - 增加“正在取消”状态。

实现时必须保留这个边界：取消只结束本次 boss-cli 命令，不能调用 `stop_login`，不能结束浏览器 PID。

### 只打开所选岗位的未读会话

根因已经定位：

1. `backend/recruitment/rpa/cli.py::conversations` 已支持 `unread=True`，会执行 `list --unread`。
2. `backend/recruitment/management/commands/run_rpa_worker.py::execute_sync_conversations` 没有使用该参数，而是读取全部会话。
3. 同一函数直接遍历 `rows[:50]` 并调用 `open_chat`，所以每个聊天框都被打开。
4. `backend/recruitment/rpa/conversations.py::parse_conversation_list` 能看到列表中的岗位字段，但当前只保留姓名和未读状态，丢掉了岗位名称。
5. 工作流创建同步任务时已经冻结了 `request_payload.job` 和 `request_payload.job_title`，位置在 `backend/recruitment/services/workflow_nodes.py`，无需新增前端参数。
6. `backend/recruitment/worker_api.py` 完成消息同步时按“账号 + 姓名”找投递记录，没有限制当前岗位，存在串岗风险。

正确数据流应为：

```text
同步任务中的 job/job_title
  -> boss-cli list --unread
  -> 解析 name + job_title + unread + external_id
  -> 先筛选未读且岗位精确一致
  -> 再验证该候选人在所选岗位下唯一
  -> 只有通过者才能 open_chat / 下载附件
  -> 服务端再次按 account + job + candidate 校验后入库
  -> 意图识别
  -> 符合索要简历意图时才生成后续人工确认
```

岗位比较规则已经确认：只归一化空白字符后精确比较，不做模糊匹配。岗位缺失、岗位不符、同名歧义全部安全跳过，不能回退成遍历所有聊天框。

建议按 TDD 顺序修改：

1. 在 `backend/recruitment/tests/test_conversation_sync.py` 增加岗位解析测试。
2. 在 `backend/recruitment/tests/test_worker_command.py` 构造三行列表：已读目标岗、未读其他岗、未读目标岗；断言只打开最后一行，且 `runner.conversations(account, unread=True)`。
3. 修改 `parse_conversation_list`，把姓名后的第一个无标签字段保存为 `job_title`。
4. 修改 `execute_sync_conversations`，先筛选再打开，最多处理 50 条合格会话。
5. 修改 `sync_conversation_states` 的签名为 `account, job, rows, actor=None`。
6. 修改 `worker_api.complete_task_view`，先用任务里的岗位 ID 和账号解析 `RecruitmentJob`，再按该岗位匹配投递记录、入库消息、归档附件。
7. 更新 `backend/recruitment/tests/test_worker_api.py` 中两个消息同步测试，为任务补上 `request_payload={"job": job.pk, "job_title": job.title}`。

关键现有测试位置：

- `test_worker_command.py::test_conversation_sync_returns_every_chat_message`
- `test_worker_api.py::test_conversation_completion_persists_all_messages_and_observation_attention`
- `test_worker_api.py::test_ordinary_candidate_message_creates_draft_resume_request_confirmation`

### 把硬性要求改成 2 倍权重评分项

当前后端仍有两层硬门槛：

- `backend/recruitment/services/resume_intelligence.py`
  - 规范化模型结果时会因硬性失败把建议改成 `hold`。
  - 创建评估后又调用 `deterministic_hard_failures`，再次强制改成 `hold`。
  - `auto_reject_on_hard_fail=True` 时会调用 `reject_for_hard_requirements` 改变候选人阶段。
- `backend/recruitment/services/job_standards.py`
  - 仍接受并启用 `auto_reject_on_hard_fail`。
- 前端：
  - `frontend/src/components/JobStandardDrawer.vue` 仍显示 `HARD GATES`、硬性指标、淘汰条件和自动淘汰开关。
  - `frontend/src/components/ResumeIntelligencePanel.vue` 仍把差距显示成“硬性指标未满足/淘汰条件”。

必须实现的行为：

- 新评估永远不自动淘汰，`assessment.auto_rejected` 必须为 `False`。
- 重点项不覆盖模型原始建议，不能强制设为 `hold`。
- 历史 `hard_requirements` 继续可读，但运行时适配成重点评分维度。
- 历史 `auto_reject_on_hard_fail=True` 也必须失效。
- 新标准把重点项作为评分维度，重点项原始权重为普通维度平均权重的 2 倍，再把所有维度等比例归一化为总计 100 分。
- HR 仍可在发布前手工调整最终权重。

建议把权重转换写成纯函数并单独测试。例如普通维度原始权重为 `30, 70`，普通平均为 `50`，一个重点项原始权重为 `100`；合并原始总数 `200` 后归一化为 `15, 35, 50`。

需要先改的测试：

- `backend/recruitment/tests/test_resume_intelligence_api.py::test_explicit_hard_requirement_failure_can_auto_reject_with_evidence`
  - 改为断言不淘汰、不改阶段、不强制 `hold`。
- `backend/recruitment/tests/test_job_standards_api.py::test_accepts_explicit_hard_requirements_but_rejects_sensitive_ones`
  - 保留敏感字段校验，但断言归一化后的自动淘汰始终为 `False`。
- `frontend/src/components/JobStandardDrawer.test.js`
  - 断言不出现自动淘汰开关，出现“重点评分项”和“2 倍权重”。
- `frontend/src/components/ResumeIntelligencePanel.test.js`
  - 断言差距显示为重点项评分差距，而不是淘汰条件。

实现时不要删除数据库里的历史字段，以免破坏历史记录和 API 兼容；只需要让新逻辑不再执行淘汰。

## 测试和验收命令

每一块先跑相关测试，再跑全量：

```powershell
cd C:\Users\35059\OneDrive\Desktop\hr\hr\backend
python manage.py test recruitment.tests.test_boss_cli recruitment.tests.test_worker_command recruitment.tests.test_rpa_api recruitment.tests.test_worker_api recruitment.tests.test_search_campaigns recruitment.tests.test_workflow_runtime recruitment.tests.test_communication_service recruitment.tests.test_conversation_sync recruitment.tests.test_job_standards_api recruitment.tests.test_resume_intelligence_api -v 1
```

```powershell
cd C:\Users\35059\OneDrive\Desktop\hr\hr\backend
python manage.py test -v 1
python manage.py makemigrations --check --dry-run
```

```powershell
cd C:\Users\35059\OneDrive\Desktop\hr\hr\frontend
npm test
npm run build
```

```powershell
cd C:\Users\35059\OneDrive\Desktop\hr\hr
git diff --check
git status --short
```

最终验收场景：

1. 运行中任务点击取消，浏览器保留登录，但不再继续点击或跳页。
2. 同时存在“已读目标岗、未读其他岗、未读目标岗”时，只打开未读目标岗。
3. 候选人明确不满足重点项时仍生成正常评分和建议，候选人阶段不自动变化。

## 本机运行状态提醒

- 此前职位同步修复后，本机数据库已同步出 17 个真实职位。
- 假数据已清理：假职位、候选人、投递、简历均为 0。
- 服务是在提交 `c0628e2` 之前启动的，因此当前后台进程不包含最新取消代码。
- 迁移 `0028` 尚未对本机业务数据库执行。
- 完成所有代码并通过测试后再执行：

```powershell
cd C:\Users\35059\OneDrive\Desktop\hr\hr\backend
python manage.py migrate
```

然后按项目原有方式重启 Django 和 RPA Worker。不要关闭仍需保留登录状态的 BOSS 隔离浏览器。

## GitHub 协作规则

当前分支尚未推送。完成并验证后首次推送：

```powershell
cd C:\Users\35059\OneDrive\Desktop\hr\hr
git push -u origin fix/browser-cdp-identity
```

如果另一台电脑也在修改，不要让两台电脑同时直接改同一个远端分支。建议另一台电脑使用自己的分支，最后合并：

```powershell
git fetch origin
git switch fix/browser-cdp-identity
git pull --rebase origin fix/browser-cdp-identity
```

遇到冲突时逐文件解决并重新跑测试，不使用 `git reset --hard`，不覆盖未提交文件。

## 证据、结论与开发路径

### E-001 分支状态

- observed_at: 2026-08-26
- source_type: command
- source_ref: `git status --short --branch`
- repro_command: `git status --short --branch`
- raw_excerpt: `## fix/browser-cdp-identity`，仅有 `?? tools/`

### E-002 已完成提交

- observed_at: 2026-08-26
- source_type: command
- source_ref: `git log --oneline master..HEAD`
- repro_command: `git log --oneline master..HEAD`
- raw_excerpt: 最新业务提交为 `c0628e2 fix: interrupt cancelled boss automation tasks`

### E-003 相关测试

- observed_at: 2026-08-26
- source_type: command
- source_ref: Django test runner
- repro_command: `python manage.py test recruitment.tests.test_boss_cli recruitment.tests.test_worker_command recruitment.tests.test_rpa_api recruitment.tests.test_worker_api -v 1`
- raw_excerpt: 共运行 80 个测试，全部通过

### F-001 当前交接结论

- status: validated
- evidence_ids: `E-001`, `E-002`, `E-003`
- finding: 普通运行中任务已具备可中断机制；领域取消入口、岗位未读筛选和 2 倍重点评分仍需开发。
- impact: 如果只部署当前提交，普通任务能停，但工作流/主动寻访可能仍无法通知 Worker；消息同步仍会遍历会话；评分仍可能自动淘汰。

### P-001 推荐开发路径

1. 补齐工作流、沟通批次和主动寻访的 `cancel_requested` 流转。
2. 完成 `list --unread`、岗位解析和 Worker/服务端双层岗位校验。
3. 完成 2 倍重点项权重和移除自动淘汰。
4. 跑后端全量、前端全量、前端构建、迁移检查。
5. 执行迁移、重启服务、做三个真实验收场景。
6. 提交并推送当前分支。

## 不要做的事

- 不要关闭或删除隔离浏览器配置目录。
- 不要为了消息同步失败而回退到打开全部聊天框。
- 不要做岗位名称模糊匹配。
- 不要让任何重点项自动改变候选人阶段。
- 不要提交 `tools/`。
- 不要改写或压缩现有提交历史。
