# Scorecard: 招聘作业台 — Blue Round 1

## 评审范围

本轮只依据 `DESIGN.md`、结构化 token、2026-08-26 最新 Sprint Contract、当前组件代码、四张本轮截图与运行时证据作绝对评审。渐变、玻璃与额外装饰均为可选项；当前使用平面蓝色背景本身不构成扣分。

## 评分

| 维度 | 分数（1-5） | 关键发现 |
|---|---:|---|
| Design System Compliance | 4 | 页面级蓝色、980px 上限、15px 白卡、指定浮层阴影、字体与颜色变量均准确落地；但步骤标题焦点呈现只解决了“非原生黑框”，尚未达到契约要求的精致状态。 |
| Visual Craft | 3 | 对齐和间距总体整洁，但 context 主卡实际为 968×254px（3.81:1），仍显著横向拉长；标题焦点光晕与窄屏 radio 方形焦点框肉眼可见，未达到专业成品级。 |
| Coherence | 3 | 蓝色舞台、白卡、青绿色状态与深墨主动作已形成统一主语言；然而当前步骤的四重强调、标题“标签框”以及 radio 的方框焦点是三种竞争的选中/聚焦表达，边缘状态仍有拼接感。 |
| Functionality Preservation | 5 | 三步前进/后退、原生 radio 切换、禁用原因、处理链接和响应式均有运行证据；桌面及 720px 无横向溢出，控制台 0 error/warn，定向测试 32/32 且生产构建通过。 |
| **总分** | **15/20** | |

## 判定

**NEEDS_IMPROVEMENT**

总分未达到 16/20。功能和主要视觉方向成立，但“卡片不要过分横向”这一用户目标，以及标题/radio 焦点态的完成度，仍未达到可停止打磨的标准。

## 最新契约逐项核验

| # | 状态 | 客观证据与判断 |
|---:|---|---|
| 1 | 符合 | `RecruitmentWorkbenchView.vue:1638,1734` 使用唯一页面级 `--wb-color-stage: #d9eafa`；四张截图均能清楚看到连续蓝色 gutter，且 scoped 页面选择器未触及侧栏、顶栏或其他路由。蓝色覆盖内容区大部分面积，已足以成为视觉主语。 |
| 2 | 符合 | `RecruitmentWorkbenchView.vue:1690,1747` 将页头、向导和内容上限统一为 980px；步骤导航直接位于蓝色舞台上，不再是一整条横向白卡。 |
| 3 | 符合 | 主面板与检查栏均为白色、15px 圆角，并引用 `0 18px 48px rgba(15,23,42,.15)`；运行时实测一致，代码中没有普通卡 hover 上浮。 |
| 4 | 符合 | 1280×720 的 plan 实测为 611px + 320px 双列；720×900 收为 589px 单列；`scrollWidth === clientWidth`。 |
| 5 | 基本符合 | 上传区实测 168px，textarea token 为 96px，standard `scrollHeight` 为 911px。1280×720 截图中下一步动作仍在首屏下方，但只需有限滚动即可到达，属于“接近首屏”，不单独扣分。 |
| 6 | 符合 | `RecruitmentWorkbenchView.vue:1665-1669` 为 meta 10px、业务小字/控件 12px、正文 13px、区块标题 17px、页面标题 27px；截图未见业务说明低于 12px。标题、正文、meta 的递减关系清楚。 |
| 7 | **部分符合** | `RecruitmentWorkbenchView.vue:2024-2030` 已去除浏览器原生 outline，并保留程序化 focus；但 4px 半透明 box-shadow 紧贴 inline 标题，三张桌面截图中读成一个粗重的“标题标签框”，只是把黑色原生框换成了另一种明显焦点框。 |
| 8 | 符合 | 两个 placeholder 使用真实换行；运行时 DOM 明确无字面量 `\\n`。 |
| 9 | 功能符合、工艺未达标 | radio 保留原生语义、18px 几何和 checked 标记，hover/focus/selected 均可辨；但 `RecruitmentWorkbenchView.vue:2411-2413,2434-2437` 同时给 label 与 input 焦点轮廓，720px 截图出现明显方形套框，和圆形 radio/圆角卡片不协调。 |
| 10 | 符合 | 颜色审查仅在 `RecruitmentWorkbenchView.vue:1638-1662,1719` 的页面级 token 区发现 hex/rgba；具体规则均引用 `--wb-*`，未发现散落颜色值。 |
| 11 | 符合 | 运行证据覆盖默认桌面与 720px：无重叠、裁切或页面横向溢出；三步导航、前进/后退、方案选择、阻塞项、处理链接与禁用原因均可见或可操作。 |
| 12 | **证据不完整** | 已有定向 Vitest 32/32、生产构建通过和浏览器 console 0 error/warn；运行证据未提供“完整前端 Vitest”结果。该缺口不推翻当前页面的 5 分功能证据，但最终验收前仍需补齐。 |

## 具体缺陷

### Compliance 缺陷

1. `frontend/src/views/recruitment/RecruitmentWorkbenchView.vue:2028` — 标题焦点用 4px box-shadow 包裹 inline 文本。契约要求的是去除粗糙原生字符框并保留程序化焦点；当前视觉结果仍像一个被选中的标签，而非安静的页面定位反馈。
2. `polish/recruitment-workbench/blue-round-1-runtime-evidence.md` — 契约第 12 项要求完整前端 Vitest，本轮证据只列出定向测试和 build，验收链不完整。

### Craft 缺陷

1. `blue-round-1-context.png` / 运行时测量 — 主卡 968×254px，宽高比约 3.81:1；它几乎占满 980px 内容线，却只承载两个字段和一条动作栏，仍是用户明确不想要的“长而宽”白色横条。蓝色背景已成为主语，但卡片比例尚未跟上。
2. `blue-round-1-context.png`、`blue-round-1-standard.png`、`blue-round-1-plan.png` — 程序化聚焦后的区块标题外围始终出现紧贴文字的光晕框，使 17px 标题看起来像输入控件或标签，破坏标题 > 正文的自然层级。
3. `blue-round-1-plan-720.png` — 被动方案右上角的圆形 radio 外出现方形青绿色套框；input 自身焦点框与父 label 的 `:focus-within` 同时存在，局部观感明显是浏览器控件拼进自定义卡片。

### Coherence 缺陷

1. `frontend/src/views/recruitment/RecruitmentWorkbenchView.vue:1933-1947` — 当前步骤同时使用白底、青绿边框、底部短线和实心编号四层强调；表单区标题又有焦点光晕，页面同时出现两个“当前焦点”，步骤层级略显用力过度。
2. 主页面的圆角/阴影语言整体统一，但标题焦点是紧贴文字的矩形、radio 焦点是方形套框，两种焦点态都没有延续卡片的圆角与克制感。

### Functionality / 验收证据

未发现可见功能回归。唯一缺口是没有完整前端 Vitest 结果，属于最终验收证据缺失，而非本轮已观察到的运行回归。

## 已达到且应保留

1. 平面浅蓝舞台已经明确覆盖内容区，白色圆角阴影卡片层级清楚；无需为了“更像设计”强行增加渐变或玻璃效果。
2. plan 桌面双列比例合理（611px + 320px），检查栏没有继续纵向堆到主卡下方；720px 单列也无横向溢出。
3. 27/17/13/12/10px 字号体系清楚，业务说明与阻塞原因均不低于 12px；步骤 meta 的 10px 使用范围合理。
4. 原生 radio 语义、可见 checked 标记、真实 placeholder 换行、唯一主动作与禁用原因都应保持。

## 优先修复建议（最多 3 项）

1. **只收窄 context 主卡，而不要破坏 standard/plan 密度。** 为 context 布局增加独立视觉 class，将白卡居中并限制到约 800–860px；不要把 standard 一并收窄，否则会重新拉长表单和增加滚动。
2. **移除标题的标签式焦点光晕。** 保留 `stepHeading.focus()` 和步骤导航的清晰当前态，但让 `h3:focus-visible` 不再绘制紧贴文字的 4px box-shadow；若必须提供视觉反馈，改为区块级、一次性的轻微颜色/透明度提示。
3. **把 radio 焦点合并为一个圆角方案卡焦点态。** 保留可见原生 radio 与 accent-color，取消 input 的方形 outline，统一由父 label 的 `:focus-within` 提供单一、圆角且不重复的焦点反馈。
