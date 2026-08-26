# Scorecard: 管理后台 — Round 1

## 评分

| 维度 | 分数(1-5) | 关键发现 |
|------|----------|---------|
| Design System Compliance | 3 | 页面主色、字号、圆角和标准面板阴影基本映射到设计 token，文本 Tab 与单主面板成立；但多组状态浅色与半透明边框仍是 DESIGN.md 未定义的局部硬编码，技术字段也没有按契约折叠。 |
| Visual Craft | 3 | 页头—文本 Tab—主面板的层级清楚，分割线列表与下方留白符合考勤模块的克制节奏；账号行横向信息过载，并在右侧发生肉眼可见的动作裁剪，尚未达到专业工艺水准。 |
| Coherence | 4 | 导航、页头、文本 Tab、面板标题行和扁平账号列表基本是同一种后台语言，没有恢复卡片墙；当前/已归档分段控件略重，但不构成第二套视觉系统。 |
| Functionality Preservation | 2 | 截图中每条账号行只看得到“聚焦登录窗口”；源码中同一 footer 的“检查状态”和“归档”均未在截图出现，说明关键账号管理动作被布局裁剪、用户无法访问。 |
| **总分** | **12/20** | |

## 判定

**NEEDS_IMPROVEMENT**

未达到 PASS：总分低于 16，且 Functionality Preservation 为 2，触发硬性否决。

## 证据摘要

- 符合项：截图中的子导航是下划线式文本 Tab；当前子页只呈现一个白色主面板；账号以分割线列表行呈现；两行数据结束后的大块空白是数据量较少时的自然页面留白，符合 DESIGN.md 的单列考勤节奏，不应再添加入口卡或装饰容器填满。
- 不符合项：两条账号行在最右侧均只显示一个按钮，源码声明的后两个行级动作完全不可见；这是布局裁剪，不是“低频动作降级”。
- 不符合项：CDP 端口字号虽已减弱，但仍常驻账号副标题；“隔离目录”及其值仍占一整列并使用较深文字。技术信息只是缩小，没有完成渐进披露或折叠。

## 具体缺陷

### Compliance 缺陷

1. `frontend/src/views/recruitment/RecruitmentAdminView.vue:1203-1211` — `#f8fafc`、`#ecfdf8`、`#fff8e9`、`#fff1f2`、`#eff6ff` 等状态浅色在页面内硬编码，无法从 DESIGN.md / `polish/design-tokens.md` 找到精确 token 对应；按 rubric 不能评为 4–5 分。
2. `frontend/src/views/recruitment/RecruitmentAdminView.vue:1353-1367`、`:1613` — 多处 `rgba(...)` 状态边框继续散落在组件规则中，而非引用统一 token；同一语义色尚未完全由设计系统管理。
3. `frontend/src/views/recruitment/RecruitmentAdminView.vue:862-868` — CDP 端口和隔离目录仍在每条账号首屏固定展示，违反 DESIGN.md“端口、目录只在诊断或详情中出现”和 Sprint Contract“技术详情折叠”的要求。

### Craft 缺陷

1. 账号行右侧动作区被面板边界截断 — 截图两行都只显示“聚焦登录窗口”，其右侧“检查状态”“归档”没有任何可见像素；完整宽度下仍发生裁剪，是明显的排版失效。
2. `frontend/src/views/recruitment/RecruitmentAdminView.vue:1430-1439`、`:1500` — 四列网格把 identity、meta、guidance 和不换行的 actions 同时塞进一行；技术元数据和长引导文案挤占动作所需宽度，缺少稳定的列宽优先级。
3. 技术字段的视觉权重仍偏高 — 截图中“隔离目录”及目录值与“最近检查”并列占据行中部，业务 HR 的“状态 / 下一步 / 可执行动作”没有成为压倒性的扫描主线。

### Coherence 缺陷

1. 账号行整体已使用扁平列表语言，但行内又同时并列身份、状态、两组技术元数据、说明和三动作；信息密度显著高于页头与文本 Tab 的克制语气，局部仍有旧后台“全部摊开”的感觉。

### Functionality 缺陷

1. `frontend/src/views/recruitment/RecruitmentAdminView.vue:880-897` — 模板明确渲染“聚焦登录窗口 / 检查状态 / 归档”三项动作，截图却只显示第一项；检查状态与归档功能在当前可见布局中不可达。
2. `frontend/src/views/recruitment/RecruitmentAdminView.vue:1392-1399`、`:1430-1439`、`:1500` — `.admin-section { overflow: hidden; }` 与不可换行的横向 footer / 四列最小宽度组合会静默裁掉超出内容，没有局部滚动、换行或菜单回退。

## 优先修复建议（最多 3 个最高优先级）

1. 先恢复账号行所有动作的可见与可达：为 actions 预留确定宽度，允许合理换行，或把“检查状态 / 归档”收进可访问的行级文本菜单；在当前桌面截图宽度下必须完整显示，不得依赖 `overflow: hidden` 裁剪。
2. 真正渐进披露技术信息：首行只保留账号、业务状态、下一步和动作；将 CDP 端口、隔离目录移到“技术详情”展开区或系统诊断，最近检查可保留为弱 meta。
3. 将状态浅色与透明边框收敛为统一设计 token，并用这些 token 替换组件规则中的散落色值；复核账号行列宽后保持现有文本 Tab、单面板与自然留白，不要重新引入卡片层级。
