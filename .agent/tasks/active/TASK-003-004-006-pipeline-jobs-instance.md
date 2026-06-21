# TASK-003/004/006: Pipeline metadata, job timing, and instance sizing

**Status:** TASK-003/TASK-004 deployed; TASK-006 migration decision guarded
**Branch:** `feat/TASK-003-004-006-pipeline-jobs-instance`
**Base SHA:** `9675536`
**PRD section:** §4a two inference pipelines, §6 job model, §16 P1 remediation,
§P1-INSTANCE

## Goal
Complete the P1 runtime metadata slice: each job must record whether it is on the
CPU or GPU pipeline, generation timing must be first-class in SQLite/API output,
failed jobs must use the canonical `failed` status, and the GCP instance-sizing
state must be verified against the TASK-006 decision.

## Acceptance criteria
- [x] `jobs` table has additive `pipeline`, `started_at`, and `finished_at`
      columns.
- [x] Existing deployed DB rows migrate without dropping data.
- [x] New jobs record `pipeline=cpu|gpu` from normalized options
      (`shuttle=tracknetv3` means GPU; otherwise CPU).
- [x] Jobs transition through `queued` -> `processing` -> `done|failed`.
- [x] Job API exposes `submitted_at`, `started_at`, `finished_at`,
      `gen_seconds`, `pipeline`, and separate expected generation budgets.
- [x] Frontend polling handles `failed` and shows pipeline/timing context.
- [x] Production DB migration is verified on the GCP VM.
- [x] Current GCP instance shape is verified.
- [x] Current production IP is promoted to a reserved static IP before any
      stop/start resize risk.
- [ ] Full TASK-006 cutover to the PRD target
      (`c2d-standard-8`, `asia-south1-a`) is executed. This still needs DNS
      cutover/region migration choice because `baddyai.com` currently points to
      the existing us-central1 VM IP.

## Verification commands
- `.venv/bin/python -m pytest tests/unit/test_job_model.py -q`
- `node --check web/app.js`
- `./scripts/check.sh`
- `ZONE=us-central1-a MACHINE=e2-standard-4 bash deploy/deploy.sh`
- `gcloud compute ssh baddy-agent --zone us-central1-a --command '...'`
- `python3 - <<'PY' ... https://baddyai.com/api/jobs/989cdb218317 ... PY`
- `gcloud compute addresses list --format='table(name,address,region.basename(),status,users.basename())'`

## Production evidence
- Live DB columns now include `pipeline`, `started_at`, `finished_at`.
- Live status vocabulary is now `done`/`failed`; legacy `error` rows migrated.
- Live pipeline counts after migration: `cpu=9`, `gpu=5`.
- All 14 live terminal jobs have timing backfilled.
- Latest GPU job `989cdb218317` reports `gen_seconds=424.6` and
  `expected_gen_seconds=600` through `https://baddyai.com/api/jobs/{id}`.
- Live VM remains `baddy-agent`, `us-central1-a`, `e2-standard-4`.
- `136.113.208.173` is reserved as static regional address `baddy-agent-ip`.

## Risks / rollback
- Full Mumbai migration needs a new regional VM/IP and DNS cutover for
  `baddyai.com`; current repo defaults point new deployments at TASK-006 target
  but production was updated in-place with explicit old-zone overrides.
- rollback code: deploy `origin/main` back to the current VM with
  `ZONE=us-central1-a MACHINE=e2-standard-4 bash deploy/deploy.sh`.
