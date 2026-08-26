# Recruitment Workbench — Reference Round 2 独立评分卡

## 结论

**18/20 — NEEDS_IMPROVEMENT**

| 维度 | 分数 | 判定 |
|---|---:|---|
| Design System Compliance | 5/5 | 关键颜色、尺寸、分栏、圆角、阴影与字号均精确收敛到页面级 token。 |
| Visual Craft | 4/5 | 整体已接近专业成品，但步骤切换保留内部滚动位置，使 03/04 的首屏层级不完整。 |
| Coherence | 5/5 | 四步共享同一外框、同一左栏与同一控件语言，没有重新退化为传统后台拼卡。 |
| Functionality Preservation | 4/5 | 定向测试全部通过，但“切换新步骤从顶部呈现”存在可见回归，不能给 5。 |

硬 PASS 条件未满足：虽然总分达到 18，Craft 与 Coherence 均不低于 4，且四步结构要求已满足，但 Functionality 不是 5；实际桌面步骤切换也没有从新步骤顶部开始。

## 逐项证据

### 1. Design System Compliance — 5/5

- `RecruitmentWorkbenchView.vue:1706-1810` 集中定义 `--wb-*` 颜色、字号、间距、尺寸、圆角和阴影；颜色扫描只命中该 token 区，没有在具体规则中散落 hex/rgb/hsl。
- 舞台、主色、左栏、表面、文字、边框分别精确使用 `#00bfc1`、`#00aeb1`、`#e8f8f8`、`#ffffff`、`#0f172a`、`#e2e8f0`；阴影为单层 `0 20px 60px rgba(4,75,78,.20)`。
- 桌面 token 为主卡 `880 × 570px`、左栏 `230px`、表单 `520px`、外圆角 `32px`（`RecruitmentWorkbenchView.vue:1764-1775`）。四张 1280×720 截图中外框均稳定在约 880×570，符合最新用户目标。
- 可见排版收敛为 26 / 18 / 14 / 12 四层（`RecruitmentWorkbenchView.vue:1734-1739`）；截图中当前任务标题、左栏标题、正文控件、辅助文字层级清楚，没有英文 kicker 或重复“招聘作业台”标题竞争。

### 2. Visual Craft — 4/5

- `reference-round-2-context.png` 第一眼已经是高饱和青蓝舞台上的唯一白色圆角阴影主卡；左右 230/650 分栏比例舒适，职位与账号纵向对齐，主按钮与表单同宽。
- `reference-round-2-standard.png` 的上传区、两列文本域和滚动轨道均落在右侧工作区内部；左栏和外轮廓没有随长内容跳变。岗位参考资料界面不存在用途 selector。
- `reference-round-2-plan.png` 与 `reference-round-2-review.png` 暴露同一个明显缺口：进入 03 时方案选择卡已在可视区上方，画面直接从“运行流程”开始；进入 04 时“本次作业”摘要已在可视区上方，画面直接从检查项开始。这破坏了新任务首屏应有的标题 → 说明 → 首要内容层级，因此扣 1 分。
- `reference-round-2-review-720.png` 中主卡仍是一个共享外框，步骤摘要为 2×2，检查项单列，未见横向裁切；移动端采用页面自然滚动，整体节奏合理。

### 3. Coherence — 5/5

- context / standard / plan / review 四张桌面截图共享完全一致的舞台、880×570 外框、230px 左栏起始线、32px 圆角和单层阴影。
- 四步名称和职责完整且一致：01 职位与账号、02 招聘标准、03 执行方案、04 执行前检查（`RecruitmentWorkbenchView.vue:136-147`）。
- 当前步骤只使用白色浅面板 + 实心青蓝编号；完成步骤使用描边/浅底编号；右区只保留当前任务标题。控件、上传、radio、检查列表和按钮均使用同一套圆角、细边框、字号与青蓝状态语言。
- 04 的检查、阻塞原因和唯一正式动作已经并入同一右工作区，不存在独立检查浮卡。

### 4. Functionality Preservation — 4/5

- 定向命令 `npm test -- --run src/views/recruitment/RecruitmentWorkbenchView.test.js` 通过：**33 tests passed**。
- 定向测试验证了四步守卫、浏览器前进后退、03 不出现 precheck/开始执行、进入 04 不产生 POST，以及正式动作仅在 04 出现（`RecruitmentWorkbenchView.test.js:170-219`）。
- 用途 selector 已删除；上传固定提交兼容类别 `persona`，实现见 `RecruitmentWorkbenchView.vue:19,1091`，测试见 `RecruitmentWorkbenchView.test.js:423-462`。
- 03 的推进函数 `completePlanStep()` 只完成草稿状态并导航到 review（`RecruitmentWorkbenchView.vue:664-668`）；03 模板仅显示“下一步：执行前检查”，04 才渲染 precheck 与“开始执行”（`RecruitmentWorkbenchView.vue:1539-1670`）。
- 不能给 5 的证据：桌面右区在 `RecruitmentWorkbenchView.vue:3895-3904` 使用持续存在的 `.workbench-main { overflow-y: auto }`；`focusCurrentStep()` / `navigateWizardStep()` 只聚焦标题和切换路由（`RecruitmentWorkbenchView.vue:587-640`），没有将该滚动容器复位到 `scrollTop = 0`。Vue 替换当前 section 时容器本身不重建，因此保留旧 scrollTop；plan/review 截图正好记录了该结果。当前 33 个测试也没有 scrollTop 断言。

## 用户结构要求核验

- [x] 高饱和青蓝舞台 + 单一白色圆角阴影主卡。
- [x] 桌面约 880×570、左栏约 230px，比例稳定舒适。
- [x] 可见字号只有 26 / 18 / 14 / 12 清晰层级。
- [x] 岗位参考资料无用途 selector，上传固定 `persona`。
- [x] 四步名称准确，01/02/03/04 均独立存在。
- [x] 03 不显示检查、阻塞原因或开始执行，只推进到 04。
- [x] 04 独立显示摘要、检查、处理入口与唯一开始动作。
- [ ] 桌面切换到新步骤时从右区顶部呈现。
- [x] 桌面长内容只滚动右工作区；≤900px 恢复页面自然滚动；≤720px 为 2×2 步骤摘要且截图无可见横向溢出。

## 与参考图仍有的视觉差距

目标参考图的右区每次进入任务都从明确的首要内容开始；当前 03/04 在桌面切换后继承前一步滚动位置，首要方案卡或作业摘要消失在首屏上方。其余构图语言已经合理转译：饱和舞台、偏竖向单卡、浅色左栏、宽主按钮和克制阴影均已达到要求，且没有复制参考图的品牌或无关文案。

## 最高价值修复（最多 3 项）

1. 给 `.workbench-main` 增加模板 ref；每次步骤键实际变化后在 `nextTick` 中将桌面内部滚动容器无动画复位到顶部，再聚焦当前标题。路由前进/后退和直接点击左侧步骤也必须走同一逻辑。
2. 增加定向交互测试：先人为设置 standard 的 `scrollTop > 0`，推进到 plan 并断言 `scrollTop === 0`；再滚动 plan、推进到 review，断言摘要为首个可见内容且 `scrollTop === 0`。同时覆盖浏览器 back/forward。
