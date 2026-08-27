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
