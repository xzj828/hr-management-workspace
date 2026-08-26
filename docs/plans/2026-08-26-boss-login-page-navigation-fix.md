# BOSS 登录页导航竞态修复

> 日期：2026-08-26
> 状态：已完成
> 类型：纯 bug 修复；不改变架构、API、数据模型或安全边界

## 问题

`open_login` 任务在隔离浏览器的 CDP 端口刚就绪时即终止 `boss-cli login` 子进程，可能打断随后执行的 BOSS 登录页导航，导致浏览器窗口已经出现但仍停留在空白页或未知页面。

## 修复约束

- CDP 端口就绪只表示浏览器进程可连接，不表示登录页已经打开。
- Worker 仅在识别到 BOSS 登录页、人工验证页、错误页或已登录招聘页后释放登录 CLI。
- 空白页、公共首页和未知页面不得作为 `open_login` 成功依据。
- 不保存密码，不代填登录信息，不绕过扫码、验证码或风控。

## 验证

- [x] CDP 先就绪、页面稍后就绪时，Worker 保持 CLI 存活直到目标页面出现。
- [x] CLI 已退出但没有目标页面时，任务明确失败。
- [x] 已登录页、登录页和人工验证页仍按原状态模型收敛。
- [x] Django 相关测试与 system check 通过。

## 完成证据

- 招聘域测试：432/432 通过。
- Django system check 与 migration drift check 通过。
- 直接调用 `execute_check_status()` 验证“空白页 → 登录页”状态序列，任务在目标页出现后返回 `succeeded + waiting_login` 并释放 CLI。
- 对抗审查：功能完整性 9/10、健壮性 8/10、最小改动 9/10、代码质量 8/10，结论 PASS。

## 现场复验与运行时加载（2026-08-26）

用户首次复验仍停留在 `edge://newtab/`。现场证据确认 RPA Worker 于 20:30 启动，而修复文件于 20:43 写入；20:54 的 `open_login` 任务仍由旧进程执行，并在约 0.12 秒内把“未检测到已登录的 BOSS 页面”错误记录为成功。

- [x] 重启本地服务组，使 Web、RPA Worker 与 AI Worker 使用同一工作树版本。
- [x] 使用真实账号隔离目录和 CDP 端口触发 `open_login`。
- [x] 读取真实 CDP 标签页，确认进入 `www.zhipin.com` 登录、验证或已登录招聘页面。
- [x] 核对任务结果与页面状态一致，不再把 `edge://newtab/` 判为成功。

现场服务于 20:58 重新启动，RPA Worker 已晚于修复文件加载。账号 3 的真实任务 `e4b5e8e3-cd8c-45e0-abab-b99d635bac71` 返回 `succeeded + waiting_login`；CDP 53472 的页面为 `https://www.zhipin.com/web/user/?ka=header-login`，不再是 Edge 新标签页。
