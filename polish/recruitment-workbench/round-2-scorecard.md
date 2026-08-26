# Scorecard: 招聘作业台 — Round 2

## 评分

| 维度 | 分数(1-5) | 关键发现 |
|------|----------|---------|
| Design System Compliance | 4 | 主色、字体、字号、间距、圆角和阴影均集中为页面 token，主体符合 DESIGN.md；但响应式策略只按 viewport 触发，未保证实际内容容器中的摘要栏达到可读宽度。 |
| Visual Craft | 2 | 主面板节奏已经清楚，但实测 `innerWidth=1600`、布局容器约 `1271px` 时右栏仍严重过窄，标题、检查项、处理链接、主按钮和说明出现肉眼可见的裁切或异常折行。 |
| Coherence | 3 | 页头与三段连续主面板形成了统一语言，但右侧执行区退化成拥挤、残缺的窄条，和左侧舒展、精确的排版不在同一完成度。 |
| Functionality Preservation | 3 | 该视图现有 7 个单元测试全部通过，运行、上传、恢复和提交逻辑未见回归；但截图中唯一核心 CTA 的文字不可读，阻塞原因也不完整，造成可见的操作可用性回归。 |
| **总分** | **12/20** | |

## 判定

NEEDS_IMPROVEMENT

## 具体缺陷（仅 NEEDS_IMPROVEMENT 时）

### Compliance 缺陷

1. `frontend/src/views/recruitment/RecruitmentWorkbenchView.vue:1556` — 单列切换使用 `@media (max-width: 1500px)`，判断的是浏览器 viewport；本轮截图的 `innerWidth=1600`，所以该规则明确不会生效，即使 `.workbench-layout` 的实际可用宽度只有约 `1271px`。不能把这条 media rule 当作右栏宽度保障。
2. `frontend/src/views/recruitment/RecruitmentWorkbenchView.vue:939` — 代码声明右轨 `304–320px`，但截图中的实际可见结果与声明不一致，右栏仍被压成不足以承载三列检查项和 CTA 的窄条；评审必须以渲染结果为准，该响应式契约尚未成立。
3. `frontend/src/styles.css:104` 与 `frontend/src/views/recruitment/RecruitmentWorkbenchView.vue:1462` — 全局主按钮 hover 仍会继承 `translateY(-1px)`；页面局部规则只覆盖颜色和边框，没有按 DESIGN.md 的动效约束取消位移。

### Craft 缺陷

1. 右侧栏标题“执行前检查”在截图中被压成“执行前”，检查项文字也只剩短截词或逐字折行；这是首屏肉眼可见的布局失败，而非细节偏差。
2. 唯一“开始执行”按钮在截图中只呈现为空白灰色按钮轮廓，按钮文字和图标不可辨认；其下提示也只剩“请先处理：”，没有完整展示需处理对象。
3. `frontend/src/views/recruitment/RecruitmentWorkbenchView.vue:1388` — 检查行固定为“20px 图标 + 弹性文本 + auto 操作”三列；在当前窄栏里，“处理”继续占据尾列，进一步挤压标题与详情，导致 BOSS 账号、隔离浏览器等关键信息碎裂。
4. `frontend/src/views/recruitment/RecruitmentWorkbenchView.vue:1531` — 底部安全说明同样被窄栏压碎和裁切，无法形成一条可扫读的辅助说明。

### Coherence 缺陷

1. 左侧三段流程已经是连续主面板、分割线和稳定双列表单，右侧却呈现近似移动端窄列的排版密度；同一桌面首屏出现两套完全不同的阅读节奏。
2. 右侧摘要、检查列表、按钮、提示和安全说明在有限宽度内纵向堆叠，但没有任何针对容器宽度的重排，导致“简洁执行摘要”反而成为全页信息最难读取的区域。

## 优先修复建议（最多 3 个最高优先级）

1. 以 `.workbench-layout` 的实际可用宽度而非 `window.innerWidth` 决定布局：在约 `1271px` 内容宽度下直接切为单列，或使用 container query，并重新截图证明 `innerWidth=1600` 时规则确实命中。
2. 为右侧检查区建立最小可读契约：标题完整显示、检查项标题至少一行可读、详情正常换行、“处理”不挤占正文，且“开始执行”按钮与阻塞提示完整可见。
3. 取消该页主按钮继承的 hover 位移，并在修复后同时验证桌面首屏和 720px 以下无横向溢出。
