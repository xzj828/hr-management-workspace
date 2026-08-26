# Scorecard: 招聘看板 — Round 1

## 评分

| 维度 | 分数(1-5) | 关键发现 |
|------|----------|---------|
| Design System Compliance | 3 | 核心字体、主色、15px 面板圆角、9px 控件圆角、边框与标准阴影已对齐，但页面仍定义多组 DESIGN.md 中没有的硬编码视觉值，并与全局同名样式形成两套规则。 |
| Visual Craft | 2 | 完整页整体对齐尚可，但 `round-1.png` 的核心 KPI 带和简历智能条发生肉眼可见的右侧裁切，信息层级在常规验收视口直接失效。 |
| Coherence | 3 | 全页已基本统一为扁平面板、分隔线列表和单一品牌绿，但同一页面在完整页与常规视口呈现出两种布局完整度，右缘残缺破坏了“One voice”。 |
| Functionality Preservation | 2 | 跳转实现与定向测试正常，但常规视口中第 5 个核心 KPI 的文案/数值/说明不可见，第 4 个智能入口文案不完整，属于核心数据与入口的可见性回归。 |
| **总分** | **10/20** | |

## 判定

NEEDS_IMPROVEMENT

未达到“总分 ≥16/20 且无单项 ≤2”；Functionality = 2 触发硬性否决。

## 具体缺陷（仅 NEEDS_IMPROVEMENT 时）

### Compliance 缺陷

1. `frontend/src/views/recruitment/RecruitmentDashboardView.vue:137-150` — 新增了 `#f8fafb`、`#f2faf8`、`#94a3b8`、`#edf1f3`、`#e8f7f4`、`#8c99a8` 等 DESIGN.md 未定义的硬编码颜色；按 rubric，无法获得 4–5 分的 token fidelity。
2. `frontend/src/views/recruitment/RecruitmentDashboardView.vue:180-183` 与 `frontend/src/styles.css:164,203-204` — scoped 的 5/4 列 token 覆盖了全局同组件的响应式列数，页面保留了互相竞争的两套布局规则；这也是截图间结果不一致的直接代码风险。
3. `frontend/src/views/recruitment/RecruitmentDashboardView.vue:339-343` — 智能项标题被强制 `overflow: hidden; text-overflow: ellipsis; white-space: nowrap`；验收要求是 4 项文案完整，而不是用截断掩盖布局不足。

### Craft 缺陷

1. `polish/recruitment-dashboard/round-1.png` 顶部 KPI 带右端 — 5 个核心 KPI 没有全部完整可见：“可用 BOSS 账号”只剩图标所在的窄片，标签、数值 `0` 和“登录状态正常”全部不可见；`round-1-full.png` 虽完整，但不能抵消常规视口失败。
2. `polish/recruitment-dashboard/round-1.png` “简历初筛进度”右端 — 第 4 项“建议进一步沟通”及“仍需 HR 决策”被裁切为残缺文本，4 个智能项未达到完整可见要求。
3. 常规视口右侧裁切让 KPI 卡宽度与智能项列宽突然失衡：前四张保持完整卡片，第五张成为窄残片；这是明显的对齐与间距崩坏，不符合专业设计工艺。

### Coherence 缺陷

1. 完整页中的 KPI 带、智能条、今日工作/风险合并面板、职位分隔线列表和主次分析区语言基本一致；但 `round-1.png` 的右侧残片使同级组件不再具有统一尺寸和信息结构。
2. 页面组件在 scoped 样式中重新建立整套 `--rd-*` token，同时全局 `styles.css` 仍保留同名组件的旧视觉与断点，导致不同视口命中不同优先级规则，难以保证统一输出。
3. 主次关系已比 baseline 清楚（首 KPI 深色、趋势区宽于漏斗、风险/任务使用列表），但核心带被裁切后，首屏主任务链条“指标 → 智能处理 → 今日工作”不再完整。

### Functionality 缺陷

1. `frontend/src/views/recruitment/RecruitmentDashboardView.vue:180,195` — 核心指标固定为 5 列，只在 720px 以下改为 2 列；验收截图对应的中间宽度没有收列/换行策略，造成第 5 个可点击 KPI 只剩图标，用户无法辨认其数据和目的。
2. `frontend/src/views/recruitment/RecruitmentDashboardView.vue:183,299,338-343` — 简历智能固定 4 列且禁止标题换行，在不足宽度时“建议进一步沟通”入口语义被截断；入口仍可点击不等于功能完整可用。
3. 跳转核验结论：5 个 KPI 的 `/recruitment/jobs|candidates|resumes|pipeline|automation`、4 个智能筛选、今日工作、风险、职位、漏斗与最近自动化均在代码中指向现有路由；`RecruitmentDashboardView.test.js` 定向运行 6/6 通过。但现有测试只验证 DOM 数量和部分 `router.push`，没有覆盖常规视口下的完整可见性，因此不能推翻上述回归。

## 优先修复建议（最多 3 个最高优先级）

1. 先修常规验收视口：按页面可用内容宽度为 KPI 增加 3+2 或其他不裁切的中间断点，并让智能条在文案不足时收为 2 列；用同尺寸 `round-1.png` 复验 5 个 KPI、4 个智能项的标题/数值/说明全部可见。
2. 移除智能项标题的强制单行截断，给文字列可换行或足够的最小宽度；不得以省略号代替完整业务文案。
3. 合并 `RecruitmentDashboardView.vue` 与全局 `styles.css` 中重复的招聘看板规则，改用单一权威 token/断点来源，并将非规范硬编码色值收敛到 DESIGN.md 已定义 token。
