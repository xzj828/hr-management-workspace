# Recruitment Workbench — Reference Round 3 Changelog

## 组件修改

- `frontend/src/views/recruitment/RecruitmentWorkbenchView.vue` — 为持续存在的 `.workbench-main` 增加模板 ref；步骤导航在 `nextTick` 中直接将该容器的 `scrollTop` 复位为 `0`，随后聚焦当前步骤标题。未调用页面级滚动，也不依赖测试环境中的 `scrollTo`。
- `frontend/src/views/recruitment/RecruitmentWorkbenchView.vue` — 在 `≤720px` 将四个向导切换项锁定为同一宽高与对齐 footprint；04 检查列表保持两列紧凑网格并压缩摘要/检查间距，只在 `≤520px` 切为单列。字号、视觉 token 与 04 独立语义保持不变。

## 定向测试

- `frontend/src/views/recruitment/RecruitmentWorkbenchView.test.js` — 人为设置同一主工作区元素的正 `scrollTop`，覆盖 `standard → plan`、`plan → review` 以及左侧已开放步骤点击，均断言复位为 `0`；同时断言四个向导步骤、独立 review 区和六项检查结构继续存在。
- `npm test -- RecruitmentWorkbenchView.test.js` — 34 tests passed。

## 未处理项

- 无。本轮只处理内部滚动位置保留与 720px 下 04 页面纵向比例失衡问题。
