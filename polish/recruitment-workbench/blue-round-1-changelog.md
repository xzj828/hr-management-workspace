# Round 1 Changelog：招聘作业台蓝色紧凑视觉

## 页面级 Token 与舞台

- `frontend/src/views/recruitment/RecruitmentWorkbenchView.vue:1637` — 将蓝色舞台、表面/状态色、焦点色、浮层阴影、宽度、密度和响应式尺寸集中到页面作用域的 `--wb-*` token 区；具体颜色规则不再散落 hex/rgb/hsl 值。
- `frontend/src/views/recruitment/RecruitmentWorkbenchView.vue:1723` — 仅为招聘作业台路由建立铺满内容区的平面蓝色舞台，页头、向导和内容统一以 `980px` 最大宽度居中；同步适配全局页面容器的桌面、900px 与 680px 内边距，避免横向溢出。
- `frontend/src/views/recruitment/RecruitmentWorkbenchView.vue:1974` — 主面板和检查面板保持白色、15px 圆角、标准边框，并使用契约记录的 `0 18px 48px rgba(15,23,42,.15)` 浮层阴影且无 hover 上浮。

## 导航、布局与密度

- `frontend/src/views/recruitment/RecruitmentWorkbenchView.vue:1854` — 将步骤向导从横向白色长卡改为蓝色舞台上的三个紧凑步骤按钮；当前、完成、hover、focus 与 disabled 状态均保持清晰。
- `frontend/src/views/recruitment/RecruitmentWorkbenchView.vue:2048` — 将职位/账号控件限制为匹配内容的双列宽度，避免短内容被无意义地拉满。
- `frontend/src/views/recruitment/RecruitmentWorkbenchView.vue:2200` — 桌面上传区压缩为 `168px`，移动端为 `160px`；textarea 最小高度压缩为 `96px`，并收紧区块标题与动作区间距。
- `frontend/src/views/recruitment/RecruitmentWorkbenchView.vue:2782` — 默认在可用空间足够时保持主区 + `304–320px` 检查栏；viewport `≤1050px` 或页面容器空间不足时收为单列，720px 下表单和操作组继续单列。

## 可读性与交互完成度

- `frontend/src/views/recruitment/RecruitmentWorkbenchView.vue:1455` — 两个 textarea 改为绑定 JavaScript placeholder 字符串，使 `\n` 解析为真实换行而不是 DOM 中的字面量。
- `frontend/src/views/recruitment/RecruitmentWorkbenchView.vue:2014` — 保留步骤标题的程序化聚焦，移除浏览器原生黑框，并为键盘 `:focus-visible` 提供 token 化焦点环。
- `frontend/src/views/recruitment/RecruitmentWorkbenchView.vue:2418` — 恢复可见的原生 radio 控件，使用 checked 圆点作为非颜色选中标志，并补齐 hover、focus、selected 四态。
- `frontend/src/views/recruitment/RecruitmentWorkbenchView.vue:1665` — 业务说明、阻塞原因、检查详情、处理链接和安全说明统一提升到至少 12px；10px 仅保留给 STEP、状态 meta 与版本 meta。

## 2026-08-26 用户补充

- 用户补充允许整页渐变、玻璃效果或更明显阴影，但不强制。本轮为保持最新契约的平面蓝色舞台与表单可读性，未使用渐变、玻璃或背景图；采用用户允许且契约已记录的柔和浮层阴影。

## 验证

- `frontend` — `npm test -- --run src/views/recruitment/RecruitmentWorkbenchView.test.js`：通过，1 个测试文件、32 个测试全部通过，退出码 0。

## 未处理项

- 本轮按 Generator 边界未截图、未自评；视觉评分与浏览器证据由独立 Evaluator/编排器完成。
