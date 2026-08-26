# 招聘工作区 Baseline 评估报告

## 2026-08-26 招聘作业台参考图重做基线

用户明确否决上一版终态，并提供新的构图硬标准：高饱和青蓝舞台、居中统一大卡、左浅青步骤区、右白工作区。独立评审将当前失败版重新评为：

| 页面 | Compliance | Craft | Coherence | Functionality | 总分 | 状态 |
|---|---:|---:|---:|---:|---:|---|
| 招聘作业台（当前失败版） | 3 | 2 | 2 | 4 | 11/20 | NEEDS_IMPROVEMENT |

当前 `840 × 254px` context 卡宽高比约 `3.3:1`，而参考主卡约 `1.26:1`；浅灰蓝背景、横向步骤条与独立检查侧卡均不再作为可接受方向。详细证据见 `recruitment-workbench/reference-rework-baseline-scorecard.md`。

---

视觉真值：现有考勤模块 + 根目录 `DESIGN.md`。

| 页面 | Compliance | Craft | Coherence | Functionality | 总分 | 状态 |
|---|---:|---:|---:|---:|---:|---|
| 管理后台 | 2 | 2 | 2 | 4 | 10/20 | NEEDS_WORK |
| 招聘作业台 | 2 | 2 | 3 | 4 | 11/20 | NEEDS_WORK |
| 结果中心 | 3 | 2 | 3 | 4 | 12/20 | NEEDS_WORK |
| 招聘看板 | 3 | 3 | 3 | 4 | 13/20 | NEEDS_WORK |

## 主要问题

1. 管理后台存在 Hero、子导航、Section Header、账号卡/诊断卡四层容器；按钮平均权重过高，技术字段占据业务首屏。
2. 作业台把连续的准备流程拆成多张独立卡，右侧摘要再次重复输入，视线在左右和上下频繁跳转。
3. 结果中心筛选、KPI、Tab、结果面板均为独立圆角容器，局部字号过小，操作入口密集。
4. 招聘看板视觉比前三页克制，但 KPI、风险、岗位、漏斗、趋势、任务仍偏“仪表盘卡片拼贴”，与考勤看板的主次节奏不完全一致。

## 同尺寸截图证据

- 视觉参照：`polish/baseline/attendance-reference.png`
- 招聘看板：`polish/baseline/recruitment-dashboard-before.png`
- 招聘作业台：`polish/baseline/recruitment-workbench-before.png`
- 结果中心：`polish/baseline/recruitment-results-before.png`
- 管理后台：`polish/baseline/recruitment-admin-before.png`

截图均来自同一个已登录桌面浏览器、同一默认视口和真实本地数据。考勤看板采用“筛选工具条 → 页面标题/KPI → 主图表”的清楚节奏；招聘看板首屏同时出现 KPI、深色智能区、今日工作和风险区，权重相近。作业台首屏有三层白色容器且右侧检查栏重复主流程信息。结果中心把筛选、KPI、视图切换、内容面板各自包裹。管理后台虽内容不多，却仍使用页面 Tab 面板、Section Header 面板和两张账号卡，按钮与技术字段比业务状态更抢眼。

## 优先级

1. 管理后台
2. 招聘作业台
3. 结果中心
4. 招聘看板

当前评分已结合源码、真实 DOM 与上述同尺寸截图，可作为本轮视觉验收基线。
