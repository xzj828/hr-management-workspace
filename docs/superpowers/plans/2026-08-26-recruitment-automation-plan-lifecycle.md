# 招聘自动化任务生命周期实施计划

> 状态：已完成并验收
> 日期：2026-08-26
> 范围：招聘作业台的开启、停止、修改、继续/重新开启及 Worker 协作式停止

## 产品目标

HR 在招聘作业台启动任务后，可随时看到服务端真实状态并执行停止、修改和重新开启。页面不得把“请求已提交”伪装成“外部动作已停止”，也不得用浏览器会话草稿代替后台运行真值。

## 状态与版本契约

- 每个职位只有一个持久化 Automation Plan；被动/主动方案类型属于不可变 Revision，停止后切换方案仍复用同一个 Plan；`desired_state` 表示 HR 意图，`effective_state` 汇总本代 WorkflowRun 与 RPA Task 的实际状态。
- 每次首次开启、修改后开启或重新开启都会生成不可变 Revision 和新的 `control_generation`；运行中的 Revision 绝不热改。
- 停止先持久化 `desired_state=stopped` 并提升 generation，再取消尚未执行的工作。已进入浏览器的单个原子动作只允许安全收尾，此时展示 `stopping`。
- `stopped` 表示不会再领取、创建或推进下一项外部动作，不承诺撤销已经完成的外部效果。
- 每次 RPA 租约具有独立 `lease_token`；旧租约即使由同一个 Worker 重新领取，也不能提交 event、checkpoint 或 complete。
- 浏览器会话存储只保存未提交草稿；Plan、Revision、Run 与 Task 才是运行状态真值。

## 业务安全契约

- “开启”必须是一个服务端原子命令：冻结配置、创建/启用流程版本、创建 Run、绑定 Plan Revision，全部成功后才派生消息同步订阅；任一步失败整体回滚。
- 被动方案以职位 Plan 的 revision/generation 复核消息处理。账号级同步可以复用，但停止岗位的消息不得标记为已处理、不得创建提醒或外发动作；其他运行中岗位互不影响。
- 主动寻访在每次在线简历 preview 等不可逆动作前后 checkpoint；停止发生在动作中时，当前结果可审计落库，但不能继续下一人或推进旧代流程。
- start/pause/resume/stop 使用 request id 与 expected control version 做幂等和乐观并发；409 后前端重新读取服务端状态。
- 所有权限、审批、额度、稳定平台身份、风险控制与外发 fail-closed 规则继续生效。

## 实施任务

- [x] 新增 Automation Plan / immutable Revision、Run/Task 追溯字段与 RPA lease token 迁移。
- [x] 新增岗位级 Plan 查询及原子 start、pause、resume、stop 领域服务/API。
- [x] 将 MessageSyncPolicy 改为由运行中被动 Plan 派生，并在同步完成前复核完整 scope 的 revision/generation。
- [x] 在 task 创建、租约、started、checkpoint、complete 和 workflow advance 边界增加 plan generation fence。
- [x] 给主动寻访循环增加逐项前后 checkpoint、协作式停止和迟到结果收口。
- [x] 作业台改用服务端 Plan 单一真值，增加停止、停止并修改、继续、修改方案、重新开启和结果入口。
- [x] 增加 5 秒非重叠轮询、请求序列隔离、岗位切换隔离、409 刷新与提交结果不确定状态。
- [x] 覆盖多岗位被动同步、启动事务回滚、停止竞态、代际隔离、旧租约、主动寻访中途停止和权限测试。
- [x] 完成全量后端、前端、迁移、生产构建与独立对抗验收；只读浏览器旅程作为最终交付检查。

## 验证结果

- 后端全量：476 项通过；招聘域 417 项通过。
- 前端全量：41 个测试文件、243 项通过；Vite 生产构建通过。
- 数据库：`recruitment.0029` 已实际应用，`makemigrations --check` 无漂移。
- 独立对抗审查：P0=0、P1=0 后交付；真实 BOSS 外部动作未在验收中触发。

## 验收标准

1. 开启命令中任一步失败时，不留下已启用的消息策略、孤立 Revision、Run 或可领取 Task。
2. 停止某岗位后不再产生该岗位的新提醒、索简历、在线简历查看或流程推进；同账号其他岗位继续正常运行。
3. 主动寻访执行到第 N 人时停止，最多让当前不可分割动作收尾，绝不开始第 N+1 人。
4. 停止后立即重新开启，新 generation 可运行；旧 generation 的 event/complete/late sync 全部失败关闭。
5. 同一 Worker 的旧 lease token 在任务重领后也不能复活或覆盖新租约。
6. 修改只更新草稿；再次开启才生成新 Revision，历史配置、Run、Task 与结果仍可审计。
7. 页面刷新、换标签页和浏览器历史均从服务端恢复一致状态；POST 成功但刷新失败不会诱导重复提交。
8. 不启动真实 BOSS 外发即可通过自动化测试和只读浏览器旅程验证控制面。
