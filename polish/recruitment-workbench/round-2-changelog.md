# Round 2 Changelog

## 修复 1440 桌面可用宽度

- `frontend/src/views/recruitment/RecruitmentWorkbenchView.vue:845` — 将宽屏检查栏宽度契约设为 304–320px，双列布局下不再允许执行栏退化为不可读窄列。
- `frontend/src/views/recruitment/RecruitmentWorkbenchView.vue:1556` — 新增 1500px 提前收列断点，覆盖固定应用侧栏后的 1440 桌面工作区；检查栏按 DOM 顺序保留在连续主面板之后，并占满可用宽度。
- `frontend/src/views/recruitment/RecruitmentWorkbenchView.vue:1568` — 单列桌面检查项使用三列紧凑网格，摘要、检查正文、处理入口和唯一“开始执行”按钮均保留完整宽度与可读文案。
- `frontend/src/views/recruitment/RecruitmentWorkbenchView.vue:1578` — 1050px 以下将检查项降为两列，同时维持主流程、检查栏和控件的 `minmax(0, 1fr)` 收缩契约。
- `frontend/src/views/recruitment/RecruitmentWorkbenchView.vue:1592` — 720px 以下将检查项和全部表单/方案/上传操作降为单列，并恢复逐项分隔线以维持移动端扫描节奏。

## 修复评审指出的隐藏与 Token 问题

- `frontend/src/views/recruitment/RecruitmentWorkbenchView.vue:856` — 移除根节点 `overflow-x: clip`，不再通过裁切掩盖布局错误；横向安全由网格断点、`min-width: 0` 与控件宽度约束实现。
- `frontend/src/views/recruitment/RecruitmentWorkbenchView.vue:806` — 删除未在设计真值中定义的 soft/focus 半透明颜色，状态、焦点、选中与回执仅复用 Canvas、Surface、Primary、Danger 等正式 token。

## 边界确认

- `frontend/src/views/recruitment/RecruitmentWorkbenchView.vue:548` — 本轮未修改 API、状态、上传、执行、恢复、事件绑定或 `data-test`；连续 STEP 01/02/03 主面板与唯一主按钮保持不变。

## 验证

- `frontend/src/views/recruitment/RecruitmentWorkbenchView.test.js:55` — `npm test -- RecruitmentWorkbenchView.test.js` 通过，7/7 tests passed。
- `frontend/package.json:8` — `npm run build` 通过，Vite 生产构建完成（仅保留既有 EChart 大 chunk 警告）。

## 未处理项

- 无。
