# Round 1 Changelog

## 视觉层级与 Token

- `frontend/src/views/recruitment/RecruitmentDashboardView.vue:135` — 建立招聘看板局部视觉 token，统一引用既有 Paper / Ink / Slate / Teal / Line 颜色、4px 间距刻度、15px 面板圆角、克制阴影和 160ms 反馈动效。
- `frontend/src/views/recruitment/RecruitmentDashboardView.vue:198` — 将 5 个核心 KPI 固定为一条横向指标带，并复用考勤看板的主 KPI 深墨色强调与同源字号、边框、圆角。
- `frontend/src/views/recruitment/RecruitmentDashboardView.vue:635` — 按 1050px 将双列工作区收为单列，按 720px 将 KPI、简历智能和今日工作收为两列，并在更窄视口继续收为单列，避免页面横向溢出。

## 面板与紧凑列表

- `frontend/src/views/recruitment/RecruitmentDashboardView.vue:83` — 为“今日工作 / 风险提醒”增加单一外层主面板 wrapper，两个业务区改由面板内分割线建立层级。
- `frontend/src/views/recruitment/RecruitmentDashboardView.vue:109` — 为“招聘漏斗 / 近 7 天趋势”增加单一主分析面板 wrapper，并扩大趋势区视觉占比。
- `frontend/src/views/recruitment/RecruitmentDashboardView.vue:262` — 将简历智能区从大面积深绿横幅改为白色紧凑面板，四个入口使用内部纵向分隔，不再使用独立小卡片或衬线数字字体。
- `frontend/src/views/recruitment/RecruitmentDashboardView.vue:374` — 清除组合工作区内层面板的重复边框、圆角和阴影，改用一条内部边界分隔主次区域。
- `frontend/src/views/recruitment/RecruitmentDashboardView.vue:395` — 将今日工作项改为紧凑分割列表，保留图标、状态说明、数量、箭头和原跳转。
- `frontend/src/views/recruitment/RecruitmentDashboardView.vue:446` — 将风险项改为无小卡边框的行列表，以警告 / 危险色状态条和文本动作保留风险语义。
- `frontend/src/views/recruitment/RecruitmentDashboardView.vue:491` — 将职位进度和最近自动化改为带面板标题分割线的全宽行列表，统一行高、文本层级、悬停与焦点反馈。
- `frontend/src/views/recruitment/RecruitmentDashboardView.vue:552` — 将招聘漏斗改为带行分割线的紧凑数据列表，并让近 7 天趋势作为主分析区获得更充足图表高度。

## 功能保持与验证

- `frontend/src/views/recruitment/RecruitmentDashboardView.vue:1` — 未修改指标计算、API、路由目标、空态、事件处理或任何 `data-test`；仅新增视觉 class / wrapper class 与 scoped CSS。
- `frontend/src/views/recruitment/RecruitmentDashboardView.test.js:40` — 定向 Vitest 通过：6 tests passed。
- `frontend/package.json:8` — `npm run build` 通过；Vite 完成 684 个模块转换，仅保留既有的大 chunk 体积提示。

## 未处理项

- 无。
