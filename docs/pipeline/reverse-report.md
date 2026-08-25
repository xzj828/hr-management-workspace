# 西鸣人事管理系统 — 逆向报告

> 来源：从现有代码库逆向生成 | 生成时间：2026-08-24

逆向文档生成完成 — 西鸣人事管理系统（2026-08-24）

## 项目概况

- 技术栈：Vue 3 / Vite 7 / Pinia / ECharts + Django 5.2 / DRF 3.16 + SQLite/PostgreSQL + 本机 RPA Worker。
- 规模：261 个文件，约 25,032 行可读文本代码与文档。
- 形态：Windows 本地/局域网部署的模块化单体；当前目录不包含 Git 元数据。

## 已生成文档

- `docs/autodev-ideation.md`：7 个平台能力 + 12 个业务场景，以及产品优先级。
- `docs/autodev-design.md`：架构、4 个核心组件域、权限和技术决策。
- `docs/autodev-ui.md`：13 个现有可访问页面及完整交互/四态设计。
- `docs/autodev-api.md`：36 个数据模型、认证权限、88 个路由模板及关键端点规则。
- `docs/autodev-index.md`：小于 100 行的知识与代码地图。
- `docs/autodev-rules.md`：小于 80 行的实现、安全与质量约束。
- 根目录 `AGENTS.md`：以上文档的发现入口。

## 覆盖率

- 路由/现有页面：13/13。
- API 路由模板：88/88（含 DRF Router 生成的资源路径与自定义动作）。
- 自定义 ViewSet 动作：23/23。
- 具体数据模型：36/36。
- 主要代码域：accounts、attendance、recruitment、RPA、workflow、frontend shell、Windows scripts 全部有文档落点。

## 完整性备注

- `RecruitmentPlaceholderView.vue` 已不被路由引用，作为遗留组件在 UI 文档中单独标记。
- 测试文件显示业务和安全边界有广泛自动化覆盖；逆向时本机尚未安装 `.venv` 与 `node_modules`，因此本报告的覆盖率是静态结构覆盖，不等同于运行时测试通过率。
- 共 1 处 `[推断]` 与 11 处 `[待确认]` 需要产品/业务负责人审阅，集中在目标企业规模、部门数据权限、真实 BOSS 写操作和实际使用指标。

## 后续建议

1. 用项目内置招聘演示数据和独立本地数据库进行真实前后端验收。
2. 优先打通“录用候选人 → 员工档案 → 考勤策略”，兑现统一 People OS 的价值主张。
3. 落实部门级数据权限，再让 Supervisor/Viewer 进入实际使用。
4. 运行 Vitest、Django 测试、生产构建和浏览器验收，补齐运行时证据。
5. 后续代码变化可用 `autodev-sync` 检查设计漂移。
