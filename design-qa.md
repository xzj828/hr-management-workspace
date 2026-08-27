# 结果中心字号与栏目宽度 Design QA

## Evidence

- Source visual truth: `design-qa-before.png`
- Source role: user-marked problem reference rather than a target to reproduce; the explicit acceptance contract is more comfortable Microsoft YaHei typography, wider fields/columns, less arbitrary bolding, and responsive proportions.
- Source pixels: 1700 × 280 at the captured candidates-table state.
- Wide implementation: `C:\Users\Administrator\Desktop\hr-management-workspace-master\design-qa-final-wide.png`
- Wide implementation pixels: 1685 × 892 from a 1700 × 900 CSS viewport, DPR 1; the 15px scrollbar accounts for the image-width difference.
- Default implementation: `C:\Users\Administrator\Desktop\hr-management-workspace-master\design-qa-final-full.png`
- Default implementation pixels: 1265 × 1507 from the browser's 1280 × 720 default viewport, DPR 1.
- Small implementation: `C:\Users\Administrator\Desktop\hr-management-workspace-master\design-qa-final-small.png`
- Small implementation pixels: 375 × 812 from a 390 × 844 CSS viewport, DPR 1.
- Combined comparison: `C:\Users\Administrator\Desktop\hr-management-workspace-master\design-qa-comparison.png`
- State: 结果中心 → 候选人与简历，2 位候选人，默认筛选。

## Fidelity Surfaces

- Fonts and typography: Microsoft YaHei / Microsoft YaHei UI is active throughout. Candidate-table body and controls are 15px, headers and supporting copy are 14px, normal content is weight 400, and only headings/primary labels use weight 600. Body line-height is 1.6; results copy uses 1.45–1.65 according to density.
- Spacing and layout rhythm: wide filters resolve to five 238px fields plus the clear action; candidate table resolves to 1638px with materially wider name, stage, recommendation, resume, HR, and notification columns. At container widths of 1180px or less, candidates become two-column record cards; at 820px or less they become single-column cards. No document-level horizontal overflow was present at 1920, 1700, 1366, 1024, or 390 checks.
- Colors and visual tokens: existing slate, teal, paper, line, warning, and state tokens are unchanged. Typography and spacing adjustments do not introduce a new palette or heavier decoration.
- Image quality and asset fidelity: this screen has no content imagery. Existing icon assets remain in use; no placeholder, emoji, CSS-art, or generated raster replacement was introduced.
- Copy and content: business copy and state labels remain unchanged. The useless empty operation dash is hidden in record-card mode; error, warning, and human-review copy is preserved.

## Full-view and Focused Comparison

- Full-view evidence: wide and default screenshots confirm the page shell, overview, filters, tabs, table/cards, and footer remain aligned without document overflow.
- Focused evidence: `design-qa-comparison.png` puts the original problem screenshot and the wide final candidates region in one image. It confirms the visible increase from 13/14px to 14/15px, taller rows, wider filter controls, reduced letter spacing, and wider semantic columns.

## Comparison History

1. Initial P1: Microsoft YaHei was rendered with a 13px table header, 14px body, browser-default line-height, 190px filters, and a 1480px ten-column table. The result looked compressed and visually uneven.
   - Fix: set a 14px system base with 1.6 line-height; results meta/header to 14px, body/control to 15px, and table width to a 1600px minimum / 1638px resolved width. Filters now use the available width instead of stopping at 190px.
   - Post-fix evidence: `design-qa-final-wide.png`; header 14px, body 15px, five filters at 238px, no console warning/error.
2. Initial P2: at 1280/1366 widths, preserving ten wide columns required horizontal scrolling and delayed access to the rightmost fields.
   - Fix: add a two-column candidate record-card layout at container widths ≤1180px, retaining all labels and values; retain the table on wide monitors.
   - Post-fix evidence: `design-qa-final-full.png`; 1280 viewport resolves a 36px selector rail plus two 422px information columns with no document overflow.
3. Initial P2: candidates without a resume produced an unlabeled, empty operation row in card mode.
   - Fix: hide the empty operation cell while preserving the real action cell when a detail action exists.
   - Post-fix evidence: final default screenshot; card height reduced from 370px to 302px and the useless dash row is absent.

## Interaction and Runtime Checks

- AI recommendation filter was changed to `advance` and cleared back to `all`; both controls updated correctly.
- Production build completed successfully.
- RecruitmentResultsView targeted suite: 22/22 tests passed.
- Browser console: zero warnings or errors in final wide, default, and small checks.
- Local production server on port 8000 was restarted after the final build and returned a healthy CSRF response.

## Findings

- No actionable P0, P1, or P2 visual or responsive findings remain for this pass.

## Follow-up Polish

- P3: the 390px shell retains the product's existing icon-only sidebar. The results content itself has no horizontal overflow and remains readable; a future shell-wide mobile-navigation redesign could reclaim additional width, but it is outside this results-center typography pass.

final result: passed
