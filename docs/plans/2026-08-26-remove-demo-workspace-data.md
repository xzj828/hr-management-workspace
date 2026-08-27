# Remove Demo Workspace Data

Date: 2026-08-26
Status: completed

## Scope

Remove only the locally loaded demo workspace data that is rendered by the frontend:

- attendance employees whose employee number starts with `DEMO-`;
- attendance import batches whose original filename starts with `演示考勤-`, including their dependent raw days, results, suspicions, and generated source files;
- recruitment jobs, candidates, applications, and resumes explicitly marked `is_demo=True`, including their generated resume files.

## Safety boundary

Preserve all non-demo records and operational state, including BOSS accounts, RPA tasks and events, audit records, workers, attendance policies, and non-demo tags. Use the existing `load_demo_workspace --clear` command rather than broad table deletion. Compare pre-clear and post-clear counts for every preserved category.

## Acceptance criteria

- All marked attendance and recruitment demo records are removed.
- All corresponding real-record counts are unchanged.
- BOSS/RPA/audit/worker and attendance configuration counts are unchanged.
- Frontend production source remains API-backed; test fixtures and demo markers are not deleted.

## Design impact

Pure local data cleanup. No architecture, API, data model, UI, dependency, or product-design change.

## Verification result

- Demo database counts after cleanup: attendance employees 0, batches 0, raw days 0, results 0, suspicions 0; recruitment jobs 0, candidates 0, applications 0, resumes 0.
- Preserved counts were unchanged: BOSS accounts 3, RPA tasks 23, RPA events 92, audit records 67, workers 1, attendance policies 5, and non-demo tags 3.
- The command removed active demo records. Five historical orphan demo files (three generated resumes and two attendance workbooks) had no remaining database references and were removed separately after exact-path verification.
- Backend cleanup tests: 8 passed. Frontend tests: 246 passed across 41 files. Frontend production build: passed.
- Authenticated runtime GET checks returned HTTP 200 and empty lists for employees, imports, recruitment jobs, candidates, and resumes; the recruitment demo status returned zero for all four counters.
