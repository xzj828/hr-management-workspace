# Scorecard: 结果中心 — Round 1

## 评分

| 维度 | 分数(1-5) | 关键发现 |
|------|----------|---------|
| Design System Compliance | 3 | 主色、系统字体、字号、间距、圆角与标准阴影已 token 化，KPI 明确使用系统无衬线；但组件仍自定义多组不在 DESIGN.md / design-tokens.md 中的色值与装饰渐变，尚非严格设计真值。 |
| Visual Craft | 3 | 单面板层级、留白、KPI 对齐和列表骨架已明显收敛，但标准桌面截图中“结果状态 / 全部状态”被截为“结果状 / 全”，四个 Tab 只显示三个，是肉眼可见的成品级缺陷。 |
| Coherence | 4 | 页头、连续筛选/KPI 区、Tab 和单一结果面板使用统一的边框、圆角、字阶和品牌绿；除桌面裁切造成的信息缺口外，整体保持同一种企业后台语言。 |
| Functionality Preservation | 3 | 源码保留人工事项、运行控制、候选人与招聘进度分支，但截图未显示“招聘进度”入口，且状态筛选文案不完整；当前截图无法证明四类功能在桌面端都可发现、可达。 |
| **总分** | **13/20** | |

## 判定

NEEDS_IMPROVEMENT

未达到 `总分 ≥ 16/20 且无单项 ≤ 2` 的 PASS 阈值。

## 具体缺陷

### Compliance 缺陷

1. `frontend/src/views/recruitment/RecruitmentResultsView.vue:659-680` — 虽然使用了页面局部变量，但 `#475569`、`#94a3b8`、`#edf1f4`、`#f8fafc`、`#f1f5f9`、多组软色及蓝色 active 色均未出现在 DESIGN.md / design-tokens.md 的正式色表中；按 rubric 不能视为所有视觉值均有精确设计依据。
2. `frontend/src/views/recruitment/RecruitmentResultsView.vue:729-730` — 骨架和进度条仍以硬编码色值定义渐变，尤其进度渐变属于 DESIGN.md 禁止的纯装饰性渐变方向，且引入了未定义的 `#5bc7b6`。

### Craft 缺陷

1. `polish/recruitment-results/round-1.png` 顶部筛选区右侧 — 标签“结果状态”实际只呈现“结果状”，选择值“全部状态”只呈现“全”；170px 最小列宽的源码意图（`RecruitmentResultsView.vue:712-714, 817-854`）没有兑现为可读的桌面结果。
2. `polish/recruitment-results/round-1.png` 结果面板 Tab 行 — 仅可见“需要人工 / 任务结果 / 候选人与简历”三个等宽 Tab，整行没有“招聘进度”；这不是轻微像素误差，而是完整导航项缺失。
3. 截图与当前源码不一致：源码在 `RecruitmentResultsView.vue:204-209, 528-529` 明确定义并遍历四个 Tab，且完整定义“结果状态 / 全部状态”；因此本轮截图可能来自未刷新构建或仍存在运行时裁切，不能据源码意图给成品加分。

### Coherence 缺陷

1. 筛选/KPI 连续上下文和 Tab/结果单面板的容器语言已经统一，但右侧筛选文案与第四个 Tab 的缺失破坏了完整、均衡的横向信息节奏；同一屏出现“源码完整、视觉不完整”的交付不一致。

### Functionality 缺陷

1. `RecruitmentResultsView.vue:208, 628-635` 保留招聘进度数据与面板代码，但标准桌面截图没有可见的“招聘进度”Tab，用户无法从截图所示界面发现该功能。
2. 人工功能入口和状态在截图中可见；运行功能至少有“任务结果”入口，源码也保留 `WorkflowRunPanel` 的暂停、恢复、取消、人工决策与重试绑定（`RecruitmentResultsView.vue:639-649`）。但当前轮没有交互证据证明入口点击及控制无回归，因此不能给 4–5 分。

## 已满足的关键验收项

1. `RecruitmentResultsView.vue:483-514` 将三个筛选和四个 KPI 收入同一 `results-overview`，截图也显示为连续上下文。
2. `RecruitmentResultsView.vue:924-930` 的 KPI 明确使用 `Inter, PingFang SC, Microsoft YaHei, system-ui`，未再引入 Georgia。
3. `RecruitmentResultsView.vue:694-700` 将页面业务文字控制在 10–13px、KPI 29px，未发现小于 10px 的业务正文或交互文字。
4. `RecruitmentResultsView.vue:527-636` 以一个 `results-workspace` 连接 Tab 与唯一活动结果区域；列表使用分割线，而非逐项卡片墙。

## 优先修复建议（最多 3 个最高优先级）

1. 先保证截图与当前源码来自同一最新构建；在标准桌面宽度重新渲染并确认四个 Tab 同时完整可见，若仍缺失，修复 `results-workspace/results-tabs` 的裁切或运行时样式覆盖。
2. 修复状态筛选的桌面渲染，使“结果状态”和“全部状态”逐字完整显示；用实际截图验证，不以 170px 源码最小宽度替代验收。
3. 收敛未被设计真值定义的页面局部颜色，去掉进度装饰渐变，优先复用 DESIGN.md / design-tokens.md 的正式颜色与单色品牌绿。
