# BOSS Worker Offline Recovery

Date: 2026-08-26
Status: completed

## Problem

The frontend reported that position synchronization prerequisites were not met even though `@joohw/boss-cli` had already been installed.

## Evidence and root cause

- Local CLI discovery resolves to the trusted `node.exe + dist/cli/index.js` invocation.
- `boss-cli --version` returns `@joohw/boss-cli 0.6.6`.
- The latest persisted Worker heartbeat was stale and the authenticated automation summary reported the Worker as offline.
- No `run_rpa_worker` process was running. The original launcher parent process was gone while its Waitress child remained running.

## Recovery

Start the existing RPA Worker with the configured virtual environment and backend working directory. Verify a fresh heartbeat, `worker.status=online`, `cli_available=true`, and the advertised `sync_positions` capability. Do not change account data or automatically start an external synchronization task.

## Design impact

Runtime recovery only. No architecture, API, data model, dependency, or UI change.

## Verification

- The RPA Worker remained running across a complete heartbeat interval.
- The authenticated automation summary returned `worker.status=online` and `cli_available=true`.
- The Worker advertised enabled `sync_positions` capability through the CLI adapter.
- The active account `北京测试1` remained in `ready` login state.
- Focused Worker and RPA API tests passed: 49/49.
- No position synchronization task was created automatically.
