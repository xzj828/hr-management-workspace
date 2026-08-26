# Refresh Job Context After Position Sync

Date: 2026-08-26
Status: completed

## Problem

Position synchronization succeeds and persists an open BOSS position, but the recruitment workbench can continue to show that no open positions exist because the shared Pinia recruitment context cached an empty list before synchronization.

## Solution

After a successful position-sync task, refresh both the administration page's local job list and the shared recruitment context with `force=true`. Preserve the existing authenticated `GET /api/recruitment/jobs/?status=open` data source and do not synthesize or duplicate positions.

## Acceptance criteria

- A successful position sync refreshes the shared open-position store immediately.
- A previously cached empty store contains the newly synchronized open position without a full browser reload.
- Existing synchronization summary and local job-table behavior remain unchanged.
- No backend API, data model, or external-action behavior changes.

## Design impact

Pure frontend cache-coherency bug fix. No architecture, API, data model, dependency, or visual-design change.

## Verification

- Regression test reproduces a previously cached empty job context and confirms that successful synchronization refreshes it with the open position.
- Focused administration tests passed: 21/21.
- Full frontend tests passed: 246/246 across 41 files.
- Production frontend build and static collection succeeded.
- The Web service was restarted and serves the new JavaScript asset with HTTP 200 and a JavaScript MIME type.
- Authenticated runtime checks return one open position (`前置部署工程师`), dashboard `open_jobs=1`, Worker online, and CLI available.
