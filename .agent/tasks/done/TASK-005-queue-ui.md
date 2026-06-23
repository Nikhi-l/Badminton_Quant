# TASK-005: Job queue UI + `GET /api/jobs`

**Status:** done (2026-06-23) — list endpoint + queue UI with live status. Verified
(unit test + preview).
**Branch:** `feat/TASK-005-queue-ui`
**PRD section:** §3 / §7 / §8 (queue), §16 P1

## Goal
Show submitted jobs in a queue with live status (queued / processing / done /
failed), the CPU/GPU pipeline, submission + generation time, and the error on
failed jobs — using the TASK-003/004 timing fields.

## Delivered
- `db.recent_jobs(limit)` — all jobs newest-first (any status).
- `GET /api/jobs` (`jobs_queue`) — id, filename, status, stage, message, error
  (failed only), pipeline, submitted_at, gen_seconds, expected_gen_seconds, and a
  thumb for done jobs.
- Frontend `web/`: a "Your queue" section (`#queueSection`) listing the user's jobs
  (filtered by the `myJobs` localStorage set) with status chips, pipeline, relative
  submit time, live stage, gen/expected time, failed-job error, and a "Studio"
  button for done jobs. Live-polls every 4s while any job is queued/processing;
  refreshed on upload and on job completion.

## Verification
- Unit: `test_jobs_queue_lists_all_statuses_newest_first` — all statuses present,
  newest-first, error only on failed, thumb on done, pipeline derived.
- Preview: `renderQueue` with 4 mock jobs → 4 cards, chips
  processing/done/failed/queued, error shown, 1 Studio button, thumb present.
- `./scripts/check.sh` → 17 passed; no console errors.

## Follow-up
- Optional: a dedicated server-side per-user filter (single-tenant today; the client
  filters by its own job ids).
