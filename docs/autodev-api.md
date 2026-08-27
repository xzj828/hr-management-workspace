# 西鸣人事管理系统 — API 设计（逆向生成）

> 来源：从现有代码库逆向生成
> 基于：`autodev-design.md` + `autodev-ui.md`

## API 约定

- 基础路径 `/api/`，JSON 为默认格式；文件上传使用 multipart，导出/简历返回二进制。
- 浏览器认证使用 Django Session，所有请求同源携带 Cookie；非安全方法要求 `X-CSRFToken`。
- 列表默认 DRF PageNumberPagination、每页 500；策略/标签显式不分页。前端兼容数组和 `{count,next,previous,results}`。
- 成功：创建 201、读取/更新 200、无内容 204；幂等创建命中已有资源时可返回 200。
- 错误：通用 `{ "detail": "可读说明" }`；Serializer 字段错误使用字段映射。400 校验、401 未登录、403 越权、404 不存在、409 生命周期/重复冲突。
- 时间为带时区 ISO 8601，日期为 `YYYY-MM-DD`，月份为 `YYYY-MM`；金额/天数等 Decimal 在 JSON 中通常为字符串。
- 自动化创建请求使用 UUID `request_id`/幂等键；服务端保留不可变 payload 快照。

## 数据模型

### 账户与配置

| 实体 | 核心字段 | 关系/约束 |
|---|---|---|
| Django User | username, first_name, is_active, is_superuser | Session 身份 |
| AccountProfile | role, department | User 1:1；角色 admin/hr/supervisor/viewer |
| UserModelProfile | name, api_url, model, encrypted_api_key, key_last4, is_active | User N:1；用户内名称不区分大小写唯一；每用户最多一个活动档案；Key 加密 |
| UserModelCredential | api_url, model, encrypted_api_key, key_last4 | User 1:1；活动档案的兼容投影，供既有 AI 服务读取 |

### 考勤域

| 实体 | 核心字段 | 关系/约束 |
|---|---|---|
| EmployeeTag | name, color, description | name 唯一；Employee M:N |
| AttendancePolicy | code, name, mode, start/end, grace, cutoff, active | code 唯一；mode 五类 |
| Employee | employee_no, name, aliases, department, position, status, policy, expected override, 联系/银行字段 | 工号唯一；Policy N:1；Tag M:N |
| ImportBatch | file, sha256, year, month, expected days, counts, status | uploader N:1；同哈希+期间由服务拒绝 |
| RawPunchDay | source row, employee, work_date, punches, match_status, effective flag | batch+row+date 唯一 |
| AttendanceResult | due/punch/leave/overtime/adjustment/actual, status, trace | batch+employee 唯一 |
| CrossDaySuspicion | previous/work date, punch, reason, status | RawPunchDay 1:1；显式审核人/时间 |

### 招聘业务域

| 实体 | 核心字段 | 关系/约束 |
|---|---|---|
| BossAccount | name, browser/profile/port, login/status, daily limits, active, archived_at | name/profile/port 唯一；authorized_users M:N |
| RecruitmentJob | external_id, title, department, jd, owner, headcount, status | account+external_id 唯一 |
| Candidate | identity_key, external_id, name, phone/email, title/city | identity_key 唯一 |
| JobApplication | candidate, job, source, stage, owner, priority, last_interaction | candidate+job 唯一；13 个阶段 |
| Resume | file, type, size, source, processing status, sha256, version | candidate+hash、candidate+version 唯一 |
| CandidateDiscovery | account, job, source, fingerprint, identity quality, profile, criteria, expiry | account+job+fingerprint 唯一 |
| CandidateExternalIdentity | account, candidate, platform ID/fingerprint, quality | account+fingerprint 唯一 |
| ApplicationStageHistory | application, from/to, reason, source, actor/task | 只追加审计 |
| FileTextExtraction | source kind/id/hash, method, blocks, status/error | Word/Excel/PDF/PNG 本地提取结果；块 ID 是证据锚点 |
| JobStandardVersion | job, version, criteria, hard requirements, status | 同职位仅一个 published；发布后不可变 |
| StructuredResumeVersion | resume, version, data, evidence, warnings | PDF/PNG 共用结构；原始未知字段保持 null |
| ResumeAssessment | structure, standard, version, score, hard failures, evidence, recommendation | 请求 UUID 唯一；重评新增版本 |
| ScreeningDecisionBatch | request_id, job, decision, reason, created_by | UUID 幂等；同一请求的业务载荷不可变化 |
| ApplicationScreeningDecision | batch, application, resume, assessment, decision, version, decided_by | 只追加；application+version、batch+application 唯一；不修改招聘阶段 |
| AiProcessingTask | kind, lease/status, resume/job/standard, error/result, private model snapshot/bound_at | DB 租约；岗位标准、结构化、评分三类任务；连接快照字段永不序列化 |

### 自动化与流程域

| 实体 | 作用 | 关键约束 |
|---|---|---|
| RpaWorker | 心跳、能力、版本 | key 唯一，last_seen 判断在线 |
| RpaTask / RpaTaskEvent | 单账号动作租约与时间线 | UUID；幂等键唯一；每账号最多一个活跃任务 |
| RecruitmentAuditLog | 招聘关键动作审计 | 记录 actor、account、action、target 和 detail，只追加 |
| AutomationApproval | 人工确认的不可变动作快照 | UUID；状态/过期/批准人；幂等键 |
| ExecutionBatch / StepExecution | 逐候选人执行与部分成功 | batch 幂等键；步骤独立状态 |
| AutomationEvidence / AutomationUsage | 证据和日额度消耗 | 关联步骤/账号/日期指标 |
| ConversationAction / InterviewInvitation | 话术与结构化邀约快照 | 关联应聘、审批、批次、步骤 |
| ConversationSyncState | 未读、同步和身份状态 | application 1:1 |
| WorkflowTemplate / WorkflowVersion | 流程与不可变版本 | 版本号在模板内唯一；启用版本保留 |
| WorkflowNode / WorkflowEdge | 有向图 | 节点 key 唯一；禁止环和未确认发送 |
| WorkflowRun / WorkflowNodeRun / WorkflowRunEvent | 试运行/正式运行快照与控制 | request_id 幂等；节点执行顺序持久化 |
| RecruitmentAutomationPlan | 岗位级招聘自动化控制面 | job 唯一；desired_state、control_version、control_generation、current revision/run |
| RecruitmentAutomationPlanRevision | 每次正式开启的不可变方案 | plan+revision 唯一；冻结 kind、config、workflow version 和请求哈希 |

对抗审查补充约束（2026-08-25）：`request_resume` 必须绑定已批准的不可变动作快照；主动搜索只产生候选摘要，打开/归档在线简历必须逐份计入 `resume_view`。外部动作只能由适配器在同一次原子调用中按平台稳定 ID（或平台原生等价标识）定位、复核并执行；组合指纹、展示名唯一或“先核验 ID、再按姓名执行”均不满足动作身份契约。缺少该能力时必须转人工提醒。批量任务的审批快照必须冻结候选集合或确定性搜索条件、最大数量和额度预算。

任务级自动化证据必须覆盖批量在线简历的每次尝试（目标稳定身份、核验结果、动作结果、错误与时间），并关联 `RpaTask`；额度记录需区分批准预算/预留值与实际尝试数。批量完成回写若任一身份、路径或归档失败，候选导入、简历归档、Campaign 统计等业务写入必须整体回滚，再单独写入 Task/Campaign 的失败终态。

任务级证据只持久化平台稳定 ID 的不可逆哈希、序号、时间、布尔核验值和受控结果码，不保存姓名、原始组合指纹、原始平台 ID、文件路径或 Worker 原始错误。主动寻访的所有终态（含 Worker 主动失败、回执预校验失败、取消及租约超时）都必须写额度账本；无法安全确认实际次数时使用 `actual_known=false`、`actual=null`、`unused=null` 和 `evidence_untrusted=true`，预留额度保持不退款。

通用 `POST /api/recruitment/rpa-tasks/` 仅允许 `check_status`、`sync_positions`、`sync_conversations`。沟通、在线简历、深度匹配和主动寻访必须通过各自专用确认/物化服务，并使用服务端规范幂等键和 Approval/Batch/Campaign/Workflow 关联；关联任务不得通过通用取消或重试拆离领域状态。主动寻访取消或租约超时时，Task、Campaign、额度证据、账号状态与关联 Workflow 必须在同一领域收口中结束。

`check_status + request_payload.open_login=true` 表示“打开或聚焦该账号的受管登录窗口”，不是自动登录。创建端点必须在账号行锁内复用同账号处于 `pending/leased/running` 的等价任务；Worker 或 CLI 不可用时返回可读的前置条件冲突，不新增永久排队任务。前端以 POST 响应中的任务为提交事实，刷新失败单独报告。账号状态、任务与自动化摘要由管理后台每 5 秒非重叠刷新。

Worker 执行 `open_login` 时异步启动固定 Node/JS CLI，轮询受管 CDP；CDP 就绪后写入账号隔离目录 marker、结束 CLI 父进程并返回 `succeeded + login_status=waiting_login`。CLI 进程 stdout/stderr 丢弃，终止采用 terminate→短等待→kill 的 best-effort 清理，不能把用户尚未扫码误报为系统失败。

`GET /api/recruitment/automation/summary/` 的 Worker 在线值由 `last_seen_at` 与服务端 TTL 计算，不直接信任历史 `status=online`。Worker 心跳在 CLI 不可用时仍应上报结构化能力状态，使 UI 能区分“Worker 未连接”和“Worker 在线但 CLI 不可用”。BOSS 登录 `ready` 只接受明确的招聘端已认证页面；公共、错误、未知页面一律保持未就绪。

招聘作业台不再直接串联消息策略、流程版本和 Run 写请求。`POST /api/recruitment/automation-plans/start/` 在同一事务中校验岗位/账号/乐观版本，冻结配置与流程、创建 Run 并最后刷新消息策略；失败整体回滚。`POST /api/recruitment/automation-plans/<id>/pause|resume|stop/` 使用 UUID request_id 与 expected_control_version。停止返回的 `effective_state=stopping` 表示在途原子动作尚在安全收尾；只有所有本代租约结束后才是 `stopped`。

Plan 关联的 WorkflowRun、SearchCampaign、RpaTask 和系统托管 WorkflowVersion 不允许从通用控制端点绕过 Plan 状态机。每次 RPA lease 返回唯一 token 和递增 generation，Worker event/checkpoint/complete 必须回传并匹配；Plan revision/generation 也必须在创建、领取、外部动作前后和完成推进边界复核。岗位或账号归档、职位关闭、Plan 停止/重启和共享被动 scope 变化均使旧代失败关闭。

本地默认 SQLite 因不支持有效的 `SELECT FOR UPDATE`，数据库连接使用 `transaction_mode=IMMEDIATE`，生命周期入口再以进程内 RLock 包住最外层事务；这与数据库唯一约束、control version 和 lease token 共同提供单机 Waitress 多线程的线性化。切换 PostgreSQL 时使用原生行锁，不启用该进程锁。

取消 WorkflowRun 后，草稿 Approval、未执行的领域 Task/Batch/Step 和后续 Node 一并终结；Worker lease 必须排除暂停或终态 Run/Node，`create_task` 也必须校验 Workflow 生命周期与 node attempt。已进入适配器的任务不能伪装取消，其真实完成回执只更新动作审计，不恢复已取消 Run。直接停止 SearchCampaign 与从 Task 入口停止使用同一领域服务，并在提交后同步 Workflow。失败的 `deep_search` 重试必须创建新 attempt 的确认、幂等键和 Task。

## 认证与授权

| API 类别 | Anonymous | Viewer/Supervisor | HR | Admin | Worker Token |
|---|---:|---:|---:|---:|---:|
| CSRF、登录 | 是 | 是 | 是 | 是 | 否 |
| 登录后普通读取 | 否 | 是 | 是 | 是 | 否 |
| 考勤/招聘写入 | 否 | 否 | 是 | 是 | 否 |
| BOSS 账号动作 | 否 | 否 | 仅授权账号 | 全部/按实现 | 否 |
| 模型档案与凭证 | 否 | 自己 | 自己 | 自己 | 否 |
| Worker 心跳/租约/回写 | 否 | 否 | 否 | 否 | 是 |

[待确认] Supervisor 的 `department` 尚未用于 queryset 过滤，当前登录用户可读取全局业务数据。

## API 端点

### 认证与个人配置

| 方法 | 路径 | 用途/对应 UI |
|---|---|---|
| GET | `/api/auth/csrf/` | 写请求前建立 CSRF Cookie |
| POST | `/api/auth/login/` | 登录页；username/password/remember |
| POST | `/api/auth/logout/` | 用户菜单退出 |
| GET | `/api/auth/me/` | Shell 恢复会话 |
| GET/PUT/DELETE | `/api/account/model-credential/` | 兼容端点；读写当前活动模型投影，并同步对应活动档案 |
| POST | `/api/account/model-credential/test/` | 测试当前活动连接；只返回模型与延迟，不返回 Key |
| GET/POST | `/api/account/model-profiles/` | 列出自己的模型档案；新增档案，首个自动启用，可显式 `make_active` |
| GET/PATCH/DELETE | `/api/account/model-profiles/{id}/` | 读取、编辑或永久删除自己的档案；活动档案编辑后同步兼容投影 |
| POST | `/api/account/model-profiles/{id}/activate/` | 原子切换当前模型；重复激活幂等 |
| POST | `/api/account/model-profiles/{id}/test/` | 测试指定档案；响应不含 API Key 或加密文本 |

模型档案规则：所有查询按 Session 用户过滤，其他用户的 ID 返回 404；输出只含 `has_api_key/key_last4`。创建首个档案自动激活，之后新增默认不切换，除非请求 `make_active=true`。切换、活动档案编辑和旧凭证写入在事务内同步 `UserModelCredential`；活动档案不能出现两个，数据库条件唯一约束作为最后防线。删除任意档案会擦除其加密 Key；删除活动档案同时删除 `UserModelCredential` 投影，不自动启用其他档案，已绑定模型快照的历史任务不受影响。API 地址规范化前后都不得超过 500 字符；API Key 必须为 8–4096 字符，序列化器与领域服务双层校验，历史末四位提示通过独立迁移清除后由新写入重建。

模型出网规则：默认拒绝非 HTTPS、userinfo、query/fragment、localhost，以及解析或实际连接到 loopback/private/link-local/reserved/unspecified/multicast 的地址；3xx 不跟随。解析通过后连接固定到已验证的数字 IP，HTTPS 仍以原域名完成 SNI、证书与 Host 校验，避免二次 DNS 重绑定。只有部署管理员通过 `MODEL_API_HOST_ALLOWLIST=host[:port],...` 精确配置的主机可以例外开放 HTTP 或本机/内网模型；该例外不得由普通用户控制。`MODEL_API_MAX_RESPONSE_BYTES` 默认 1 MiB；连接测试由 `MODEL_API_TEST_TIMEOUT_SECONDS`（默认 10 秒）与 `MODEL_API_TEST_THROTTLE_RATE`（默认每用户 `5/min`）限制。任务创建时冻结 API 地址、模型名与加密 Key 快照，序列化器永不输出该快照；Worker 和重试使用任务快照而非当前活动投影。

### 考勤资源

标准资源规则：`GET collection/detail`；标为“可写”的资源另有 `POST collection`、`PUT/PATCH/DELETE detail`。

| 资源/方法 | 路径 | 查询/动作 |
|---|---|---|
| 策略 CRUD | `/api/policies[/<id>/]` | 不分页 |
| 标签 CRUD | `/api/tags[/<id>/]` | 不分页 |
| 人员 CRUD | `/api/employees[/<id>/]` | q, active, mode, tag |
| 批次 GET/POST | `/api/imports[/<id>/]` | multipart file/year/month/default_expected_days |
| GET | `/api/imports/<id>/export/` | 完成批次导出 Excel |
| 结果 GET/PATCH | `/api/results[/<id>/]` | batch, q, status；PATCH 后重算 |
| POST | `/api/results/<id>/approve/` | HR 确认结果 |
| 原始日 GET | `/api/raw-days[/<id>/]` | batch, employee, match_status |
| 疑似 GET | `/api/suspicions[/<id>/]` | batch, status |
| POST | `/api/suspicions/<id>/resolve/` | resolution=assign_previous/keep_current |
| GET | `/api/dashboard/` | from, to, department；考勤看板聚合 |

### 招聘业务资源

| 资源/方法 | 路径 | 查询/动作 |
|---|---|---|
| BOSS 账号 GET/POST/PATCH | `/api/recruitment/boss-accounts[/<id>/]` | `archived=1`; 创建自动派生 profile/port；禁止物理 DELETE |
| POST | `.../boss-accounts/<id>/check-status/` | 立即只读检查登录状态 |
| POST | `.../<resource>/<id>/archive|restore/` | 账号/职位/简历/任务/流程的可恢复生命周期 |
| 职位 GET/POST/PATCH | `/api/recruitment/jobs[/<id>/]` | is_demo；按用户授权账号过滤；禁止物理 DELETE |
| POST | `/api/recruitment/jobs/sync/` | boss_account + UUID request_id，幂等创建同步任务 |
| 候选人只读 | `/api/recruitment/candidates[/<id>/]` | search, job, stage, is_demo |
| 应聘 CRUD | `/api/recruitment/applications[/<id>/]` | job, stage, is_demo；阶段变更需原因 |
| 发现结果只读 | `/api/recruitment/candidate-discoveries[/<id>/]` | account, job, source, imported |
| POST | `.../candidate-discoveries/search/` | 推荐/关键词搜索，创建只读发现任务 |
| POST | `.../candidate-discoveries/prepare-deep-match/` | 创建深度匹配确认快照 |
| POST | `.../candidate-discoveries/import-selected/` | ids；幂等导入候选人/应聘 |
| 简历只读 | `/api/recruitment/resumes[/<id>/]` | job, archived=1；版本、文件和最新结构化状态 |
| GET | `/api/recruitment/resumes/<id>/file/` | `download=1` 下载，否则内联预览；写审计 |
| POST | `/api/recruitment/resumes/<id>/retry-structure/` | 重试或补建简历结构化任务 |
| 岗位依据 GET/POST | `/api/recruitment/job-documents[/<id>/]` | `.doc/.docx/.xlsx`，版本化、职位绑定、归档恢复 |
| 岗位标准 GET/PATCH | `/api/recruitment/job-standards[/<id>/]` | job；仅 draft 可修改 |
| POST | `/api/recruitment/job-standards/generate/` | 根据当前岗位依据异步生成草稿 |
| POST | `/api/recruitment/job-standards/<id>/publish/` | 校验权重 100、硬性指标和证据后发布 |
| 结构化简历 GET | `/api/recruitment/structured-resumes[/<id>/]` | job, resume；不在简历列表返回全文 |
| 评分 GET | `/api/recruitment/resume-assessments[/<id>/]` | job, resume；返回维度证据与版本 |
| POST | `/api/recruitment/resume-assessments/score/` | job + resume_ids + request_id；批量幂等评分 |
| POST | `/api/recruitment/resume-assessments/<id>/rescore/` | 新 request_id 创建重评任务 |
| GET | `/api/recruitment/screening-results/` | `job` 必填；返回当前排名、AI 建议、HR 结论与通知状态的统一读模型 |
| POST | `/api/recruitment/screening-decisions/bulk/` | UUID request_id + 同岗位 application_ids + pass/fail + reason；只追加人工结论 |
| POST | `/api/recruitment/rejection-notices/prepare/` | decision_batch_id + UUID request_id + 中性 message；冻结未通过通知审批快照 |
| GET | `/api/recruitment/automation-plans/` | `job` 可选；返回岗位 Plan、当前不可变修订、运行和 effective_state |
| POST | `/api/recruitment/automation-plans/start/` | job + kind + config + UUID request_id + expected_control_version；原子开启或重新开启 |
| POST | `/api/recruitment/automation-plans/<id>/pause/` | UUID request_id + expected_control_version；写入暂停意图并 fence 旧代 |
| POST | `/api/recruitment/automation-plans/<id>/resume/` | UUID request_id + expected_control_version；沿用当前修订创建新代运行 |
| POST | `/api/recruitment/automation-plans/<id>/stop/` | UUID request_id + expected_control_version；协作式停止，可能返回 202/stopping |
| AI 任务 GET | `/api/recruitment/ai-tasks/` | job, resume, kind, status |
| POST | `/api/recruitment/ai-tasks/<uuid>/retry/` | 显式恢复失败/等待配置任务 |
| GET/POST/DELETE | `/api/recruitment/demo-data/` | 状态/加载/只清除演示数据 |
| GET | `/api/recruitment/dashboard/` | 招聘指标、简历智能处理计数、今日动作、风险、漏斗、趋势、任务 |

### 沟通、审批与执行

| 方法 | 路径 | 用途 |
|---|---|---|
| GET | `/api/recruitment/automation-approvals/` | 确认记录；支持 `status`、`action`、`job`、`automation_plan_revision`、`automation_generation` 精确过滤 |
| POST | `/api/recruitment/automation-approvals/<id>/approve/` | 检查过期、归属和额度后批准 |
| GET | `/api/recruitment/communication-actions/` | 沟通动作记录 |
| POST | `/api/recruitment/communication-actions/prepare/` | 生成打招呼/索简历/面试确认快照 |
| POST | `/api/recruitment/communication-actions/prepare-online-resume/` | 在线简历查看次数确认 |
| GET | `/api/recruitment/execution-batches[/<id>/]` | 确认执行队列与逐人步骤 |
| GET/POST | `/api/recruitment/rpa-tasks[/<id>/]` | 创建白名单任务或查看详情 |
| POST | `/api/recruitment/rpa-tasks/<id>/cancel/` | 取消待执行任务 |
| POST | `/api/recruitment/rpa-tasks/<id>/retry/` | 显式重试失败任务，生成新任务 |
| GET | `/api/recruitment/automation/summary/` | Worker、CLI、完成数和账号状态 |

### 流程编排与运行

| 方法 | 路径 | 用途 |
|---|---|---|
| GET/POST/PATCH | `/api/recruitment/workflows[/<id>/]` | 模板；禁止物理 DELETE，支持归档/恢复 |
| GET/POST/DELETE | `/api/recruitment/workflow-versions[/<id>/]` | 版本；仅无运行记录且非活动的草稿可删除 |
| POST | `/api/recruitment/workflow-versions/<id>/enable/` | 校验图并启用 |
| POST | `/api/recruitment/workflow-versions/<id>/run/` | dry_run/formal；formal 要启用、账号 ready、confirm=true |
| GET | `/api/recruitment/workflow-runs[/<id>/]` | 运行、节点和事件 |
| POST | `.../workflow-runs/<id>/pause/` | 暂停 |
| POST | `.../workflow-runs/<id>/resume/` | 恢复并推进 |
| POST | `.../workflow-runs/<id>/cancel/` | 取消 |
| POST | `.../workflow-runs/<id>/decision/` | node_id + approved + note |
| POST | `.../workflow-runs/<id>/retry/` | node_id；仅失败节点 |

### Worker 白名单

| 方法 | 路径 | 用途 |
|---|---|---|
| POST | `/api/recruitment/worker/heartbeat/` | upsert Worker 能力/在线状态 |
| GET | `/api/recruitment/worker/status-targets/` | 获取需要观察的活跃账号 |
| POST | `/api/recruitment/worker/status-observations/` | 批量回写登录/风控状态 |
| POST | `/api/recruitment/worker/tasks/lease/` | 原子租约最早待执行任务 |
| POST | `/api/recruitment/worker/tasks/<uuid>/event/` | 追加事件并续租 |
| POST | `/api/recruitment/worker/tasks/<uuid>/complete/` | 完成/失败，持久化归一化结果并推进业务 |

## 端点详细规则

### POST `/api/imports/`

- 请求：multipart `file`、`year`、`month`、`default_expected_days`。
- 校验：必须 `.xlsx`、≤10MB、月份 1–12；同 SHA-256 + 年月返回 409 和既有 batch。
- 成功：同步解析后返回完整 batch 201；解析失败保留失败批次与错误说明 400。

### PATCH `/api/results/<id>/`

- UI 只提交 leave/overtime/adjustment/note 等可编辑字段。
- Serializer 保存后必须调用规则重算，响应返回更新后的 `actual_days` 和 `rule_trace`。
- Viewer/Supervisor 不能写；确认使用独立 approve 动作并记录审核人/时间。

### POST `/api/recruitment/candidate-discoveries/import-selected/`

- `ids` 必须属于当前用户可操作账号且未过期。
- 平台 ID 优先；没有稳定 ID 时使用账号范围组合指纹。
- 重复导入复用 Candidate/Application，不把同名自动视为同一人。

### POST `/api/recruitment/communication-actions/prepare/`

- 请求包含账号、应聘 ID 列表、动作、消息快照；面试动作使用结构化邀请字段。
- 服务端重新检查账号授权和候选人归属，创建 draft approval，不直接发送。
- 批准后按候选人生成独立步骤；部分失败不得重复成功项。

周期被动同步产生的 `request_resume` 审批必须绑定当前 `automation_plan_revision` 与 `automation_generation`。招聘作业台只能显示当前岗位、当前修订和当前代际的 `draft` 审批；旧代审批即使仍可查询也不得批准。每次有效同步应幂等恢复已处理但未形成有效求简历动作的候选人来信，已有简历以及 `approved/pending/running/waiting_human/succeeded` 动作不得重新排队。

### GET `/api/recruitment/screening-results/?job=<id>`

- 仅返回当前用户可读取岗位中的未归档应聘；列表权限必须显式过滤，不能依赖对象权限自动套用。
- 每个应聘只绑定最新未归档简历、该简历最新结构化版本，以及当前 published 标准下对应的最新评分。旧标准评分不参与当前排名。
- 有可比分数的记录按 `total_score DESC, application_id ASC` 排名；无简历、未评分、处理中或失败记录继续返回，`rank=null`。
- 响应分别包含 `ai_state/assessment`、最新 `hr_decision`、`application.stage` 和最新未通过 `notification`，客户端不得相互推断。

### POST `/api/recruitment/screening-decisions/bulk/`

- 请求：`request_id`、`job`、`application_ids`、`decision=pass|fail`、必填内部 `reason`。所有应聘必须属于同一可写岗位；混入越权、归档或其他岗位 ID 时整批拒绝。
- 服务端在事务内锁定应聘并重新选择当前简历/评分，创建一个幂等批次和每人一条只追加决策。相同 request_id 与相同载荷返回既有结果；载荷变化返回 409。
- 决策绑定当时的简历和评分但允许二者为空；创建决策不修改 `JobApplication.stage`、不创建通知、不调用 Worker。

### POST `/api/recruitment/rejection-notices/prepare/`

- 仅接受一个当前最新结论仍为 `fail` 的 ScreeningDecisionBatch；所有应聘必须属于同一岗位、同一授权 BOSS 账号，且未进入面试、Offer、录用等禁止自动通知的后续阶段。
- 最终通知文案不能为空，且不得由服务端拼入分数、AI 建议、硬性条件失败或内部原因。准备只创建不可变审批，不直接发送。
- 批准时一次性校验并预占整批 `message` 额度，随后一次性物化全部步骤和 pending 任务；额度不足时不创建部分批次/任务。重复批准不得重复扣额或建任务。
- 新动作 `rejection_notice` 只更新动作/通知状态，不修改 HR 决策或招聘阶段。Worker 必须按稳定平台 ID 原子定位、复核和发送；适配器不具备该能力时返回 `waiting_human`，禁止按姓名回退。
- 每人独立记录 `pending/running/waiting_human/succeeded/failed/cancelled`。身份不匹配可转人工并继续安全项；登录、风控、CDP 错误或外发结果不确定时停止剩余批次且不得自动重试。

### POST `/api/recruitment/workflow-versions/<id>/run/`

- `request_id` 必填并幂等；`mode` 为 dry_run/formal。
- dry_run 不创建 RPA、审批或外发工作；仍会在人工门停留用于验证图。
- formal 只接受已启用版本、ready 账号和 `confirm: true`；可选职位必须属于该账号。

### POST `/api/recruitment/worker/tasks/<uuid>/complete/`

- 仅有效 Worker Token；任务必须处于当前租约可完成状态。
- 服务端而非 Worker 决定业务写入：归一化职位、发现池、沟通状态、PDF 归档和阶段推进。
- 不确定身份或文件路径越界返回错误/等待人工，不静默成功。

## 第三方集成

| 集成 | 方式 | 数据方向 | 安全边界 |
|---|---|---|---|
| BOSS CLI | 本机 Node 子进程，固定 JS 入口并以参数列表调用 | 职位/候选/会话读取；确认后的有限写动作 | 不执行 npm `.cmd/.bat/.ps1` shim；`shell=False`；最小环境；隔离资料目录；超时/编码归一化 |

### 主动寻访候选条件快照（2026-08-26）

`RecruitmentAutomationPlanRevision.config` 的主动寻访配置允许 `candidate_filters` 对象，字段固定为年龄区间、活跃度、性别、近期未看过、未与同事交换简历、牛人关键词、院校、专业、跳槽频率、求职状态和学历要求。服务端按白名单规范化枚举、长度和年龄上下界；未知值不能进入不可变修订。

规范化后的 `candidate_filters` 必须原样进入标准工作流搜索节点、`SearchCampaign.criteria` 与 `AutomationApproval.payload`，使草稿恢复、版本冲突、审批摘要和审计链看到同一份确定性搜索条件。当前固定 BOSS CLI 未暴露的筛选能力只保存和传递，不得在结果或日志中宣称已经应用到平台页面；适配器未来支持时从同一快照消费，不另建旁路配置。

| Chrome/Edge | 独立用户目录 + loopback CDP；会话链路使用 CLI 同版本 Puppeteer bridge | 人工登录、状态观察、职位/未读筛选、稳定身份核验、消息回执、附件 PDF | 受管端口/路径；bridge 只 disconnect 不 close；不绕验证；不使用日常资料 |
| 飞书打卡 Excel | 人工上传 `.xlsx` | 单向导入 | 类型/大小/哈希、原文件留档 |
| 模型服务 | 仅保存个人兼容 API 配置 | [待确认] 当前无实际调用端点 | Key 加密；不应默认发送候选人/员工敏感数据 |

### 被动会话同步回写契约（2026-08-26）

- `sync_conversations` Worker 结果中的每行会话必须携带 BOSS 会话 `external_id`、展示名、岗位、消息和附件；`application_id` 即使由 Worker 提供也不可信，服务端必须删除并重新解析。
- 服务端仅在稳定 ID 存在、岗位属于冻结 `allowed_job_ids` 且标题唯一匹配时创建或复用候选人、平台身份与应聘。兼容旧任务时，可把缺少稳定 ID 的行绑定到账号内既有且全局唯一的应聘，但不得据此创建新候选人或执行外发。
- 标准工作流首次同步携带 `backfill_conversations=true` 并读取岗位列表，但只打开未读或当前选中行；周期性 `passive_plan_scopes` 同步仍只读取未读。
- Worker 必须先在 BOSS 页面精确选择冻结职位，再切换未读/全部状态；账号共享的多个被动岗位逐岗位读取并按 stable ID 合并，任何职位筛选歧义或跨 scope 重复 stable ID 都失败关闭。
- `request_resume_by_external_id` 必须在同一次 Puppeteer bridge 执行中重新应用批准快照的职位 scope、刷新列表、按 stable ID 唯一解析、打开并复核选中行 stable ID、展示名和职位，再发送已批准话术并调用 BOSS 原生“求简历”；不得在定位后切回另一个 CLI 子进程执行写动作。
- 作业台只有在确认接口返回沟通批次且批次中至少存在一个 `pending` 执行步骤时，才能提示动作已排队；审批提交期间禁止同时停止或重启岗位计划，计划控制期间也禁止提交审批。
- Worker 的目标职位会话适配器必须在一次调用中按“精确职位 → 未读/全部 → stable ID”定位并点击，返回选中会话消息；不得先通过 CLI 切换账号级列表，也不得把 CLI 序号作为跨筛选快照的动作目标。同步调用必须把原始 `unread` 范围传到打开动作。
- 首次 `request_resume` 必须把文字发送和原生求简历拆开：发送后以选中 stable ID 下新增的精确己方消息作为成功回执，随后才允许求简历。缺少新增消息回执时任务进入 `waiting_human/external_result_uncertain`，不得自动重试或继续求简历。消息方向类既可能位于 `.message-item` 自身也可能位于后代，解析和回执必须兼容两种 DOM 形态。
- 会话读取、打开、发送、消息回执、原生求简历和附件下载由本地 `boss_chat_bridge.mjs` 通过固定 CLI 包内的 `puppeteer-core` 执行；bridge 输入为 JSON stdin，Node/脚本/包根均为固定 argv，继承最小账号环境。bridge 只能断开自身 CDP 连接，不得关闭受管浏览器。`request_resume` 成功回执必须明确包含 `greeting_verified`（首次联系时）、`resume_requested`、`request_acknowledged` 及与批准目标一致的 `observed_external_id`；`request_acknowledged` 只接受原生求简历确认后的 BOSS 非遥测 2xx 响应或明确成功提示。

### 独立招聘任务详情与可恢复删除（W16，2026-08-27）

- `RecruitmentAutomationPlan` 新增可空、索引字段 `archived_at`。该字段只表示业务任务从当前列表移除，不改变不可变 Revision、当前 Run、control version/generation 或任何审计对象。
- `GET /api/recruitment/automation-plans/` 默认只返回未归档 Plan；`archived=1` 只返回归档 Plan。详情读取遵循相同过滤和账号授权范围。
- `POST /api/recruitment/automation-plans/<id>/archive/` 仅允许 `stopped/failed/completed` 等终态且不存在活动租约的 Plan；否则返回 409。成功返回包含 `archived_at` 的完整 Plan。
- `POST /api/recruitment/automation-plans/<id>/restore/?archived=1` 清除 `archived_at`，不重新启动任务；`archived=1` 用于在归档查询范围内解析对象，重新运行仍须显式调用原子 start 命令。
- `POST /api/recruitment/automation-plans/start/` 发现既有归档 Plan 时在事务中恢复后开启；幂等请求、乐观版本、Revision 和 generation 规则不变。
- `RecruitmentAutomationPlanSerializer` 增加 `archived_at`。`WorkflowRunSerializer` 增加只读 `automation_plan` 与 `automation_plan_archived_at`，从 `automation_plan_revision.plan` 投影，供结果中心生成稳定任务详情链接和已删除过滤。
- 归档与恢复使用现有 `RecruitmentWritePermission` 和授权账号查询；其他用户的 Plan 继续返回 404。

### 主动寻访结果批量打招呼（W17，2026-08-27）

状态：`[x]` 读模型、准备/批准、顺序执行和完成回执契约已通过自动测试；真实 BOSS 外发回执需 HR 人工验收。

本功能不新增数据表和公开端点，复用现有沟通准备与审批 API，并扩展候选结果读模型。

#### GET `/api/recruitment/screening-results/?job=<id>` 扩展

每条 `results[]` 增加：

```json
{
  "greeting": {
    "eligible": true,
    "status": "not_requested",
    "reason_code": "",
    "reason_label": "",
    "action_id": null,
    "updated_at": null
  }
}
```

- `status` 为 `not_requested/draft/pending/running/waiting_human/succeeded/failed/skipped/cancelled` 之一；只投影最近有效的 `greet` 动作。
- `eligible=false` 的稳定原因包括 `stage_ineligible`、`stable_identity_missing`、`already_contacted`、`greeting_in_progress`；API 不返回 `external_id`、指纹或其他平台身份秘密。
- 资格仅用于 UI 选择解释。客户端不得依据 `eligible=true` 绕过准备接口的事务内复核。

#### POST `/api/recruitment/communication-actions/prepare/` 复用

批量打招呼请求：

```json
{
  "request_id": "uuid",
  "boss_account": 7,
  "application_ids": [11, 12],
  "action": "greet",
  "message": "你好，我们正在招聘相关岗位，想和你进一步沟通。",
  "invitation": {}
}
```

- `application_ids` 必须为当前用户可写、同一岗位、同一 BOSS 账号的 1–100 个未归档应聘；整批只接受一个 `message`，规范化后复制到所有动作快照。
- 服务端锁定并重新验证每个应聘的资格。任一目标已进入不适合新联系的阶段、缺少该账号平台 stable ID、已成功打招呼或已有活动打招呼动作时，整批返回 400 字段错误，不创建部分审批；客户端刷新读模型后重新选择。
- 相同 `request_id` 只有在账号、动作、候选范围和统一话术完全一致时才返回原审批，否则返回 400。同一批准记录的 approve 可安全重放，只复用既有批次和步骤，不重复建任务或扣额；审批 `items` 继续冻结候选人、应聘、职位、账号、stable ID、来源和统一话术。

#### POST `/api/recruitment/automation-approvals/<id>/approve/` 复用

- 继续返回完整 `batch`。前端只有在 `batch.id` 存在且至少一个步骤为 `pending` 时提示“已加入执行队列”；不得把批准成功等同于外发成功。
- 批次逐项串行创建 `RpaTask(action=greet)` 并按 `contact` 指标记账。成功项不重复，身份可确定地不可执行时进入 `waiting_human`，外部结果不确定时停止剩余项且不自动重试。

#### Worker 打招呼回执

成功 `result` 至少包含：

```json
{
  "verified": true,
  "greeting_verified": true,
  "expected_external_id": "stable-id",
  "observed_external_id": "stable-id"
}
```

- Worker 必须在同一受管 CDP 原子动作中恢复来源和职位范围、刷新候选列表、按 stable ID 唯一定位并复核展示名后执行。姓名、组合指纹和列表序号都不能代替 stable ID。
- `greeting_verified` 缺失、stable ID 不一致、验证码/风控或点击后结果未知均不得回写成功；其中结果未知使用 `external_result_uncertain` 并创建人工核查事项。
- 核验成功后服务端推进应聘阶段为 `greeted`，并只解决同一应聘、同一岗位、同一 BOSS 账号当前开放的 `greeting_required` 人工事项；其他人工事项不受影响。
