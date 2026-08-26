# Round 1 Changelog

## 建立结果中心 Token 系统

- `frontend/src/views/recruitment/RecruitmentResultsView.vue:655` — 在页面作用域集中定义 `--results-*` 颜色、字体、字号、间距、圆角、边框、阴影、动效与响应式布局尺寸；页面样式不再散落硬编码视觉值。
- `frontend/src/views/recruitment/RecruitmentResultsView.vue:655` — KPI 和页面正文统一为 Inter / 中文系统无衬线字体，移除 Georgia；业务正文与交互文字提升到 10–13px。

## 组件修改

- `frontend/src/views/recruitment/RecruitmentResultsView.vue:483` — 新增纯视觉 `results-overview` wrapper，将岗位/运行/状态筛选、历史链接提示、四项 KPI 和局部数据警告合并为连续上下文面板；KPI 改用分割线而非四张独立圆角卡片。
- `frontend/src/views/recruitment/RecruitmentResultsView.vue:527` — 新增纯视觉 `results-workspace` wrapper，让文本 Tab 与当前视图共享一个主面板；任务运行与主动寻访在同一结果面板内以中线分区，不再各自套圆角卡片。
- `frontend/src/views/recruitment/RecruitmentResultsView.vue:1005` — Tab 改为直接连接内容的下边线选中态，保留全部既有视图与计数。
- `frontend/src/views/recruitment/RecruitmentResultsView.vue:1144` — 人工事项、运行、寻访和候选人列表统一水平内边距与行分割线；状态、主信息和动作列重新对齐。
- `frontend/src/views/recruitment/RecruitmentResultsView.vue:470` — 页头“刷新结果”继续作为唯一常驻刷新动作并保持次按钮；全量失败态“重新加载”也降级为次按钮。
- `frontend/src/views/recruitment/RecruitmentResultsView.vue:1599` — 1050px 以下收为单列任务区和两列 KPI，720px 以下筛选/操作组堆叠、Tab 局部滚动，所有网格使用 `minmax(0, …)` 防止页面横向溢出。

## 功能边界

- 未修改查询、筛选同步、路由、运行控制、人工处理、事件、`data-test` 或请求逻辑。
- 候选人详情、简历详情、运行展开/处理、人工事项处理、进度和所有空态/错误态均保留。

## 验证

- `npm test -- RecruitmentResultsView.test.js` — 13/13 通过。
- `npm run build` — 生产构建通过；仅保留既有 ECharts chunk 大小提示。

## 未处理项

- 无。
