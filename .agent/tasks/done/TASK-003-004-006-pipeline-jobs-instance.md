# TASK-003/004/006: Pipeline metadata, job timing, and instance sizing

**Status:** done (Cycle 7, 2026-06-21)
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
- [x] TASK-006 production sizing is applied: live VM is `c2d-standard-8` with
      the existing static production IP preserved.

## Verification commands
- `.venv/bin/python -m pytest tests/unit/test_job_model.py -q`
- `node --check web/app.js`
- `./scripts/check.sh`
- `ZONE=us-central1-a MACHINE=e2-standard-4 bash deploy/deploy.sh`
- `gcloud compute ssh baddy-agent --zone us-central1-a --command '...'`
- `python3 - <<'PY' ... https://baddyai.com/api/jobs/989cdb218317 ... PY`
- `gcloud compute addresses list --format='table(name,address,region.basename(),status,users.basename())'`
- `gcloud compute instances stop baddy-agent --zone us-central1-a --quiet`
- `gcloud compute instances set-machine-type baddy-agent --zone us-central1-a --machine-type c2d-standard-8 --quiet`
- `gcloud compute instances start baddy-agent --zone us-central1-a --quiet`
- `curl -fsS https://baddyai.com/api/health`

## Production evidence
- Live DB columns now include `pipeline`, `started_at`, `finished_at`.
- Live status vocabulary is now `done`/`failed`; legacy `error` rows migrated.
- Live pipeline counts after migration: `cpu=9`, `gpu=5`.
- All 14 live terminal jobs have timing backfilled.
- Latest GPU job `989cdb218317` reports `gen_seconds=424.6` and
  `expected_gen_seconds=600` through `https://baddyai.com/api/jobs/{id}`.
- Live VM is now `baddy-agent`, `us-central1-a`, `c2d-standard-8`.
- `136.113.208.173` is reserved as static regional address `baddy-agent-ip`.
- `baddyai.com` still resolves to `136.113.208.173` and returns `HTTP/2 200`.

## Risks / rollback
- Mumbai remains a future DNS-backed migration option. DNS is hosted at GoDaddy
  (`domaincontrol.com`), not in this GCP project, so TASK-006 was completed as an
  in-place `c2d-standard-8` resize on the existing static production IP.
- rollback code: deploy `origin/main` back to the current VM with
  `ZONE=us-central1-a MACHINE=c2d-standard-8 bash deploy/deploy.sh`.
- rollback machine type: stop the VM, set `--machine-type e2-standard-4`, start.
