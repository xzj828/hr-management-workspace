# Scorecard: 招聘作业台 — Blue Round 2

## 评审范围

本轮按绝对标准评审，只依据 `DESIGN.md`、结构化 token、2026-08-26 最新 Sprint Contract、当前组件代码、指定 baseline / Round 2 截图与运行时证据。未读取任何 Generator changelog，也未使用 git diff 或生成者自述作为结论依据。渐变、玻璃和额外装饰均为可选项；平面浅蓝舞台本身不构成扣分。

## 评分

| 维度 | 分数（1-5） | 关键发现 |
|---|---:|---|
| Design System Compliance | 4 | 页面级蓝色、白色 15px 圆角卡、指定浮层阴影、27/17/13/12/10px 字级与语义色均准确落地，颜色值只出现在页面 token 区；两处规则级固定尺寸仍未 token 化，因此未达到“零硬编码视觉值”的 5 分标准。 |
| Visual Craft | 4 | context 卡收至 840×254px 后比例与留白明显更均衡，standard 保持高效表单密度，plan 的 611+320 双栏和 720 单栏均对齐清楚；步骤当前态仍同时使用边框、白底、底线与实心编号，强调层数略多，尚非设计工作室级 5 分。 |
| Coherence | 4 | 蓝色舞台、白卡阴影、深墨主动作、青绿状态与圆角控件已形成同一视觉语言；标题与 radio 焦点也已回归同一套克制圆角表达，仅步骤当前态比其余状态稍显用力。 |
| Functionality Preservation | 5 | 三步切换、前进/后退、radio 键盘 Space 切换、禁用原因与处理入口均有运行证据；桌面及 720px 无水平溢出，console 为 0 error / 0 warning，定向测试 32/32 与生产构建通过，未观察到功能回归。 |
| **总分** | **17/20** | |

## 判定

**PASS**

总分达到 16/20，无单项低于 3，且 Functionality Preservation 为 5。

## 关键契约核验

| 核验项 | 状态 | 客观证据与判断 |
|---|---|---|
| context 仅自身收窄并居中 | 符合 | 运行实测为 `840 × 254px`，处于合同目标 `800–860px`，相较 Round 1 的 `968 × 254px` 明确改善。模板只在 `currentStep === 'context'` 时添加 `workbench-layout--context`（`RecruitmentWorkbenchView.vue:1312-1318`），该类在 `:1985-1988` 独立限制 840px 并居中。 |
| standard 未被连带收窄 | 符合 | 桌面实测主卡宽 953px、上传区高 168px；截图中仍使用接近 980px 内容线的双 textarea 布局，没有因 context 修复增加纵向长度。 |
| plan 桌面双栏与 720 单栏 | 符合 | 桌面实测 `611px + 320px`，与 `:1973-1977` 的主区 + 304–320px 检查栏一致；720px 实测主卡 589px 并收为单列，`clientWidth === scrollWidth === 705px`，没有横向溢出。 |
| h3 程序化 focus | 符合 | `:2037-2039` 仅关闭 h3 原生 outline，未再绘制 box-shadow；三张桌面截图中标题均呈普通区块标题，不再出现 Round 1 的标签式光晕。程序化 `focus()` 仍保留在 `:556-559`。 |
| radio 键盘焦点 | 符合 | input 保持 18×18px 原生圆形与 checked 标记（`:2430-2441`）；input 自身无 outline / shadow（`:2443-2446`），焦点只由父方案卡的 2px 青绿圆角 outline 表达（`:2420-2422`）。720px 截图中未见方形双框，Space 可切换。 |
| 蓝底、白卡、字号与质感 | 符合 | 三步均清楚显示平面浅蓝 gutter；主卡与检查卡为白色、15px 圆角、柔和浮层阴影。27px 页面标题、17px 区块标题、13px 正文、12px 业务说明与 10px STEP/meta 层级清楚。整体简约但不空洞，无需为未使用渐变或玻璃效果扣分。 |
| 颜色 token 收敛 | 符合 | 色值扫描只命中 `:1646-1668` 的页面级 `--wb-color-*` 定义及 `:1727` 的阴影 token；具体组件规则均引用变量，没有散落新增 hex/rgb/hsl。 |
| 可见交互与运行状态 | 符合 | 三步可达、操作和阻塞说明可见，console 无错误或警告；当前证据没有按钮失效、字段裁切、数据消失或响应式布局崩坏。 |

## Round 1 缺陷关闭情况

| 前轮缺陷 | Round 2 结论 |
|---|---|
| context 主卡 968×254px，过度横向 | **已关闭**：840×254px，且只影响 context。 |
| h3 焦点呈标题标签式光晕 | **已关闭**：截图与代码均为无 outline、无 shadow 的普通标题。 |
| radio 出现 input 方形框与父卡双焦点 | **已关闭**：只剩父卡单一 2px 圆角焦点，input 保持圆形语义控件。 |
| standard / plan 可能被修复连带收窄 | **未发生**：standard 953px；plan 611+320 双栏保持。 |

## 非阻断观察

1. `RecruitmentWorkbenchView.vue:2192` 的 `min-width: 148px` 与 `:2670` 的 `min-height: 32px` 仍是规则级硬编码尺寸；视觉上没有造成偏差，但阻止 Compliance 达到严格 5 分。
2. 当前步骤同时使用白底、青绿边框、底部短线和实心编号，状态非常清楚但略重；这是 4 分与 5 分之间的精修差距，不影响本轮 PASS。
3. 完整前端 Vitest 的统一 final sweep 仍应由最终验收阶段复核；该待补证据不是当前页面已发生运行回归的证据，也不降低本轮 Functionality 5 分判断。
