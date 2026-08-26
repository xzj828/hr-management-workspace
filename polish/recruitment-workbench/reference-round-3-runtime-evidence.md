# Recruitment Workbench — Reference Round 3 Runtime Evidence

## Environment

- Production frontend build served through Django/Waitress at `http://127.0.0.1:8771`.
- Synthetic isolated evaluation database only; no production data or external action was used.
- Desktop viewport: `1280 × 720`; narrow viewport: `720 × 900`.

## Desktop evidence

- Shared shell remains `880 × 570px`, with `230px` left rail and `650px` workspace.
- Standard → Plan navigation landed on `scrollTop = 0`; the two execution scheme cards were visible at the top of step 03.
- Plan → Review navigation landed on `scrollTop = 0`; the “本次作业” summary was visible at the top of step 04.
- Step 03 rendered the plan editor and `complete-plan-step`, with no review block and no `start-execution` action.
- Step 04 rendered the summary, six preflight checks, and the sole `start-execution` action.

## Narrow evidence

- At `720px`, all four navigation items measured exactly `269 × 58px`.
- Step 04 checks remained a compact two-column grid (`262.5px 262.5px`).
- The step 04 shell height reduced from the prior `1044px` single-column layout to `888px` without horizontal overflow.
- The shared shell, 2×2 step navigation, summary, checks, start action, and safety copy remained inside one rounded card.

## Console and automated checks

- Browser console logs: `[]`.
- Targeted Vitest: `34/34` passed.
- Production build completed successfully.

## Screenshots

- `reference-round-3-context.png`
- `reference-round-3-standard.png`
- `reference-round-3-plan.png`
- `reference-round-3-review.png`
- `reference-round-3-review-720.png`
