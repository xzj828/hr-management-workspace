# Runtime Evidence: 招聘作业台 — Blue Round 2

## 运行环境

- 隔离预览：`http://127.0.0.1:8771/recruitment/workbench?job=1`
- 数据库：临时 SQLite `hr-polish-eval-01a03cbb.sqlite3`，未使用正式业务库
- 桌面视口：`1280 × 720`
- 响应式视口：`720 × 900`

## 桌面实测

| 步骤 | 核心测量 | 结论 |
|---|---|---|
| context | 白色主卡 `840 × 254px`，宽高比 `3.31:1`；Round 1 为 `968 × 254px`、`3.81:1` | 仅第一步收窄并居中，达到契约的 `800–860px` 目标；standard/plan 未被连带收窄 |
| standard | 主卡 `953 × 629px`；上传区 `168px`；页面高度 `911px` | 卡片密度、上传区高度与真实 placeholder 换行保持 |
| plan | 网格 `611px + 320px`；主卡高 `516px`；检查卡高 `563px`；页面高度 `845px` | 桌面双栏保持，检查卡没有重新落到主卡下方 |

- 三个步骤中，程序化聚焦后的 `h3` 均为 `box-shadow: none`，且原生 outline 已被关闭。
- context、standard、plan 页面均可通过步骤按钮正常切换；方案 radio 可通过键盘 Space 切换。
- 浏览器控制台：`0 error / 0 warning`。

## 720px 响应式与焦点实测

- 文档 `clientWidth = 705px`、`scrollWidth = 705px`，无水平溢出。
- plan 自动收为单列，主卡宽 `589px`。
- radio 本体保持 `18 × 18px` 与原生 checked 标记。
- radio 获得键盘焦点时：input `outline: none`、`box-shadow: none`；父方案卡仅显示一层 `2px` 青绿色圆角 outline，圆角 `9px`。
- 未再出现 Round 1 的方形双焦点套框。

## 截图证据

- `blue-round-2-context.png`
- `blue-round-2-standard.png`
- `blue-round-2-plan.png`
- `blue-round-2-plan-720.png`

## 自动化验证

- 定向 Vitest：`RecruitmentWorkbenchView.test.js`，`32/32` 通过。
- 完整前端 Vitest：`41/41` 个测试文件、`243/243` 个测试全部通过。
- 生产构建：`npm run build` 通过，Vite 共转换 `689` 个模块。
- `git diff --check -- frontend/src/views/recruitment/RecruitmentWorkbenchView.vue` 通过。
