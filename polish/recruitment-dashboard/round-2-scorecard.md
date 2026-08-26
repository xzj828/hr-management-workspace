# Scorecard: 招聘看板 — Round 2

## 评审范围

- 视觉证据：`round-2.png`、`round-2-full.png`
- 设计真值：`DESIGN.md`、`polish/design-tokens.md`
- 验收契约：`polish/recruitment-dashboard/sprint-contract.md`
- 实现证据：`frontend/src/views/recruitment/RecruitmentDashboardView.vue`、`frontend/src/router.js`
- 说明：`frontend/src/views/DashboardView.vue` 实际对应考勤看板；`/recruitment` 路由指向 `RecruitmentDashboardView.vue`，因此招聘看板实现审查以该文件为准。

## 评分

| 维度 | 分数(1-5) | 关键发现 |
|------|----------|---------|
| Design System Compliance | 4 | 主色、字体、15px 面板圆角、9px 控件圆角、标准边框/阴影和 4px 间距体系均通过 token 对齐；但组件仍定义了若干未在设计真值中逐项列出的派生 `color-mix` 表面色与局部尺寸 token，未达到零偏离的 pixel-perfect 级别（`RecruitmentDashboardView.vue:135-181`）。 |
| Visual Craft | 4 | 5 个 KPI 以 3+2 完整排布，第一项深色主 KPI 建立明确主次；4 个智能项以 2×2 完整呈现，整页对齐、留白和分隔稳定。全页长截图中次级图表和日志区域的标题/图例尺寸较克制，远距离扫描时辨识度略弱。 |
| Coherence | 3 | 正常态从 Shell、KPI、智能概览、今日工作/风险到职位、图表和自动化列表保持同一套扁平语言；但加载时直接显示零值内容，错误态只有 `form-error` 且没有重试动作，边缘态尚未完全遵循同一设计系统（`RecruitmentDashboardView.vue:64,66-75,77-130`）。 |
| Functionality Preservation | 5 | 5 个 KPI、4 个智能项、今日事项、风险、职位、漏斗和自动化入口均保留点击语义；旧路径由路由重定向至新工作区并保留 query。招聘看板与路由定向测试共 12/12 通过。 |
| **总分** | **16/20** | |

## 判定

**PASS**

总分达到 16/20，且无单项 ≤2。

## 验收核验

| 检查项 | 结果 | 证据 |
|---|---|---|
| 5 个 KPI 完整，3+2 布局 | 通过 | 两张截图均无截断；`RecruitmentDashboardView.vue:16-22,66-70,634-645` |
| 4 个智能项完整，2×2 布局 | 通过 | 两张截图均显示完整四项；`RecruitmentDashboardView.vue:25-30,72-75,647-662` |
| 主次层级 | 通过 | 首个 KPI 使用唯一深色高强调，其他 KPI 降级；今日工作为主列、风险为窄次列。 |
| 列表代替逐行卡片 | 通过 | 今日事项、风险、职位、漏斗、自动化均使用分隔线行；组合面板的子区块已移除重复边框、圆角和阴影（`RecruitmentDashboardView.vue:373-391,394-469,490-579,616-632`）。 |
| 跳转与功能 | 通过 | `go()` 统一调用 router；兼容入口在 `router.js:25-31` 重定向；Vitest 定向测试 12/12 通过。 |
| Token 使用 | 通过（非满分） | 主视觉值通过 `--rd-*` 映射到全局设计 token；仅保留精确标准面板阴影硬编码和少量派生/局部尺寸 token。 |
| 响应式 | 通过 | 1320px 为 KPI 3+2、智能项 2×2；1050px 双列收单列；720/520px 继续降为 2 列/1 列，并在 reduced-motion 下关闭动效（`RecruitmentDashboardView.vue:634-758`）。 |

## 非阻塞观察

1. 后续可为加载态增加局部骨架，并为错误态加入重试动作，使四态完全符合 `DESIGN.md`。
2. 若继续追求 5 分合规，可把派生表面色、尺寸和阴影提升为全局共享 token，减少页面内二次 token 层。
