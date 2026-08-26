# Scorecard: 管理后台 — Round 3

## 评分

| 维度 | 分数(1-5) | 关键发现 |
|------|----------|---------|
| Design System Compliance | 4 | 主色、表面、文字、分割线、圆角、阴影、字号和间距均通过页面级 CSS 变量贴合 `DESIGN.md`；但仍有少量直接尺寸值未抽成语义 token，未达到零硬编码的 5 分标准。 |
| Visual Craft | 4 | 1440×900 首屏层级清楚、对齐稳定、留白自然，标题、说明、状态与动作可快速扫读；账号动作独占第二行使列表行略高，尚非设计工作室级的极致紧凑。 |
| Coherence | 5 | 页头、文本 Tab、单一主面板、分割线列表、状态标签、按钮和折叠详情使用同一套克制后台语言，无卡片墙或外来组件感。 |
| Functionality Preservation | 5 | 截图中关键动作全部可见，源码保留刷新、Tab、创建、状态检查、登录窗口、归档/恢复、四态和二次确认；专项 Vitest 21/21 通过。 |
| **总分** | **18/20** | |

## 判定

PASS

判定依据：总分 18/20 ≥ 16/20，且无单项 ≤ 2。

## 硬性验收核对

| 验收项 | 结果 | 证据 |
|------|------|------|
| 标题旁刷新可见 | 通过 | 截图中“管理后台”右侧直接显示“刷新状态”；模板见 `RecruitmentAdminView.vue:783-787`。 |
| 当前 / 已归档 / 添加账号可见 | 通过 | 三项在账号主面板标题区同时可见；模板见 `RecruitmentAdminView.vue:834-841`。 |
| 每账号三动作在正常全页截图可见 | 通过 | 两个账号均直接显示“聚焦登录窗口 / 检查状态 / 归档”，无滚动、悬停或展开前置；模板见 `RecruitmentAdminView.vue:876-893`。 |
| 技术信息仅在 details | 通过 | 浏览器、CDP 端口和隔离目录均位于关闭的 `<details class="account-technical">` 内；截图首屏仅显示“技术详情”摘要，模板见 `RecruitmentAdminView.vue:894-901`。 |
| 文本 Tab | 通过 | 子导航为无卡片背景的文本 Tab，选中态仅用品牌文字与底线；样式见 `RecruitmentAdminView.vue:1301-1326`。 |
| 单面板、分割线列表 | 通过 | 账号子页仅有一个 `.admin-section` 主面板；账号条目无独立边框/阴影，仅以底部分割线组织，样式见 `RecruitmentAdminView.vue:1406-1463`。 |
| 自然留白与信息层级 | 通过 | 页面栈 22px，主面板内采用 12/16/22px 节奏；标题、说明、状态、最近检查、下一步和动作层级可在 3 秒内识别。 |
| Token 一致性 | 通过 | 颜色值只出现在 `.recruitment-admin` 的变量定义中，并与设计真值一致；第二套品牌绿已消失，见 `RecruitmentAdminView.vue:1200-1242`。 |
| 功能与四态保留 | 通过 | Loading、Empty、Error、Normal、归档 Empty/Error、权限态与禁用原因均仍在；`npm test -- --run src/views/recruitment/RecruitmentAdminView.test.js` 结果为 21 tests passed。 |

## 严格扣分说明

1. Compliance 未给 5 分：`RecruitmentAdminView.vue:1361`、`:1575`、`:1657`、`:1722` 等仍直接使用 44px、40px、14px、36px 等视觉尺寸；这些值本身合理，但 rubric 的 5 分要求所有视觉值均经变量或 token 引用。
2. Craft 未给 5 分：账号行将三动作和技术摘要各占一层，保证了硬性可见性，但也使每个账号条目明显高于 DESIGN.md 的默认 48–64px 列表节奏；当前截图仍然整齐且不拥挤，因此属于次要偏离。

## 优先修复建议

无需继续 GAN 轮次。若后续做非阻塞式精修，可把剩余直接尺寸抽成语义 token，并在不牺牲三动作首屏可见性的前提下进一步压缩账号行的纵向节奏。
