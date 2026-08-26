# Runtime Evidence: 招聘作业台参考图重做 — Round 1

## 环境

- 隔离预览：`http://127.0.0.1:8771/recruitment/workbench?job=1`
- 临时验收数据库，不使用正式业务库。
- 桌面：`1280 × 720`；窄屏：`720 × 900`。

## 参考图核心构图实测

| 状态 | 主卡 | 左栏 / 右区 | 结果 |
|---|---|---|---|
| context | `950 × 638px`，比例 `1.49:1`，圆角 `32px` | `270px / 680px` | 从失败版 `3.3:1` 横条改为居中统一大卡；舞台实测 `rgb(0,191,193)` |
| standard | `950 × 848px`，比例 `1.12:1` | 主表单 `560px`，上传区 `164px` | 与 context 共用同一外框/左栏起始线；用途选择器不存在 |
| plan | `950 × 1361px`，比例 `0.70:1` | 主表单 `560px`；检查区并入主卡且无独立阴影 | 构图统一，但 plan 桌面纵向高度较大，交由独立 Evaluator 判断是否需固定外框/内部滚动 |

- 外框阴影：`0 24px 70px rgba(4,75,78,.23)`，只有主卡一层。
- context 表单为职位/账号纵向排列，控件与主动作位于同一右侧任务区。
- standard DOM 中 `[data-test="document-category"]` 为 `false`；上传固定 `persona` 由定向测试覆盖。
- plan 的执行前检查背景为 `rgb(242,251,251)`、`box-shadow: none`，不再是第二张浮动白卡。

## 720px

- 主卡 `589px` 单列，左栏折叠为 `165px` 卡内顶部步骤摘要，右侧工作区位于其下。
- `clientWidth = scrollWidth = 705px`，无页面水平溢出。
- 主卡仍是唯一统一外框，圆角 `28px`；纵向内容通过页面自然滚动。

## 交互与运行

- context → standard → plan 三步前进通过。
- 方案 radio 使用原生语义并可切换；诊断处理链接仍指向 `/recruitment/admin?section=diagnostics`。
- 浏览器控制台：`0 error / 0 warning`。

## 截图

- `reference-round-1-context.png`
- `reference-round-1-standard.png`
- `reference-round-1-plan.png`
- `reference-round-1-plan-720.png`

## 自动化

- 定向 Vitest：`1` 个文件、`32/32` 测试通过。
- 生产构建：通过，Vite 转换 `689` 个模块。
- 指定 `git diff --check`：通过（仅本机 LF/CRLF 提示）。
