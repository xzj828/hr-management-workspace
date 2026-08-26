# Reference Round 1 Changelog

## 分栏主卡与页面级 Token

- `frontend/src/views/recruitment/RecruitmentWorkbenchView.vue:1655` — 将招聘作业台舞台 token 更新为高饱和青蓝 `#00bfc1`，并集中定义浅青侧栏、青蓝主动作、950px 外框、270px 左栏、620px 最小卡高、32px 外圆角与单层阴影等页面级 token。
- `frontend/src/views/recruitment/RecruitmentWorkbenchView.vue:1288` — 把原先分散的 Hero、横向步骤条、主表单和 plan 检查卡重排为一个共享外框：左侧纵向三步导航，右侧白色当前任务工作区。
- `frontend/src/views/recruitment/RecruitmentWorkbenchView.vue:2998` — 建立桌面端统一主卡、32/68 邻近分栏、纵向 context 表单、50px 控件、28px 当前步骤标题和青蓝实心推进按钮；standard 与 plan 复用同一外框和内容起始线。
- `frontend/src/views/recruitment/RecruitmentWorkbenchView.vue:1584` — 将“执行前检查”、阻塞原因、处理链接、唯一开始动作与运行控制并入 plan 右侧连续浅色分区，移除独立浮动检查卡视觉。
- `frontend/src/views/recruitment/RecruitmentWorkbenchView.vue:3584` — 在 720px 及以下把左栏折叠为卡内顶部三步摘要，白色工作区置于其下，并让表单、方案、检查和操作区单列排布。

## 岗位参考资料简化

- `frontend/src/views/recruitment/RecruitmentWorkbenchView.vue:19` — 新增固定兼容类别 `JOB_DOCUMENT_CATEGORY = 'persona'`；上传始终提交该类别，旧草稿类别不再参与恢复、上传或用户流程。
- `frontend/src/views/recruitment/RecruitmentWorkbenchView.vue:1398` — 删除可见“本批文件用途”选择器，上传区统一命名为“岗位参考资料”，并说明其用于生成岗位标准与简历评分依据。
- `frontend/src/views/recruitment/RecruitmentWorkbenchView.vue:1357` — 移除 context 首屏的浏览器/CDP 技术信息，仅保留账号业务就绪状态与职位绑定关系。

## 定向测试更新

- `frontend/src/views/recruitment/RecruitmentWorkbenchView.test.js:361` — 更新上传用例，断言用途选择器不存在，两个文件上传请求均提交固定类别 `persona`；同步使用“岗位参考资料”统一文案。

## 验证结果

- `npm test -- --run src/views/recruitment/RecruitmentWorkbenchView.test.js` — 通过，1 个测试文件、32 个测试全部通过。
- `git diff --check -- frontend/src/views/recruitment/RecruitmentWorkbenchView.vue frontend/src/views/recruitment/RecruitmentWorkbenchView.test.js` — 通过，无空白错误；仅输出工作区 LF/CRLF 转换提示。

## 未处理项

- 无。
