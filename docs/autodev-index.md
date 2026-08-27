# 西鸣人事管理系统 — 开发者地图

> 来源：从现有代码库逆向生成

## 一句话

面向本地/局域网 HR 的招聘与考勤工作台，重点提供可解释核算和人工在环的安全招聘自动化。

## 知识地图

| 需要了解 | 去哪看 |
|---|---|
| 产品定位、功能完成度与优先级 | → `autodev-ideation.md` |
| 架构、组件关系和技术决策 | → `autodev-design.md` § Architecture |
| 页面、流程、四态和视觉规范 | → `autodev-ui.md` |
| 数据模型、权限与端点 | → `autodev-api.md` |
| 编码约束和质量红线 | → `autodev-rules.md`（全文） |
| 原始招聘专项方案 | → `superpowers/specs/` |
| 原始实施计划 | → `superpowers/plans/` |
| 安装、运行、备份与真实账号边界 | → `../README.md` |

## 代码地图

| 区域 | 入口 |
|---|---|
| Vue 启动与路由 | `frontend/src/main.js`, `frontend/src/router.js` |
| 全局布局与导航 | `frontend/src/components/AppLayout.vue`, `frontend/src/navigation.js` |
| 前端请求与认证 | `frontend/src/api.js`, `frontend/src/stores/auth.js` |
| 考勤页面 | `frontend/src/views/*.vue` |
| 招聘页面 | `frontend/src/views/recruitment/*.vue` |
| 独立招聘任务详情 | `frontend/src/views/recruitment/RecruitmentTaskDetailView.vue`, `RecruitmentAutomationPlan` |
| Django 配置 | `backend/config/settings.py`, `backend/config/urls.py` |
| 考勤域 | `backend/attendance/` |
| 招聘域 | `backend/recruitment/` |
| 自动化 Worker | `backend/recruitment/management/commands/run_rpa_worker.py` |
| Windows 运维 | `scripts/*.ps1`, 根目录 `*.cmd` |

## 技术栈

Vue 3 + Vite 7 + Pinia + ECharts | Django 5.2 + DRF 3.16 | SQLite/PostgreSQL | Vitest + Django TestCase | npm + pip

## 核心约束

1. 外发或消耗额度的招聘动作必须经过服务端人工确认和不可变快照。
2. 组合指纹不是稳定平台身份，执行动作前必须重新核验候选人。
3. 验证码、风控、同名歧义和身份错位必须暂停或跳过，不能绕过。
4. 考勤不可从打卡文件推断的业务事实必须由人工输入。
5. 本地文件、数据库和用户已有文档不得在普通迭代中被破坏性覆盖。
6. 完整规则见 `autodev-rules.md`。
7. 作业台启动成功后进入独立任务详情；任务删除只归档可见性，运行历史和审计证据不得物理删除。
