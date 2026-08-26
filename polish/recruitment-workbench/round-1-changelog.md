# Round 1 Changelog

## 建立 Token 系统

- `frontend/src/views/recruitment/RecruitmentWorkbenchView.vue:806` — 将页面颜色、字体、间距、圆角、阴影、控件尺寸与动效集中为 `--wb-*` 变量，并严格映射 `DESIGN.md` 与 `polish/design-tokens.md`。

## 页面结构与层级

- `frontend/src/views/recruitment/RecruitmentWorkbenchView.vue:569` — 用一个 `workbench-layout` 包裹主流程与检查栏，并将 STEP 01/02/03 归并到同一个 `panel workbench-main` 中；未改动任何字段、事件或 `data-test`。
- `frontend/src/views/recruitment/RecruitmentWorkbenchView.vue:966` — 取消三步独立卡片外观，统一以主面板内边距和单线分隔呈现连续作业流程。
- `frontend/src/views/recruitment/RecruitmentWorkbenchView.vue:1076` — 将岗位依据上传区改为主面板内的扁平工具行，使用上下分割线替代虚线嵌套卡片。
- `frontend/src/views/recruitment/RecruitmentWorkbenchView.vue:1136` — 将“添加依据文件”固定为克制的描边次按钮，并将高级流程入口降为弱化文本链接。
- `frontend/src/views/recruitment/RecruitmentWorkbenchView.vue:1333` — 将右侧检查栏收窄为 304px 粘性摘要，先显示本次作业，再显示检查状态；就绪项仅保留图标与标签，阻塞项继续展示原因和处理入口。
- `frontend/src/views/recruitment/RecruitmentWorkbenchView.vue:1453` — 将“开始执行”设为页面唯一高强调实心按钮，禁用态仍通过紧邻提示解释阻塞原因。

## 响应式

- `frontend/src/views/recruitment/RecruitmentWorkbenchView.vue:1562` — 在 1050px 及以下切换为单列，检查摘要移到主面板之前并以双列紧凑排列检查项。
- `frontend/src/views/recruitment/RecruitmentWorkbenchView.vue:1582` — 在 720px 及以下将标题、上传工具、方案、表单与检查项全部收为单列，并为所有容器与控件补齐 `min-width: 0`/`max-width: 100%` 防止页面横向溢出。

## 验证

- `frontend/src/views/recruitment/RecruitmentWorkbenchView.test.js:55` — `npm test -- RecruitmentWorkbenchView.test.js` 通过，7/7 tests passed。
- `frontend/package.json:8` — `npm run build` 通过，Vite 生产构建完成（保留既有 EChart 大 chunk 警告）。

## 未处理项

- 无。
