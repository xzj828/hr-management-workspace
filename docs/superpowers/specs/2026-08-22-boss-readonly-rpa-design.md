# BOSS 直聘只读 RPA 第一阶段设计

日期：2026-08-22  
状态：待用户书面复核

## 1. 目标

在人事管理系统中交付一个可验证、可暂停、可审计的 Windows BOSS RPA 最小闭环。第一阶段只允许检查登录状态和同步职位，不读取候选人、不发送消息、不打招呼、不请求或下载简历。

系统必须继续使用 `boss-cli` 执行 BOSS 页面动作，同时由独立 Windows Worker 管理浏览器生命周期、账号隔离、任务串行和错误状态。Chrome 与 Edge 均作为账号级可选项。

## 2. 当前前提与交付边界

- 当前仓库只有招聘数据底座，没有 RPA Worker、任务队列或 `boss-cli` 适配器。
- 当前 Windows 环境的 `PATH` 中没有 `boss` 或 `boss-cli` 命令。
- 用户提供的压缩包包含工作台和 `boss-cli` 行为分析，但不包含可安装的 `boss-cli` 源码或可执行文件。
- 因此本阶段可以完成业务模型、Worker 协议、浏览器隔离、任务页面、模拟适配器和自动化测试；真实 BOSS 联调必须在用户提供可运行的 `boss-cli` 后进行。
- 不迁移、不读取、不初始化压缩包中的第三方候选人、简历或评分数据。

真实联调的完成标准不能用模拟适配器代替。界面必须明确显示“CLI 未安装”，不得伪装成账号离线或同步成功。

## 3. 方案

采用混合接入：

```text
Vue 3 自动化任务页
        ↓
Django 招聘 API
├─ BOSS 账号与浏览器配置
├─ RPA 任务、事件和审计
└─ Worker 本机鉴权与任务租约
        ↓ HTTP 轮询（本机 Worker）
Windows RPA Worker
├─ 浏览器管理器
├─ 单账号进程锁
├─ boss-cli 适配器
└─ 状态/错误归一化
        ↓
Chrome 或 Edge 独立持久目录
        ↓ CDP
boss-cli → BOSS 直聘
```

Django 不直接启动浏览器或运行 CLI，避免 CLI 卡死阻塞考勤与招聘 API。Worker 只执行服务端创建的白名单任务，不接受任意 Shell 命令。

## 4. 第一阶段动作白名单

仅开放：

- `CHECK_STATUS`：检查 CLI、浏览器、CDP、BOSS 页面和登录/验证状态。
- `SYNC_POSITIONS`：调用 `boss positions` 获取当前账号可管理职位，并以账号加外部职位标识进行新增或更新。

明确禁止：

- 候选人搜索、采集和打开详情；
- 打招呼、发送消息、索要简历；
- 简历预览、下载和评分；
- 任意脚本、Shell 参数或未登记 CLI 子命令。

## 5. 浏览器与账号隔离

每个 `BossAccount` 固定保存：

- `browser_type`：`chrome` 或 `edge`；
- `browser_executable`：系统检测到的可执行文件绝对路径；
- `browser_profile`：系统生成的不可变目录标识；
- `user_data_dir`：位于应用数据目录下的账号专属绝对路径；
- `cdp_port`：账号专属端口；
- `login_status`、`verification_status` 和最后检查时间；
- 授权 HR、启用状态和每日限制。

规则：

1. 不允许选择日常 Chrome/Edge 默认用户目录。
2. 一个目录只能被一个 Worker 进程持有；锁未释放时拒绝第二次启动。
3. 一个账号一项运行中任务；第一阶段系统全局并发也固定为 `1`。
4. 浏览器使用可视模式，不使用无痕或关闭即删除的临时目录。
5. 账号切换浏览器类型时，不搬运 Cookie；必须创建新隔离目录并重新人工登录。
6. CDP 只监听 `127.0.0.1`，不得暴露到局域网。

## 6. boss-cli 兼容层

Worker 按以下顺序定位 CLI：

1. 系统设置中的绝对路径；
2. 环境变量 `BOSS_CLI`；
3. `PATH` 中的 `boss`；
4. `PATH` 中的 `boss-cli`。

调用使用参数数组，不经过 Shell。每次执行设置超时，分别捕获退出码、UTF-8/Windows 多编码输出和截断后的脱敏日志。

原工作台已证明的命令契约为：

```text
boss login
boss positions
boss jd <职位名称>
```

第一阶段只调用 `login` 和 `positions`。Worker 启动时执行能力探测；如果现有 CLI 固定使用 Chrome、固定端口 `53470` 或不支持外部 CDP 参数，则：

- Chrome 兼容模式可按 CLI 原生行为验证；
- Edge 账号显示“当前 CLI 不支持 Edge”，禁止创建真实执行任务；
- 不通过伪造、代理转发或复制 Cookie 冒充支持；
- 获得 CLI 源码或正式参数说明后再扩展端口和 Edge 参数映射。

这样保证 UI 可以配置 Edge，但不会在底层能力不存在时给出虚假成功。

## 7. 登录与验证状态机

账号状态：

```text
CLI_MISSING
→ BROWSER_STOPPED
→ STARTING
→ WAITING_LOGIN
→ WAITING_QR_SCAN
→ WAITING_APP_CONFIRMATION
→ READY
→ RUNNING
```

异常状态：

```text
QR_EXPIRED
TOKEN_INVALID
LOGIN_EXPIRED
CDP_UNAVAILABLE
PROFILE_LOCKED
NETWORK_ERROR
PAGE_CHANGED
RISK_CONTROL
```

处理规则：

- 扫码必须发生在当前隔离浏览器的实时页面中，不保存二维码供稍后使用。
- 二维码过期允许人工点击刷新，不无限自动刷新。
- `TOKEN_INVALID` 结束本次登录任务；Worker 关闭该账号浏览器后可由 HR 使用原目录重新启动。
- 连续三次登录验证失败后账号进入暂停状态，必须人工恢复。
- 验证码、App 确认和风控页面只允许人工处理，系统不绕过、不代答。
- 扫码后以 BOSS 页面已进入登录态并通过一次 `CHECK_STATUS` 为准，不能仅依据扫码回调判定成功。

## 8. 任务与数据模型

新增：

- `RpaWorker`：Worker 标识、版本、主机、最后心跳和能力。
- `RpaTask`：动作、账号、创建者、状态、租约、超时、结果摘要和错误分类。
- `RpaTaskEvent`：任务时间线、状态变化和脱敏信息。
- `RecruitmentAuditLog`：谁在何时对哪个账号创建、取消或重试了什么任务。

任务状态：

```text
PENDING → LEASED → RUNNING → SUCCEEDED
                         ├→ FAILED
                         ├→ WAITING_HUMAN
                         └→ CANCELLED
```

Worker 使用短租约领取任务并定期续租。Worker 崩溃导致租约到期时，只读任务可以回到待处理；第一阶段不存在外发动作，因此不会产生重复发送问题。

## 9. API 与权限

HR 和管理员可以：

- 创建、修改和停用自己获授权的 BOSS 账号；
- 创建 `CHECK_STATUS`、`SYNC_POSITIONS` 任务；
- 查看任务、事件、Worker 心跳和账号状态；
- 取消待执行任务，并在允许条件下重试失败任务。

主管和只读用户只能查看被授权范围内的状态，不能创建任务。所有写权限由 Django API 强制执行。

Worker API 使用独立的随机凭据，不复用 HR 登录 Cookie。Worker 凭据只允许领取白名单任务、上报心跳和提交任务结果。

## 10. 前端

“自动化任务”页面保持现有简约视觉，不堆叠大量按钮，包含：

- 顶部 Worker/CLI 总状态；
- BOSS 账号列表：浏览器、登录状态、最近检查、同步职位数；
- 账号配置抽屉：Chrome/Edge、浏览器路径、隔离目录只读展示、CDP 端口；
- 主操作菜单：检查状态、同步职位、打开隔离浏览器；
- 任务列表和事件详情；
- `CLI_MISSING`、`WAITING_HUMAN`、`TOKEN_INVALID` 等明确中文指引。

危险或未开放动作不渲染为可点击按钮。

## 11. 测试与验收

自动化测试覆盖：

- 浏览器类型、目录和端口校验；
- 默认浏览器目录拒绝、目录锁和全局串行；
- CLI 查找、缺失、超时、非零退出码和多编码输出；
- CLI 能力不足时 Edge 任务被拒绝；
- Worker 鉴权、心跳、领取、续租和结果提交；
- 角色权限和账号授权；
- 职位同步新增、更新和去重；
- `TOKEN_INVALID`、二维码过期、登录失效和人工接管状态；
- Vue 页面状态、动作可用性和错误提示；
- 原考勤与招聘基础测试继续通过。

真实 Windows 验收按顺序进行：

1. 安装或提供 `boss-cli`，系统从“CLI 未安装”变为“可用”。
2. 创建一个隔离 Chrome 账号，人工扫码并重启浏览器，登录仍有效。
3. 连续执行三次 `CHECK_STATUS`，结果稳定且没有重复浏览器进程。
4. 执行一次 `SYNC_POSITIONS`，核对职位数量和名称。
5. 再次同步，数据库不产生重复职位。
6. 创建隔离 Edge 账号；只有能力探测确认 CLI 支持 Edge 后才执行相同步骤。
7. 人为关闭浏览器、占用端口和使登录失效，确认任务给出正确状态并且考勤页面不受影响。

## 12. 交付顺序

1. 扩展账号模型，新增任务、Worker 和审计模型。
2. 完成 Django 任务 API、权限、租约和职位同步服务。
3. 实现 Windows Worker、浏览器管理器和可替换 CLI 适配器。
4. 实现自动化任务页面和账号配置交互。
5. 使用模拟 CLI 完成自动化测试和本机进程测试。
6. 用户提供真实 `boss-cli` 后完成 Chrome 联调，再依据能力探测结果完成 Edge 联调。
