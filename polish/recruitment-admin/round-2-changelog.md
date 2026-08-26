# Round 2 Changelog

## Top 1：恢复账号行全部动作

- `frontend/src/views/recruitment/RecruitmentAdminView.vue:1435` — 重设账号业务行列宽：为动作区预留至少 260px，账号、最近检查、下一步和动作形成稳定扫描顺序。
- `frontend/src/views/recruitment/RecruitmentAdminView.vue:1397` — 主面板取消 `overflow: hidden`，不再静默裁剪超宽的行级操作；表格和专用内部容器仍各自管理溢出。
- `frontend/src/views/recruitment/RecruitmentAdminView.vue:1501` — 账号 footer 允许合理换行并使用紧凑次按钮，确保“聚焦登录窗口 / 检查状态 / 归档”在默认桌面宽度全部可见、可点击。
- `frontend/src/views/recruitment/RecruitmentAdminView.vue:1654` — 新增 1250px 账号行断点：窄桌面将业务指引移至下一行，但动作仍保留在首行；1050px 与 720px 下继续安全重排而非裁剪。

## Top 2：技术详情渐进披露

- `frontend/src/views/recruitment/RecruitmentAdminView.vue:857` — 账号首行移除常驻浏览器、CDP 端口和隔离目录，只保留账号、业务状态、最近检查、下一步与操作。
- `frontend/src/views/recruitment/RecruitmentAdminView.vue:892` — 使用可键盘操作的原生 `<details>` / `<summary>` 新增“技术详情”，默认折叠浏览器类型、CDP 端口和隔离目录。
- `frontend/src/views/recruitment/RecruitmentAdminView.vue:1492` — 最近检查独立为弱 meta；`frontend/src/views/recruitment/RecruitmentAdminView.vue:1505` 为技术详情提供轻分割线、焦点态和展开后的紧凑三列布局。

## Top 3：状态色 Token 收敛

- `frontend/src/views/recruitment/RecruitmentAdminView.vue:1205` — 移除散落的状态浅色色值，改为从 surface 与 DESIGN.md 语义色派生 `--admin-*-soft`。
- `frontend/src/views/recruitment/RecruitmentAdminView.vue:1214` — 新增 success / warning / danger 三组统一语义边框变量，替代通知、阻塞条和模型反馈中的局部 `rgba(...)`。
- `frontend/src/views/recruitment/RecruitmentAdminView.vue:1358` — 全局提示、错误、Worker/CLI 阻塞和模型连接反馈统一引用 scoped 语义变量。

## 保持项

- 保留无卡片页头、文本 Tab、单一主面板、分割线列表和数据量较少时的自然留白，未回退为卡片墙。
- 未修改 API、状态管理、事件、生命周期、`data-test` 或权限逻辑。
- 除 `RecruitmentAdminView.vue` 和本 changelog 外未修改其他文件。

## 验证

- `npm test -- src/views/recruitment/RecruitmentAdminView.test.js --configLoader runner` — 21/21 测试通过。
- `npm run build` — 生产构建通过；仅保留既有 ECharts chunk 超过 500 kB 的提示。

## 未处理项

- Round 2 Generator 未自行评分；after 截图与独立 Evaluator 复核由主流程执行。
