# 主动寻访 Worker 事件范围误判修复

日期：2026-08-27

状态：`[x]` 已完成

## 问题证据

- 最近一次 `search_pull_resumes` 任务已成功领取租约，但在上报 `started` 事件时立即收到 HTTP 409。
- 任务没有进入 BOSS 搜索：`started_at` 为空，扫描数与拉取数均为 0。
- Plan revision、control generation、岗位状态和账号状态均有效。
- `_raw_passive_scopes()` 将携带 `automation_plan_revision` 与 `job` 的主动寻访任务错误推导为被动消息同步 scope，随后 `task_event_view()` 将空的被动 Plan 匹配结果判为 scope 已变化。

## 修复方案

- 被动 scope 推导只接受 `RpaTask.Action.SYNC_CONVERSATIONS`；其他任务返回“无被动 scope”。
- 不改变租约 token/generation、租约期限、Plan fence、停止栅栏或完成回写校验。
- 增加真实 Active Plan Revision 关联任务的 Worker `started` 事件回归测试。
- 保留被动消息同步 scope 变化必须返回 409 的既有行为。

## 验证

- [x] 主动寻访任务领取后可上报 `started` 并进入 `running`。
- [x] 被动同步 scope 失效仍被拒绝。
- [x] Worker API 与 Automation Plan 聚焦测试通过。
- [x] recruitment 后端 472 项测试与 Django system check 通过。
