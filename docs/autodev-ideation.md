# 西鸣人事管理系统 — 功能发现（逆向生成）

> 来源：从现有代码库逆向生成 | 生成时间：2026-08-24

## 产品定位

面向办公室本地与局域网环境的人事运营系统，把招聘、人员档案和考勤核算放在同一套登录、权限、数据与审计基础上。产品当前的差异化不在通用 HR 表单，而在两项高风险工作的可控自动化：打卡文件规则核算，以及 BOSS 招聘动作的人工确认、幂等执行和留痕。

产品现状更接近“两套完成度较高的垂直工作台共用一个壳”，尚未完全成为以员工生命周期和每日任务为中心的 People OS。

## 用户画像

- 系统管理员：初始化本地环境、维护账号与系统可用性。
- HR：维护人员与规则，处理考勤核算，推进招聘并监督自动化。
- 部门主管：代码中已有角色和部门字段；[待确认] 当前是否期望只查看本部门数据。
- 只读用户：查看看板、列表与业务结果，不执行写操作。
- [推断] 主要客户是 10–200 人、偏好本地数据保存且招聘流程依赖 BOSS 的中国中小企业。

## MVP 功能清单

### 平台层功能

| 编号 | 功能 | 描述 | 完成度 | 代码位置 |
|---|---|---|---|---|
| P1 | 本地部署与会话认证 | Windows 一键初始化/启动、局域网访问、Django Session + CSRF | [x] 完整 | `scripts/`, `backend/config/`, `backend/attendance/views.py` |
| P2 | 角色权限骨架 | Admin、HR、Supervisor、Viewer；读写权限分离 | [~] 部分 | `backend/attendance/models.py`, `backend/attendance/permissions.py` |
| P3 | 统一数据与文件存储 | SQLite 默认、PostgreSQL 可选、上传文件与 PDF 留档 | [x] 完整 | `backend/config/settings.py`, `backend/*/models.py` |
| P4 | 审计与可恢复生命周期 | 招聘审计、任务事件、阶段历史、管理后台归档/恢复与受控永久删除 | [x] 2026-08-25 管理后台入口与删除边界验收完成 | `backend/recruitment/models.py`, `services/lifecycle.py`, `RecruitmentAdminView.vue` |
| P5 | 安全自动化运行时 | 隔离浏览器、Worker 租约、人工确认、额度、幂等与证据 | [x] 代码完整 / 真实隔离窗口已验收，账号扫码待用户完成 | `backend/recruitment/rpa/`, `services/`, `worker_api.py` |
| P6 | 统一前端壳与设计系统 | Vue SPA、模块导航、本地图标、表格/抽屉/弹窗模式 | [x] 完整 | `frontend/src/components/`, `styles.css` |
| P7 | 个人模型档案与切换 | 加密保存多个兼容模型配置，在 Shell 或管理后台明确切换当前模型 | [x] 2026-08-25 完成 | `backend/accounts/`, `ModelSwitcher.vue`, `RecruitmentAdminView.vue` |
| P8 | 招聘总览与三工作区 | 以跨岗位看板分流，以作业台、结果中心、管理后台完成任务 | [x] 2026-08-25 看板入口恢复，三工作区全栈与生命周期验收通过 | `frontend/src/views/recruitment/`, `navigation.js` |

### 场景层功能

| 编号 | 功能 | 依赖 | 完成度 | 代码位置 |
|---|---|---|---|---|
| W1 | 人员档案、标签与考勤策略 | P1, P2, P3 | [x] 完整 | `EmployeesView.vue`, `SettingsView.vue`, `attendance/models.py` |
| W2 | 飞书打卡 Excel 导入与人员匹配 | P1, P3 | [x] 完整 | `ImportsView.vue`, `attendance/services.py` |
| W3 | 跨日打卡疑似人工审核 | W2, P4 | [x] 完整 | `SuspicionsView.vue`, `resolve_cross_day` |
| W4 | 月度结果调整、确认与 Excel 导出 | W1–W3 | [x] 完整 | `ResultsView.vue`, `attendance/exporter.py` |
| W5 | 跨月/部门考勤看板 | W4, P6 | [x] 完整 | `DashboardView.vue`, `dashboard_view` |
| W6 | BOSS 账号和职位管理 | P2, P5 | [x] 真实 Worker、双账号隔离窗口与等待登录状态已验收 | `RecruitmentAdminView.vue`, `backend/recruitment/rpa/` |
| W7 | 推荐、搜索、深度匹配与候选人入库 | W6, P5 | [x] 代码完整 / 外部依赖 | `RecruitmentCandidatesView.vue`, `services/discovery.py` |
| W8 | 候选人阶段与招聘看板 | W6, W7, P4 | [x] 完整 | `RecruitmentPipelineView.vue`, `RecruitmentDashboardView.vue` |
| W9 | 沟通批次、简历索取/保存与面试邀约 | W7, P5 | [x] 2026-08-27 被动会话 stable ID、文本/附件解耦、持续监听、真实应聘建档与求简历链路验收完成；标准被动计划以 HR 点击开始作为当前 revision/generation 的一次性授权，不再二次确认，身份/附件/结果不确定仍失败关闭 | `rpa/cli.py`, `rpa/boss_chat_bridge.mjs`, `services/communications.py`, `services/conversation_ingestion.py`, `worker_api.py`, `RecruitmentTaskDetailView.vue` |
| W10 | 人工确认的招聘流程编排 | W6–W9, P5 | [x] 完整 | `WorkflowCanvas.vue`, `services/workflow_runtime.py` |
| W11 | 演示数据与 PDF 简历预览 | P3, P6 | [x] 完整 | `recruitment/demo_data.py`, `RecruitmentDemoMenu.vue` |
| W12 | 招聘记录归档与恢复 | P4 | [x] 管理后台当前/归档、恢复与确认交互完整 | `ArchivableViewSetMixin`, `ArchiveConfirmModal.vue`, `RecruitmentAdminView.vue` |
| W13 | 候选排名、人工初筛与未通过通知 | W8, W9, P5 | [x] 2026-08-26 完成；AI 建议与 HR 结论分离，通知安全队列已验收 | `services/screening.py`, `RecruitmentResultsView.vue` |
| W14 | 岗位招聘任务停止、修改与重新开启 | W6–W10, W13, P5 | [x] 2026-08-26 完成；持久化方案、不可变修订、协作式停止与代际隔离已验收 | `services/automation_plans.py`, `RecruitmentOperationControl.vue` |
| W15 | 主动寻访候选条件 | W7, W14, P5 | [~] 2026-08-26 实现作业台白金展开表单、草稿恢复与不可变条件快照；平台实际筛选受固定 BOSS CLI 能力约束 | `RecruitmentWorkbenchView.vue`, `services/automation_plans.py`, `services/standard_workflows.py` |
| W16 | 招聘任务集合、独立详情与连续建任务 | W9, W13–W15, P4–P6 | [x] 已完成（2026-08-27）；执行成功进入招聘任务集合，作业台重置后可继续创建其他岗位任务，HR 再从卡片进入独立详情；结果中心提供可见的跨岗位任务集合，并支持停止、修改、可恢复删除与结果深链，终态任务可直接从卡片确认删除；同日完成任务集合、详情和业务结果的控件层级、文案密度与响应式打磨，任务集合改为 3/2/1 列内容卡片，外层页面锁定可用视口且卡片区独立纵向滚动，并删除重复统计摘要与当前/已删除整行切换，运行详情默认使用业务步骤和独立人工处理卡，不再暴露节点键与事件日志 | `RecruitmentTasksView.vue`, `RecruitmentTaskDetailView.vue`, `RecruitmentResultsView.vue`, `WorkflowRunPanel.vue`, `RecruitmentWorkbenchView.vue`, `RecruitmentAutomationPlan` |
| W17 | 主动寻访结果批量打招呼 | W7、W9、W14–W16、P5 | [x] 已完成（2026-08-27）；在主动寻访结果中按岗位勾选候选人、整批只确认一份统一话术，复用不可变审批、逐项顺序执行、账号级 stable ID 复核、额度和审计链；已联系、无 stable ID、跨岗位和结果不确定项失败关闭或转人工，历史结果可回看；真实 BOSS 账号外发保留 HR 人工验收 | `RecruitmentResultsView.vue`, `CommunicationConfirmDrawer.vue`, `services/communications.py`, `rpa/boss_chat_bridge.mjs` |
| W18 | 主动寻访 AI 合格目标闭环 | W13、W17、P5 | [x] 2026-08-27 已完成；最大上限按 AI 完成评分数计数，目标按 AI `advance` 合格数计数，并衔接现有人工批量打招呼链 | `SearchCampaign`, `SearchCampaignItem`, `services/search_campaign_intelligence.py`, `RecruitmentResultsView.vue` |
| W19 | 已保存简历原文件清理 | W9、W13、P3、P4 | [x] 2026-08-27 完成；在结果中心简历详情提供危险确认操作，物理删除原始 PDF/PNG 并移出当前结果，同时保留轻量元数据、历史评分、HR 结论和审计链；文件清理、冲突/越权/幂等和前端成功/失败状态已通过自动验收 | `services/resumes.py`, `ResumeViewSet`, `ResumeIntelligencePanel.vue`, `RecruitmentResultsView.vue` |
| W20 | 工作台招聘标准统一 | W14、W18、P4、P5 | [x] 2026-08-27 完成；Word/Excel 或手工要求均可作为主动寻访标准，Plan 原子启动时生成/确认不可变版本并贯穿 Revision、Run、Campaign，取消另行上传评分标准的重复入口 | `services/job_standards.py`, `services/automation_plans.py`, `services/workflow_nodes.py`, `RecruitmentWorkbenchView.vue` |
| W21 | 标准主动寻访开始授权 | W14、W18、W20、P5 | [~] 2026-08-27 实施中；点击开始即授权当前 Revision/Generation 内冻结的搜索条件和最大在线简历查看额度，后台保留不可变审批、额度和身份安全门，不再要求重复人工确认 | `services/automation_plans.py`, `services/workflow_nodes.py`, `RecruitmentWorkbenchView.vue` |

## 未完成或边界功能

| 功能 | 现状线索 | 判断 |
|---|---|---|
| 模型切换 | 个人多模型档案、显式当前模型、自定义新增与任务级不可变连接快照 | [x] 配置能力独立于后续 AI 业务能力 |
| 部门级主管权限 | `AccountProfile.department` 已存在，但 API 只区分 HR 写/登录读 | [~] 角色结构存在，数据范围未落地 |
| 账号管理 UI | README 提到角色，前端只有当前用户菜单 | [~] 初始化脚本可建管理员，日常管理缺口明显 |
| 入职衔接 | 录用候选人与 `Employee` 没有转换或关联 | [待确认] “招聘到考勤”目前是品牌叙事，不是完整流程 |
| 请假/加班/调休/出差 | 结果字段已预留，但没有审批和来源模型 | [~] 依赖人工调整 |
| 真实 BOSS 写动作 | README 明确要求指定测试候选人单人验收 | [待确认] 自动化测试不能替代生产验收 |
| 招聘工作入口 | 岗位依据、文字要求、执行方案与数量集中在作业台；运行、人工事项、候选人、简历和阶段集中在结果中心 | [x] 三工作区主链已完成；Word 标准提取与简历评分按产品决策保留下一阶段入口 |

## 产品经理评判

### 值得保留的产品资产

1. 安全自动化不是“脚本按钮”，而是审批快照、逐人执行、额度、幂等、身份复核和证据链组成的产品能力。
2. 考勤规则明确承认数据边界，把不可推断事项留给人工处理，可信度高。
3. 演示数据、空态、归档恢复和本地备份让内部工具具备可交付性，而不只是开发环境可运行。

### 主要产品问题

1. 首页默认进入考勤看板，招聘与考勤各自优化，但用户没有跨模块的“今日优先级”。
2. 招聘自动化工作区同时暴露账号、任务、批次、流程版本和运行状态，系统安全模型清楚，HR 的工作模型却不够直接。
3. “招聘到员工到考勤”的统一价值主张尚未被数据关系和用户流程兑现。
4. 角色模型和多数据库能力早于对应的完整用户价值，存在平台先行的范围膨胀；模型配置只承担连接管理，不冒充 AI 助手。

### 2026-08-25 招聘信息架构决策

- 高频业务按 HR 心智重组为“准备一次作业 → 执行 → 查看结果与处理例外”，不再按职位、候选人、流程、自动化和简历等技术对象平铺一级导航。
- 招聘一级入口为“招聘看板、招聘作业台、结果中心、管理后台”。看板承载跨岗位概览与分流；作业台承载岗位、画像/需求文件、文字要求、方案、数量与执行；结果中心承载运行、人工介入、候选人、简历、评分与阶段；管理后台承载职位同步、BOSS 账号、隔离浏览器、流程编排、模型和诊断。
- 已实现的职位同步、岗位文档、评分标准、工作流、RPA 审批、候选人、简历和评分领域能力继续复用；本轮不复制模型、不放宽安全门。
- 旧招聘 URL 作为兼容入口保留，定向到新工作区的对应视图，避免收藏和业务深链失效。
- 顶栏入口使用用户可理解的“切换模型”，而不是尚不存在对话能力的“Copilot”；当前模型是用户级配置，新增或切换不会改变历史评分记录所绑定的模型信息。
- [x] 2026-08-26 作业台交互由三段同屏调整为同路由四步向导：岗位与账号、招聘标准、执行方案、执行前检查逐步完成；岗位依据上传复用考勤模块的拖拽心智。执行方案页以“检查并开始执行”记录一次性启动意图，检查全部通过后自动调用原子 Plan 命令；刷新、深链、阻塞和失败不会意外启动，自动化安全门保持不变。
- [~] 2026-08-26 结果中心把候选人与简历合并为当前标准下的连续排名；AI 建议、HR 结论、招聘阶段和通知状态分离。批量未通过先保存人工结论，再通过专用、失败关闭的通知动作执行。

## 建议的后续功能

### 2026-08-27 W16 设计漂移修正

- 原实现把岗位唯一 `RecruitmentAutomationPlan` 直接当作任务卡，导致同一岗位的多次 Run 只显示最新一次，偏离“连续创建多个招聘任务”的用户心智。
- 修正后 Plan 保留为岗位控制面，任务集合改按正式 `WorkflowRun` 展示；每次执行持续保留独立卡片，单次删除只归档该 Run 的可见性。

| 优先级 | 建议 | 价值 | 验证方式 |
|---|---|---|---|
| P0 | 统一“今日工作台” | 把招聘、考勤、自动化风险按影响和时效合并排序 | 观察 HR 是否能在 30 秒内说出今天先做的 3 件事 |
| P0 | 录用转员工向导 | 真正打通招聘与考勤，减少重复录入 | 录用后 2 分钟内完成档案与策略配置 |
| P1 | 部门数据权限与账号管理 | 让主管/只读角色可安全落地 | 权限矩阵和跨部门越权测试通过 |
| P1 | 自动化“业务视图” | 默认展示待确认、受阻和业务结果，技术任务日志下钻 | 待确认处理时长和误操作率下降 |
| P2 | 请假/加班来源与审批接入 | 降低考勤月结人工调整 | 人工调整条目占比下降 |
| P2 | 基于明确任务的 Copilot | 先做候选人摘要、JD 差距和异常解释，不做泛聊天 | 每个 AI 输出有来源、可编辑且不直接外发 |
