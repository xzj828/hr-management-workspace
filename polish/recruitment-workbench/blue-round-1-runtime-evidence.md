# Runtime Evidence: 招聘作业台 — Blue Round 1

此文件由编排器基于已登录的隔离演示环境采集，不包含 Generator changelog。

## 环境

- URL：`http://127.0.0.1:8771/recruitment/workbench?job=1`
- 数据：临时 SQLite 演示数据库；不读取或修改正式数据库
- 默认浏览器视口：1280 × 720
- 窄屏验证视口：720 × 900

## 三步运行时测量

| 步骤 | 页面 scrollHeight | 主卡尺寸 | 关键证据 |
|---|---:|---|---|
| context | 720px | 968 × 254px | 页面 scrollWidth = clientWidth = 1280；15px 圆角；`0 18px 48px rgba(15,23,42,.15)` 阴影 |
| standard | 911px | 953 × 629px | 上传区 168px；placeholder 含真实换行；DOM 无字面量 `\\n` |
| plan | 845px | 主区 611 × 516px；检查区 320 × 563px | grid columns = `611px 320px`；常见桌面保持并列 |

基线对应 scrollHeight：context 720px、standard 1036px、plan 1232px。

## 交互与可访问状态

- context 的职位/账号选择可用，点击“下一步：招聘标准”成功。
- standard 的“上一步 / 下一步：执行方案”可见，点击下一步成功。
- passive / active 两个原生 radio 均可点击；切到主动寻访后主动参数字段出现，再切回被动咨询成功。
- radio 保持原生 checked 语义且几何尺寸可见，不仅依赖边框颜色。
- plan 中阻塞项、处理链接、禁用“开始执行”按钮和禁用原因同时可见。
- 页面 DOM 中没有字面量 `\\n`；核心要求 placeholder 为真实三行文本。
- 浏览器 console error/warn：0。

## 响应式

- 720 × 900：document scrollWidth = clientWidth = 705px，无横向溢出。
- plan 布局收为单列 `589px`；主区和检查区宽度均为 589px。
- 顶部步骤导航保持三步横向可辨，表单与方案卡收为单列。

截图：

- `blue-round-1-context.png`
- `blue-round-1-standard.png`
- `blue-round-1-plan.png`
- `blue-round-1-plan-720.png`

## 自动化验证

- 定向 Vitest：`RecruitmentWorkbenchView.test.js`，32/32 通过。
- 生产构建：Vite build 通过；仅保留既有 ECharts chunk-size advisory。
