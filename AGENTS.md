# Project Guidance

## Design Docs

- `docs/autodev-ideation.md` — 产品定位、功能清单、完成度与产品优先级（逆向生成）
- `docs/autodev-design.md` — 架构、组件关系、边界与技术决策（逆向生成）
- `docs/autodev-ui.md` — 页面、流程、四态、视觉与响应式规范（逆向生成）
- `docs/autodev-api.md` — 数据模型、权限、端点与第三方集成（逆向生成）
- `docs/autodev-index.md` — 开发者知识地图
- `docs/autodev-rules.md` — 编码约束、安全红线与验证要求
- `docs/superpowers/specs/` — 既有专项设计文档，保留作为历史设计证据
- `docs/superpowers/plans/` — 既有专项实施计划，保留作为历史实施证据

修改代码前先阅读 `docs/autodev-index.md` 和适用范围内的设计文档；自动化、身份、权限或文件处理变更必须遵守 `docs/autodev-rules.md`。

## Deployment

- 完成代码修改并通过适用测试后，默认自动部署到本机服务器，不等待额外提醒。
- 部署前备份涉及迁移的生产数据；部署时完成前端生产构建、数据库迁移、服务重启与健康检查。
- 部署失败时保留可恢复状态并明确报告，不把“测试通过”当作“部署完成”。
