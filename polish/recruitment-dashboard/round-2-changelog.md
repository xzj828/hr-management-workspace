# Round 2 Changelog

## Scorecard 修复

- `frontend/src/views/recruitment/RecruitmentDashboardView.vue:137` — 移除 Round 1 新增的非规范硬编码浅色，将悬停面、弱文字、软分割线和 Teal 浅底全部由 DESIGN.md 的 Paper / Muted / Line / Teal token 派生。
- `frontend/src/views/recruitment/RecruitmentDashboardView.vue:183` — 将 `.recruitment-dashboard` 声明为命名 inline-size 查询容器，使页面按实际内容宽度响应，不再依赖含侧栏的浏览器视口宽度。
- `frontend/src/views/recruitment/RecruitmentDashboardView.vue:194` — 提升本页 KPI 网格选择器为页面根容器直系选择器，明确覆盖 `styles.css` 中同名旧规则而不修改全局样式。
- `frontend/src/views/recruitment/RecruitmentDashboardView.vue:296` — 提升简历智能网格选择器为页面根容器直系选择器，避免全局同名响应式规则改变本页列数。
- `frontend/src/views/recruitment/RecruitmentDashboardView.vue:337` — 删除智能项标题的 `nowrap + ellipsis`，允许中文业务标签自然换行并完整展示。
- `frontend/src/views/recruitment/RecruitmentDashboardView.vue:634` — 内容容器不超过 1320px 时，5 个 KPI 使用六列网格组成 3+2 布局；后两项各占半行，完整保留标签、数字、说明和点击区域。
- `frontend/src/views/recruitment/RecruitmentDashboardView.vue:647` — 内容容器不超过 1320px 时，4 个简历智能入口改为 2×2，并同步调整内部横纵分割线。
- `frontend/src/views/recruitment/RecruitmentDashboardView.vue:665` — 将工作区与分析区的 1050px 收列策略改为容器查询，保留主次关系并规避全局 viewport 规则竞争。
- `frontend/src/views/recruitment/RecruitmentDashboardView.vue:678` — 内容容器不超过 720px 时 KPI 使用两列且第 5 项占满末行；不超过 520px 时 KPI、智能项和今日工作统一收为单列，避免横向溢出。

## 功能保持与验证

- `frontend/src/views/recruitment/RecruitmentDashboardView.vue:1` — 未修改指标、API、跳转、空态、事件或任何 `data-test`；Round 2 仅调整 scoped CSS。
- `frontend/src/views/recruitment/RecruitmentDashboardView.test.js:40` — 定向 Vitest 通过：6 tests passed。
- `frontend/package.json:8` — `npm run build` 通过，684 个模块完成转换；仅保留既有的大 chunk 体积提示。

## 未处理项

- 无。
