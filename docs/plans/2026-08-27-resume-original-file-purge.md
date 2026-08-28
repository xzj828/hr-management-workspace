# 已保存简历原文件一键清理

日期：2026-08-27  
状态：`[x]` 已完成

## 目标

让 HR 从结果中心简历详情安全删除本地保存的原始 PDF/PNG，立即释放主要磁盘占用，同时不破坏历史评分、人工筛选结论和自动化审计链。

## 方案

1. 在 `services/resumes.py` 增加事务化清理服务：锁定记录、拒绝在途 AI 任务、终止尚未开始的排队任务、删除存储对象、清空文件字段、归档并写审计。
2. 在 `ResumeViewSet` 增加岗位权限范围内的 `POST <id>/purge/` 动作，成功返回释放字节数，冲突返回 409。
3. 在 `ResumeIntelligencePanel` 暴露“删除简历”危险操作；`RecruitmentResultsView` 承担确认框、请求、URL 清理、刷新与成功/失败反馈。
4. 增加后端文件删除/权限/冲突/幂等测试与前端确认/刷新/失败测试。

## Acceptance Criteria

- [x] 点击删除后必须经过明确的不可恢复确认，提交期间不可重复操作。
- [x] 成功后原文件在配置的存储中不存在，`Resume.file` 为空、`file_size=0`、`archived_at` 非空。
- [x] 已清理简历不再进入当前岗位排名；预览和下载返回 404。
- [x] 结构化版本、评分、HR 结论与审计引用仍可留存，不因受保护外键导致删除失败。
- [x] 在途 AI 任务返回 409，排队任务安全终止；越权返回 404；重复清理返回 200 且释放字节数为零。
- [x] 前端成功后关闭详情、清理深链、刷新结果并展示释放空间；失败保留上下文。
- [x] 相关 Django、Vitest 测试与前端生产构建通过。

## 风险与边界

- 本功能释放原始文件的磁盘占用，不承诺删除历史结构化文本或审计数据。
- 不新增数据库字段、迁移、依赖或外部动作。
- 不触碰招聘任务、运行事件或人工筛选记录的既有保留策略。

## 验证记录

- `manage.py test recruitment.tests.test_recruitment_pages_api -v 1`：15/15 通过。
- `manage.py test recruitment.tests.test_resume_intelligence_api -v 1`：18/18 通过。
- `npm test`：43 个测试文件、265/265 通过。
- `npm run build`：Vite 生产构建通过。
- `manage.py check`、`makemigrations --check --dry-run`、`git diff --check` 和变更范围红线扫描通过。
- 应用内浏览器确认本地服务可访问；因真实账号删除具有破坏性，未对用户现有简历执行实删，文件系统副作用由隔离测试存储验证。
