# Round 1 Changelog

## Token 与页面层级

- `frontend/src/views/recruitment/RecruitmentAdminView.vue:1196` — 将页面局部颜色、间距、圆角、阴影、字号和动效统一映射到 `DESIGN.md` token；品牌色改为全局 `--teal / --teal-dark`，移除原自定义深绿体系。
- `frontend/src/views/recruitment/RecruitmentAdminView.vue:1271` — 页头标题收敛为 27px 考勤页面层级，保留无卡片背景的页面标题、说明和低强调刷新动作。
- `frontend/src/views/recruitment/RecruitmentAdminView.vue:1287` — 子导航改为纯文本 Tab：透明背景、底部分割线、选中态 2px 品牌色下划线，不再使用白色圆角卡片和绿色填充块。
- `frontend/src/views/recruitment/RecruitmentAdminView.vue:1392` — 每个子页的 `.admin-section` 成为唯一主面板；区块头改为面板内标题行并与内容共享边界，隐藏无业务价值的英文 section kicker。

## 列表与信息密度

- `frontend/src/views/recruitment/RecruitmentAdminView.vue:1430` — BOSS 账号由双列卡片网格改为单面板内的分割线列表行；账号、状态、技术 meta、业务指引和行操作在同一行对齐。
- `frontend/src/views/recruitment/RecruitmentAdminView.vue:1476` — CDP 端口、隔离目录和最近检查降为 10–12px 弱文字；登录状态与下一步使用文字状态和轻量左侧状态线，保持 3 秒内可识别。
- `frontend/src/views/recruitment/RecruitmentAdminView.vue:1502` — 账号、流程、模型行和重复空态动作的实心主操作统一降级为描边次按钮；页级“添加账号 / 新建高级流程 / 新增自定义模型”等仍是唯一高强调动作。
- `frontend/src/views/recruitment/RecruitmentAdminView.vue:1583` — 流程方案统一为 64px 起的分割线列表行，移除逐条圆角卡片感；高级画布作为主面板内的连续区域展开。
- `frontend/src/views/recruitment/RecruitmentAdminView.vue:1606` — 模型档案统一为分割线列表行；当前模型仅用左侧品牌线和轻状态标识表达，API 地址与 Key 信息保持弱层级。
- `frontend/src/views/recruitment/RecruitmentAdminView.vue:1621` — 系统诊断由四张卡片改为主面板顶部紧凑状态条，使用状态圆点、文字和列分隔，最近任务表格继续在同一面板内展示。
- `frontend/src/views/recruitment/RecruitmentAdminView.vue:1534` — 职位同步控制台、同步进度和职位表格移除各自外层卡片边界，以面板内分割线形成连续工作流。

## 状态、响应式与可访问性

- `frontend/src/views/recruitment/RecruitmentAdminView.vue:1352` — Worker/CLI 阻塞、成功、警告、错误反馈改为面板内 inline notice，保留原有 role、文案和恢复动作。
- `frontend/src/views/recruitment/RecruitmentAdminView.vue:1334` — 为按钮、Tab、分段切换和文本动作补齐统一品牌焦点环，普通 hover 不再上浮。
- `frontend/src/views/recruitment/RecruitmentAdminView.vue:1641` — 1050px 下账号行转两列、诊断条转两列；720px 下统一转单列并堆叠操作组，页面不产生横向溢出。
- `frontend/src/views/recruitment/RecruitmentAdminView.vue:1696` — `prefers-reduced-motion` 下关闭按钮、Tab 和骨架的非必要动效。

## 功能边界

- 未修改 `<script setup>`、API、状态管理、事件处理、生命周期逻辑、`data-test` 或原有交互语义。
- 未修改其他源文件。

## 验证

- `npm test -- src/views/recruitment/RecruitmentAdminView.test.js --configLoader runner` — 21/21 测试通过。
- `npm run build` — 生产构建通过；仅保留既有 ECharts chunk 超过 500 kB 的提示。

## 未处理项

- 本轮按 Generator 边界未生成 after 截图，也未修改全局组件；由主流程在运行态截图后交给独立 Evaluator 评分。
