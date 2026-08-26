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

对抗审查补充约束（2026-08-25）：`request_resume` 必须绑定已批准的不可变动作快照；主动搜索只产生候选摘要，打开/归档在线简历必须逐份计入 `resume_view`。外部动作只能由适配器在同一次原子调用中按平台稳定 ID（或平台原生等价标识）定位、复核并执行；组合指纹、展示名唯一或“先核验 ID、再按姓名执行”均不满足动作身份契约。缺少该能力时必须转人工提醒。批量任务的审批快照必须冻结候选集合或确定性搜索条件、最大数量和额度预算。

任务级自动化证据必须覆盖批量在线简历的每次尝试（目标稳定身份、核验结果、动作结果、错误与时间），并关联 `RpaTask`；额度记录需区分批准预算/预留值与实际尝试数。批量完成回写若任一身份、路径或归档失败，候选导入、简历归档、Campaign 统计等业务写入必须整体回滚，再单独写入 Task/Campaign 的失败终态。

任务级证据只持久化平台稳定 ID 的不可逆哈希、序号、时间、布尔核验值和受控结果码，不保存姓名、原始组合指纹、原始平台 ID、文件路径或 Worker 原始错误。主动寻访的所有终态（含 Worker 主动失败、回执预校验失败、取消及租约超时）都必须写额度账本；无法安全确认实际次数时使用 `actual_known=false`、`actual=null`、`unused=null` 和 `evidence_untrusted=true`，预留额度保持不退款。

通用 `POST /api/recruitment/rpa-tasks/` 仅允许 `check_status`、`sync_positions`、`sync_conversations`。沟通、在线简历、深度匹配和主动寻访必须通过各自专用确认/物化服务，并使用服务端规范幂等键和 Approval/Batch/Campaign/Workflow 关联；关联任务不得通过通用取消或重试拆离领域状态。主动寻访取消或租约超时时，Task、Campaign、额度证据、账号状态与关联 Workflow 必须在同一领域收口中结束。

`check_status + request_payload.open_login=true` 表示“打开或聚焦该账号的受管登录窗口”，不是自动登录。创建端点必须在账号行锁内复用同账号处于 `pending/leased/running` 的等价任务；Worker 或 CLI 不可用时返回可读的前置条件冲突，不新增永久排队任务。前端以 POST 响应中的任务为提交事实，刷新失败单独报告。账号状态、任务与自动化摘要由管理后台每 5 秒非重叠刷新。

Worker 执行 `open_login` 时异步启动固定 Node/JS CLI，轮询受管 CDP；CDP 就绪后写入账号隔离目录 marker、结束 CLI 父进程并返回 `succeeded + login_status=waiting_login`。CLI 进程 stdout/stderr 丢弃，终止采用 terminate→短等待→kill 的 best-effort 清理，不能把用户尚未扫码误报为系统失败。

`GET /api/recruitment/automation/summary/` 的 Worker 在线值由 `last_seen_at` 与服务端 TTL 计算，不直接信任历史 `status=online`。Worker 心跳在 CLI 不可用时仍应上报结构化能力状态，使 UI 能区分“Worker 未连接”和“Worker 在线但 CLI 不可用”。BOSS 登录 `ready` 只接受明确的招聘端已认证页面；公共、错误、未知页面一律保持未就绪。

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
| AI 任务 GET | `/api/recruitment/ai-tasks/` | job, resume, kind, status |
| POST | `/api/recruitment/ai-tasks/<uuid>/retry/` | 显式恢复失败/等待配置任务 |
| GET/POST/DELETE | `/api/recruitment/demo-data/` | 状态/加载/只清除演示数据 |
| GET | `/api/recruitment/dashboard/` | 招聘指标、简历智能处理计数、今日动作、风险、漏斗、趋势、任务 |

### 沟通、审批与执行

| 方法 | 路径 | 用途 |
|---|---|---|
| GET | `/api/recruitment/automation-approvals/` | 确认记录 |
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
| Chrome/Edge | 独立用户目录 + loopback CDP + Playwright | 人工登录、状态观察、目标核验、PDF | 受管端口/路径；不绕验证；不使用日常资料 |
| 飞书打卡 Excel | 人工上传 `.xlsx` | 单向导入 | 类型/大小/哈希、原文件留档 |
| 模型服务 | 仅保存个人兼容 API 配置 | [待确认] 当前无实际调用端点 | Key 加密；不应默认发送候选人/员工敏感数据 |
