# 招聘作业台四步界面 Design QA

## Evidence

- Source visual truth: `C:\Users\ADMINI~1\AppData\Local\Temp\codex-clipboard-4a7288ee-1417-4c0a-b06f-958bec27a43e.png`
- Source pixels: 1448 × 1086, four target states in a 2 × 2 board.
- Final browser viewport: 1542 × 1026 CSS pixels. Browser capture is 1713 × 1140 pixels (1.111 capture scale); card crops were density-normalized before comparison.
- Implementation states:
  - `design-qa-workbench-context-mid.png`
  - `design-qa-workbench-standard-mid.png`
  - `design-qa-workbench-plan-mid.png`
  - `design-qa-workbench-review-mid.png`
- Combined source/implementation comparison: `design-qa-workbench-comparison-mid.png`. Each row places the target on the left and the browser-rendered implementation on the right.
- State data: Python 后端工程师 · 技术部、招聘账号 A、3 条核心要求、2 条加分项、主动寻访 20 份、最大扫描 100 人。

## Fidelity Surfaces

- Layout: all four steps use the target's unified white task canvas, 250px pale-teal step rail, 1020 × 680 desktop card, 22px outer radius, fixed bottom action area, and two-column main forms where shown in the source. This is the user-selected middle size between the original 1080 × 720 and the smaller 972 × 648 pass.
- Typography: explanatory header copy is visually removed; only task titles, field labels, state labels, values, and safety-critical text remain. Titles are 26px/800 on desktop and body controls use 14–15px text.
- Colors: stage `#01a7af`, white surface, sidebar `#ecf7f7`, ink `#10213a`, teal primary, green completion state, amber blocked state, and cool gray borders match the reference family.
- Assets: existing local `AppIcon` SVG assets are used for upload, completed steps, job, account, search, and safety. No emoji, handcrafted SVG, CSS-art icon, or raster placeholder was introduced.
- Controls: native selects, radios, inputs, textareas, upload control, and action buttons retain their existing functionality. The candidate filter deliberately remains the existing dropdown form per the user's explicit instruction; its trigger was opened and closed successfully during browser QA.
- Copy: redundant explanatory paragraphs were removed from the visible UI. Business values, validation copy, diagnostics links, and service-side safety messaging remain intact.

## Full-view and Focused Comparison

- Full-view evidence covers all four workflow states at the same desktop viewport and data state.
- The combined comparison confirms the target hierarchy, sidebar proportions, control grouping, teal/white palette, footer placement, check-row structure, and use of line icons.
- The only intentional visual deviation is step 3's candidate filtering: the selected target shows all filters inline, while the implementation preserves the existing collapsible dropdown form as explicitly required.
- Runtime constraints remain truthful: the implementation displays the project's actual maximum scan value of 100 and the actual local-worker readiness, rather than fabricating the target mock's 2000/ready values.

## Comparison History

1. Initial P1: the original workbench mixed dense helper text, nested cards, inconsistent footer placement, and vertically scrolling content.
   - Fix: rebuilt the four states around one task canvas, simplified visible copy, introduced a consistent step rail and footer, and grouped only actionable content.
2. Initial P1: the first review implementation placed actions before summary data, collapsed checks into two columns, and hid ready-state details.
   - Fix: summary now precedes six single-row checks, all details remain visible, safety guidance follows the checks, and actions stay in the bottom footer.
3. Initial P2: first-pass controls and review rows were proportionally smaller than the selected visual.
   - Fix: increased desktop title, control, upload-zone, textarea, scheme-card, summary, check-row, and safety-panel dimensions while preserving the 720px card boundary.
4. Initial P2: isolated browser login state produced authentication alerts during visual QA.
   - Fix: repeated QA against a temporary SQLite database and fixed test-only authenticated session. No production authentication code or user data was changed.
5. Follow-up P2: the accepted 1080 × 720 workbench card felt too large in the live application shell.
   - Fix: reduced the card to exactly 972 × 648 (90%), scaled the sidebar and dense controls proportionally, and compacted only the plan-step rhythm enough to keep all persistent actions visible.
   - Post-fix evidence: `design-qa-workbench-comparison-90.png`; every step now has matching client/scroll dimensions and no internal overflow.
6. Follow-up P3: after seeing the 90% version in the application shell, the user requested a slightly larger card.
   - Fix: increased the card to 1020 × 680, restored proportional control and footer spacing, and retained the plan-specific compact rhythm.
   - Post-fix evidence: `design-qa-workbench-comparison-mid.png`; all four main regions still have matching client/scroll dimensions.

## Interaction and Runtime Checks

- Navigated among all four steps using the completed-step rail and footer actions.
- Verified job/account selection, requirements textareas, scheme radio selection, keyword and numeric inputs.
- Verified the unchanged candidate filter dropdown opens and closes and exposes its existing filter form.
- Review state correctly shows one blocked local-service check and disables execution without changing the server-side safety gate.
- Final desktop geometry: card 1020 × 680 with `scrollWidth === clientWidth`; every step main area is 669 × 608 with matching scroll dimensions.
- Targeted workbench tests: 31/31 passed.
- Full frontend suite baseline: 258/258 passed across 43 files; the final size-only pass reran the 31 workbench tests successfully.
- Production build: passed.
- Browser console: zero errors or warnings in the final middle-size QA pass.

## Findings

- No actionable P0, P1, or P2 visual, interaction, overflow, or runtime findings remain for this pass.

final result: passed

---

# 主动寻访条件浮层 Design QA（2026-08-27）

## Scope

- Source visual truth: `C:/Users/ADMINI~1/AppData/Local/Temp/codex-clipboard-2fbe6a50-36f8-4e34-9584-bad112fcbea0.png`
- Implementation screenshot: `polish/design-qa-candidate-filter/top-layer-597x309.png`
- Combined comparison input: `polish/design-qa-candidate-filter/comparison-1194x309.png`
- Source pixels: 597 × 309; implementation focused crop: 597 × 309; browser CSS viewport: 1280 × 720 at devicePixelRatio 1.
- State: “主动寻访条件”已展开，父卡片保持 `overflow: hidden`，浮层跨越卡片底边。

## Full-view and Focused Comparison

- The combined comparison places the original clipped state on the left and the revised open state on the right at equal pixel dimensions.
- Focused evidence is sufficient because this change is isolated to one dropdown layer: the revised form begins at the trigger edge, remains fully opaque above the white card and teal stage, and is no longer clipped at the card bottom.
- Runtime geometry: card bottom 242px; floating form top 170px and bottom 600px; `crossesCardBottom: true`; computed `position: fixed`; computed `z-index: 300`.

## Required Fidelity Surfaces

- Fonts and typography: unchanged from the source component; Chinese family, weights, sizes, line heights and wrapping are preserved.
- Spacing and layout rhythm: trigger width and row spacing remain unchanged; only the expanded form leaves normal flow and gains a 6px anchor gap plus viewport edge protection.
- Colors and visual tokens: the white/gold form, borders, selected pills and teal stage remain unchanged.
- Image and asset fidelity: no new raster, SVG, icon or decorative asset is introduced.
- Copy and content: all filter labels, options, helper copy and actions are unchanged.

## Comparison History

1. P1: the source state clipped the expanded filter form at the fixed-height workbench card, exposing the teal stage over the form and hiding remaining controls.
   - Fix: teleported the form to `body`, positioned it against the trigger with a top-layer fixed overlay, and bounded its height to the available viewport space.
   - Post-fix evidence: `polish/design-qa-candidate-filter/comparison-1194x309.png`; the form renders above the card and teal stage.
2. P2: a fixed overlay can drift or become inaccessible during scroll, resize or short viewports.
   - Fix: recalculate anchor geometry on scroll/resize, choose the side with more useful space, keep internal scrolling, close on outside pointer or Escape, and restore trigger focus.
   - Post-fix evidence: browser geometry checks plus 3/3 focused component tests.

## Findings

- No actionable P0, P1 or P2 layer, clipping, keyboard, focus or viewport findings remain.
- Final browser-rendered state has no new console error; the earlier temporary QA harness compiler warning was removed before the final capture.

final result: passed

---

# 招聘看板像素还原与响应式 Design QA

## Evidence

- Source visual truth: `C:\Users\ADMINI~1\AppData\Local\Temp\codex-clipboard-6e7b22cb-83fa-4fa0-8386-a725f73c7acf.png`
- Browser-rendered implementation: `C:\Users\Administrator\.codex\visualizations\2026\08\27\01a041ef-b7f9-7930-8220-ff0fe3c0578d\recruitment-dashboard-final.png`
- Full-view normalized comparison: `C:\Users\Administrator\.codex\visualizations\2026\08\27\01a041ef-b7f9-7930-8220-ff0fe3c0578d\recruitment-dashboard-comparison.png`（左为源图，右为实现）
- Focused main-region comparison: `C:\Users\Administrator\.codex\visualizations\2026\08\27\01a041ef-b7f9-7930-8220-ff0fe3c0578d\recruitment-dashboard-focus-main.png`（左为源图，右为实现）
- Responsive evidence: `recruitment-dashboard-1280.png`、`recruitment-dashboard-900.png`、`recruitment-dashboard-390.png`、`recruitment-dashboard-390-full.png`，均位于上述可视化目录。
- Source pixels: 1487 × 1058. Implementation pixels: 1487 × 1058. CSS viewport: 1487 × 1058. Density: 1 CSS px : 1 captured px; no density normalization or resampling was needed before the full-view comparison.
- State: authenticated normal recruitment-dashboard state using an isolated temporary SQLite preview database; production data and authentication code were not changed.

## Fidelity Surfaces

- Fonts and typography: Microsoft YaHei / YaHei UI fallback matches the existing Chinese product shell; title, panel heading, row label, secondary copy, KPI, date, and top-navigation hierarchy match the selected visual's scale and optical weight without wrapping at the target viewport.
- Spacing and layout rhythm: the target 284px sidebar, 75px topbar, 37px content inset, 1.475:1 main grid, 615px primary card, 451px position card, 152px risk card, 17px column gap, and five-part metric strip are reproduced. Full-view and focused comparisons show aligned card edges, dividers, row centers, progress tracks, and bottom strip.
- Colors and tokens: deep navy shell, pale blue-gray canvas, white cards, cool gray borders/copy, teal action/status color, amber warning pills, and red risk icon map directly to the source. No alternative palette or decorative gradient was introduced into the content surface.
- Image and asset fidelity: the target contains no photographic or illustrative raster assets. Visible product icons use the existing local SVG library plus `@lucide/vue` outline icons for the briefcase, person, document, calendar, and shield-alert forms. No emoji, text glyph, handcrafted SVG, inline SVG, placeholder art, or CSS-drawn icon is used.
- Copy and content: all static headings and helper copy match the source. Candidate/job counts, recruited headcount, current stage, and hired counts remain bound to the real dashboard response; therefore `0 / 2` and `面试推进` in the isolated data intentionally differ from the mock's static `1 / 2` and `简历筛选` while preserving the same typography and geometry.
- Responsiveness: the 1487px target preserves exact two-column proportions; 1280px keeps the same proportional grid; 900px switches the content cards to one column with the compact shell; 390px removes the sidebar rail, keeps an icon topbar, and stacks cards/metrics without horizontal clipping.

## Full-view and Focused Comparison

- The full-view comparison was inspected in one combined image at equal crop, pixel size, theme, route, and state. No major-region proportion, above-the-fold density, color, radius, or alignment mismatch remains.
- The focused comparison covers the highest-density surfaces at readable size: all four priority rows, both position-progress rows, progress tracks, warning pills, risk state, SVG alignment, small copy, and card dividers. Dynamic business values are the only intentional content deviations.

## Comparison History

1. Initial P1: the previous implementation used a dark decision card and additional analytics sections, materially changing the selected source hierarchy and above-the-fold density.
   - Fix: replaced the normal state with the selected single-screen structure: left priority card, right position/risk column, and bottom metric strip; constrained the shell dimensions only to the recruitment-dashboard route.
   - Post-fix evidence: `recruitment-dashboard-comparison.png`.
2. Initial P2: first pixel pass placed the main cards roughly 10px too low, the metric strip roughly 12px too high, and used generic project/warning icons in job and risk slots.
   - Fix: corrected hero-to-grid rhythm, metric margin, job-row spacing, column fractions, topbar account/model widths, and replaced the affected glyphs with matching outline icons from the icon library.
   - Post-fix evidence: `recruitment-dashboard-focus-main.png`; card and row boundaries now align with the source.
3. Follow-up P2: the first narrow-screen pass retained the 76px sidebar and desktop content inset at 390px, creating horizontal clipping.
   - Fix: introduced a route-scoped ≤680px shell, icon-only top navigation, 16px page inset, stacked hero controls, single-column metrics, and a 900px container breakpoint while keeping the two-column ratio at 1280px.
   - Post-fix evidence: `recruitment-dashboard-1280.png` and `recruitment-dashboard-390-full.png`. Measured document/body widths equal the available content width at 1487, 1280, 900, and 390; no horizontal overflow remains.

## Interaction and Runtime Checks

- Primary CTA navigates to `/recruitment/workbench?new=1&step=context&job=1`.
- “待联系候选人” navigates to `/recruitment/results?stage=to_contact&view=candidates`.
- Sidebar collapse and restore both work in the desktop shell.
- Responsive widths checked: 1487 × 1058, 1280 × 900, 900 × 1000, and 390 × 844. At every width `document.scrollWidth` and `body.scrollWidth` are no greater than the inner viewport width.
- Loading, error/retry, empty, and normal states are covered by the focused view tests.
- Focused tests: 15/15 passed. Full frontend suite: 43 files, 260/260 tests passed. Production build: passed.
- Browser console: the final stable build produced no new error entries. Two retained log entries at 07:18:30 reference a superseded asset hash from an earlier concurrent build and predate the final 07:21+ verification captures.

## Findings

- No actionable P0, P1, or P2 visual, interaction, overflow, accessibility, asset, or runtime findings remain.
- P3/intentional: dynamic preview values differ from the static mock in two job-detail labels; keeping server truth is preferred to fabricating business data.

final result: passed

---

# 管理后台五界面 Design QA

## Scope

- Reference: `polish/ideation-admin-five/selected-editorial-administration.png`
- Implementation: `frontend/src/views/recruitment/RecruitmentAdminView.vue`
- Comparison boards: `polish/design-qa-admin/comparison-full.png`, `polish/design-qa-admin/comparison-focus.png`, `polish/design-qa-admin/comparison-responsive-1280.png`, `polish/design-qa-admin/readable-five-screens-1280.png`, `polish/design-qa-admin/comparison-fluid-shell.png`
- Screens: 账号与浏览器、职位同步、流程方案、模型管理、系统诊断

## Visual review

- P0 blockers: none
- P1 major mismatches: none
- P2 noticeable mismatches: none
- P3 polish notes: the reference is a montage of differently cropped mini-frames; the implementation preserves the selected hierarchy, density, spacing, typography, color, controls, card/table treatment, and five-screen composition at the product's desktop viewport.
- Readability iteration: the 1280 × 720 baseline now uses a 30px page title, 16px tabs/body copy, 15px buttons, a 19px account title, a 58px tab rail, and a 274px account card. Fluid `clamp()` sizing grows these surfaces through 1080p, 2K, and 4K while capping the content canvas at 2000px on ultrawide displays.
- Five-screen browser verification: `polish/design-qa-admin/readable-accounts-1280x720.png`, `readable-jobs-1280x720.png`, `readable-workflows-1280x720.png`, `readable-models-1280x720.png`, and `readable-diagnostics-1280x720.png`.
- At 1280 × 720 the document and admin canvas have no horizontal overflow. The workflow action column uses a dedicated 1280–1400px grid contract so its full action set remains visible without shrinking the type.
- Model-management readability pass: its empty-state title/body now start at 24/18px, table headings at 16px, and configured-model names/details/actions at 15–20px. This deliberately gives the model page one larger type tier without changing the other four screens.
- Shell-proportion pass: the admin sidebar now scales from 272px at laptop width toward 17.5vw and caps at 380px; the top navigation scales from 82px to 104px. Brand, navigation typography, icons, status controls, spacing, and avatar scale with those two rails instead of remaining visually narrow on larger displays.
- Stable-shell browser contract: the root page permanently reserves its vertical scrollbar gutter, so switching among short and long admin tabs cannot change the shell's available width. At 1280 × 720 all five tabs must measure the same sidebar, topbar, admin-root, and document client width, with no horizontal overflow.
- Stable-shell runtime result: every tab measured exactly `1265px document / 272px sidebar / 993px topbar / 993px admin root`; document `clientWidth` and `scrollWidth` were both 1265px on all five screens. Capture: `polish/design-qa-admin/stable-shell-1280x720.png`.
- Cross-route shell contract: every expanded application shell uses the same sidebar token, overriding the previous 244px attendance/workbench, 230px results, 284px dashboard, and 272px admin variants. This covers both left-side module switching and top recruitment navigation; the collapsed 82px state remains the only intentional width change.
- Cross-route runtime result: 管理后台、招聘看板、招聘作业台、结果中心、考勤管理，以及从考勤返回招聘，全部实测为 `272px sidebar / 993px topbar / 1265px document client width`; no route transition changed the shell width.
- Cross-route element contract: expanded shells also share identical sidebar padding, 50px brand mark, 19px brand name, 64px navigation rows, 25px navigation icons, 17px navigation labels, 52px service state, 82px topbar, 17px top links, 24px top-link icons, 42px avatar, and stable model/account trigger widths at the 1280px viewport.
- Result-center model switcher no longer uses the compact prop; every recruitment top route now renders the same 178px × 40px switcher used by management administration.
- Final management-admin baseline comparison returned zero geometry diffs for 招聘看板、招聘作业台、结果中心、管理后台、考勤管理 and the return to 招聘管理. The measured baseline was 272px sidebar, 50px brand mark, 64px side rows, 25px side icons, 82px topbar, 17px top links, 24px top icons, 178×40px model switcher, 185×42px account trigger, and 42px avatar.
- Icon iteration: all shared UI glyphs now render as real 24 × 24 rounded-line SVGs with `fill="none"`, `stroke="currentColor"`, `stroke-linecap="round"`, and 1.8px strokes, matching the reference's outline icon language.

## Runtime review

- Five sub-navigation tabs switch to the correct active screen.
- Current/archive filters and the add-account dialog respond correctly.
- Browser console warnings/errors: none.
- Frontend test suite: 43 files, 260 tests passed.
- Production build: passed.

final result: passed
