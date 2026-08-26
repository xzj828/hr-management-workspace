# Round 2 Changelog

## 修复容器宽度响应

- `frontend/src/views/recruitment/RecruitmentResultsView.vue:735` — 为结果中心根容器启用命名 inline-size containment，使页面布局基于侧栏占位后的实际内容宽度响应，而不是只看浏览器视口。
- `frontend/src/views/recruitment/RecruitmentResultsView.vue:1602` — 内容容器不宽于 1320px 时，筛选区固定为两列：岗位筛选占整行，任务运行与结果状态位于第二行并各自获得完整列宽。
- `frontend/src/views/recruitment/RecruitmentResultsView.vue:1611` — 同一容器宽度下，四个结果 Tab 固定为 2×2 网格，招聘进度不再依赖最右边缘才能发现。
- `frontend/src/views/recruitment/RecruitmentResultsView.vue:1626` — 原 1050px 与 720px 视口媒体查询迁移为结果中心容器查询；窄内容区会正确触发 KPI、任务区、候选人行和操作组收排。
- `frontend/src/views/recruitment/RecruitmentResultsView.vue:1664` — 720px 以下筛选改为单列，四个 Tab 仍保持 2×2 全量可见，不产生页面横向溢出。

## 收敛设计真值

- `frontend/src/views/recruitment/RecruitmentResultsView.vue:657` — 将正文、弱文字、软表面、状态底色和分割线别名全部映射回 DESIGN.md 的 Ink / Slate / Muted / Line / Paper / Canvas / Teal / Amber / Red 正式色表。
- `frontend/src/views/recruitment/RecruitmentResultsView.vue:720` — 移除骨架与进度条的装饰渐变及未定义绿色；骨架改为 Canvas 单色呼吸，进度统一使用品牌绿。

## 功能边界

- 未修改查询、筛选同步、路由、运行控制、人工处理、事件、`data-test` 或请求逻辑。
- 保留 Round 1 的连续筛选/KPI 上下文、Tab/结果单面板、10px 以上业务文字和全部候选人/运行功能。

## 验证

- `npm test -- RecruitmentResultsView.test.js` — 13/13 通过。
- `npm run build` — 生产构建通过；仅保留既有 ECharts chunk 大小提示。
- `git diff --check -- frontend/src/views/recruitment/RecruitmentResultsView.vue` — 通过。

## 未处理项

- 无。
