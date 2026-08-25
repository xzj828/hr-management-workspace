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
| P4 | 审计与可恢复生命周期 | 招聘审计、任务事件、阶段历史、归档/恢复 | [x] 完整 | `backend/recruitment/models.py`, `services/lifecycle.py` |
| P5 | 安全自动化运行时 | 隔离浏览器、Worker 租约、人工确认、额度、幂等与证据 | [x] 代码完整 / 真实账号待验收 | `backend/recruitment/rpa/`, `services/`, `worker_api.py` |
| P6 | 统一前端壳与设计系统 | Vue SPA、模块导航、本地图标、表格/抽屉/弹窗模式 | [x] 完整 | `frontend/src/components/`, `styles.css` |
| P7 | 个人模型凭证 | 加密保存 API 地址、模型名和 API Key | [~] 仅配置 | `backend/accounts/`, `RecruitmentCopilotDrawer.vue` |

### 场景层功能

| 编号 | 功能 | 依赖 | 完成度 | 代码位置 |
|---|---|---|---|---|
| W1 | 人员档案、标签与考勤策略 | P1, P2, P3 | [x] 完整 | `EmployeesView.vue`, `SettingsView.vue`, `attendance/models.py` |
| W2 | 飞书打卡 Excel 导入与人员匹配 | P1, P3 | [x] 完整 | `ImportsView.vue`, `attendance/services.py` |
| W3 | 跨日打卡疑似人工审核 | W2, P4 | [x] 完整 | `SuspicionsView.vue`, `resolve_cross_day` |
| W4 | 月度结果调整、确认与 Excel 导出 | W1–W3 | [x] 完整 | `ResultsView.vue`, `attendance/exporter.py` |
| W5 | 跨月/部门考勤看板 | W4, P6 | [x] 完整 | `DashboardView.vue`, `dashboard_view` |
| W6 | BOSS 账号和职位管理 | P2, P5 | [x] 代码完整 / 外部依赖 | `RecruitmentAutomationView.vue`, `RecruitmentJobsView.vue` |
| W7 | 推荐、搜索、深度匹配与候选人入库 | W6, P5 | [x] 代码完整 / 外部依赖 | `RecruitmentCandidatesView.vue`, `services/discovery.py` |
| W8 | 候选人阶段与招聘看板 | W6, W7, P4 | [x] 完整 | `RecruitmentPipelineView.vue`, `RecruitmentDashboardView.vue` |
| W9 | 沟通批次、简历索取/保存与面试邀约 | W7, P5 | [x] 代码完整 / 真实写操作待验收 | `services/communications.py`, `services/resumes.py` |
| W10 | 人工确认的招聘流程编排 | W6–W9, P5 | [x] 完整 | `WorkflowCanvas.vue`, `services/workflow_runtime.py` |
| W11 | 演示数据与 PDF 简历预览 | P3, P6 | [x] 完整 | `recruitment/demo_data.py`, `RecruitmentDemoMenu.vue` |
| W12 | 招聘记录归档与恢复 | P4 | [x] 完整 | `ArchivableViewSetMixin`, `ArchiveConfirmModal.vue` |

## 未完成或边界功能

| 功能 | 现状线索 | 判断 |
|---|---|---|
| 招聘 Copilot | 仅保存模型凭证，没有对话、推荐或摘要端点 | [~] 配置入口先于产品能力 |
| 部门级主管权限 | `AccountProfile.department` 已存在，但 API 只区分 HR 写/登录读 | [~] 角色结构存在，数据范围未落地 |
| 账号管理 UI | README 提到角色，前端只有当前用户菜单 | [~] 初始化脚本可建管理员，日常管理缺口明显 |
| 入职衔接 | 录用候选人与 `Employee` 没有转换或关联 | [待确认] “招聘到考勤”目前是品牌叙事，不是完整流程 |
| 请假/加班/调休/出差 | 结果字段已预留，但没有审批和来源模型 | [~] 依赖人工调整 |
| 真实 BOSS 写动作 | README 明确要求指定测试候选人单人验收 | [待确认] 自动化测试不能替代生产验收 |
| Word 标准与简历智能初筛 | 当前只完成 PDF 简历归档；用户确认 Word 用户画像/招聘需求仅用于后续评分，不作为 BOSS 自动化上下文 | [~] 本阶段可见禁用入口已完成；上传、标准提取和评分整体后置 |

## 产品经理评判

### 值得保留的产品资产

1. 安全自动化不是“脚本按钮”，而是审批快照、逐人执行、额度、幂等、身份复核和证据链组成的产品能力。
2. 考勤规则明确承认数据边界，把不可推断事项留给人工处理，可信度高。
3. 演示数据、空态、归档恢复和本地备份让内部工具具备可交付性，而不只是开发环境可运行。

### 主要产品问题

1. 首页默认进入考勤看板，招聘与考勤各自优化，但用户没有跨模块的“今日优先级”。
2. 招聘自动化工作区同时暴露账号、任务、批次、流程版本和运行状态，系统安全模型清楚，HR 的工作模型却不够直接。
3. “招聘到员工到考勤”的统一价值主张尚未被数据关系和用户流程兑现。
4. 角色模型、Copilot 和多数据库能力早于对应的完整用户价值，存在平台先行的范围膨胀。

## 建议的后续功能

| 优先级 | 建议 | 价值 | 验证方式 |
|---|---|---|---|
| P0 | 统一“今日工作台” | 把招聘、考勤、自动化风险按影响和时效合并排序 | 观察 HR 是否能在 30 秒内说出今天先做的 3 件事 |
| P0 | 录用转员工向导 | 真正打通招聘与考勤，减少重复录入 | 录用后 2 分钟内完成档案与策略配置 |
| P1 | 部门数据权限与账号管理 | 让主管/只读角色可安全落地 | 权限矩阵和跨部门越权测试通过 |
| P1 | 自动化“业务视图” | 默认展示待确认、受阻和业务结果，技术任务日志下钻 | 待确认处理时长和误操作率下降 |
| P2 | 请假/加班来源与审批接入 | 降低考勤月结人工调整 | 人工调整条目占比下降 |
| P2 | 基于明确任务的 Copilot | 先做候选人摘要、JD 差距和异常解释，不做泛聊天 | 每个 AI 输出有来源、可编辑且不直接外发 |
