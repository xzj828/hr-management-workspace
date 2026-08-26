# Round 3 Changelog

## 全页尺度动作发现性

- `frontend/src/views/recruitment/RecruitmentAdminView.vue:783` — 将“刷新状态”移入页标题行，按钮紧邻“管理后台”标题，不再落在全页最右侧。
- `frontend/src/views/recruitment/RecruitmentAdminView.vue:1417` — 所有子页标题行改为左对齐纵向结构；标题说明在前，当前/已归档切换与页级主动作紧随下一行。
- `frontend/src/views/recruitment/RecruitmentAdminView.vue:1353` — `.admin-header-actions` 改为左对齐，使账号页“当前 / 已归档 / 添加账号”在默认全页截图中处于可发现区域。

## 账号三行扫描结构

- `frontend/src/views/recruitment/RecruitmentAdminView.vue:1448` — 账号行重排为三列业务首行：账号与业务状态、最近检查、下一步指引；不再把任何操作放到最右侧列。
- `frontend/src/views/recruitment/RecruitmentAdminView.vue:1517` — 第二行独占完整动作区并左对齐，始终依次显示“聚焦/打开登录窗口、检查状态、归档”；按钮允许安全换行但不会被裁剪。
- `frontend/src/views/recruitment/RecruitmentAdminView.vue:1520` — 第三行保留原生“技术详情”，闭合态移除额外顶边框与内边距，仅保留低权重 summary；展开后才显示浏览器、CDP 与隔离目录。
- `frontend/src/views/recruitment/RecruitmentAdminView.vue:1448` — 账号行纵向间距收敛为 8px、上下内边距收敛为 12px，减少闭合技术详情造成的双倍行高。

## Token 与响应式复核

- `frontend/src/views/recruitment/RecruitmentAdminView.vue:1232` — 将控件高度、紧凑控件高度、Tab 高度与状态点尺寸定义为 scoped token；空态间距改用 28/34px 设计刻度。
- `frontend/src/views/recruitment/RecruitmentAdminView.vue:1649` — 诊断条的 30px/19px 硬编码改为现有 spacing token，状态点尺寸引用 scoped token。
- `frontend/src/views/recruitment/RecruitmentAdminView.vue:1669` — 1250px 以下仍保持“业务首行 / 动作第二行 / 技术详情第三行”，仅压缩业务列最小宽度。
- `frontend/src/views/recruitment/RecruitmentAdminView.vue:1690` — 720px 下页头、面板动作与账号内容依次单列堆叠；操作区保持左对齐并可换行，技术详情展开内容转为单列。
- 1440px 代码复核：三列业务首行最小内容宽度约 662px，动作独占整行，不依赖右侧剩余空间；页头与面板动作均位于标题附近。
- 720px 代码复核：账号 grid 使用单列命名区域，Tab 仅自身横向滚动，主页面不引入横向溢出。

## 保持项

- 保留文本 Tab、单主面板、分割线列表、自然留白和原生技术详情折叠。
- 未修改 API、状态管理、事件、生命周期、权限、`data-test` 或业务逻辑。
- 除 `RecruitmentAdminView.vue` 和本 changelog 外未修改其他文件。

## 验证

- `npm test -- src/views/recruitment/RecruitmentAdminView.test.js --configLoader runner` — 21/21 测试通过。
- `npm run build` — 生产构建通过；仅保留既有 ECharts chunk 超过 500 kB 的提示。

## 未处理项

- Round 3 Generator 未自行评分；全页 after 截图与独立 Evaluator 复核由主流程执行。
