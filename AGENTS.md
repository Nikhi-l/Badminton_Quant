# AGENTS.md — Baddy operating rules

Operating rules for AI agents (Claude, Codex) working in this repo. Adapted from
the v2 AI-Agent Repo Harness (GlassFlow patterns), **pragmatic subset**: we keep
branches, a canonical PRD, a cycle log, a progress ledger, task files, and real
tests. We skip worktrees, patch files, mission branches, and CI gating until the
project actually needs them.

## Source of truth (precedence when docs conflict)
1. `AGENTS.md` / `CLAUDE.md` safety + operating rules (this file)
2. Current task file under `.agent/tasks/active/`
3. `docs/roadmap/PRIMARY_PRD.md` (canonical product + architecture + remediation queue)
4. `docs/progress-ledger.md` then `docs/dev-cycle-log.md` (current state)
5. Feature-local README
6. Legacy `README.md` / old notes — historical context only

Legacy docs are research inputs unless the PRD re-adopts them.

## Branching (see docs/BRANCHING.md)
- **No agent works directly on `main`.** `main` is protected and releasable.
- One task = one short-lived branch: `feat/TASK-NNN-slug`, `fix/…`, `chore/…`, `spike/…`.
- Branch off `main`; open a PR back to `main`. No force-push to `main`.

## Before coding
1. Read the active task file under `.agent/tasks/active/`.
2. Read the relevant `docs/roadmap/PRIMARY_PRD.md` section.
3. Read `docs/progress-ledger.md` and recent `docs/dev-cycle-log.md` cycles.

## Development cycle (commit rhythm)
For each meaningful slice on a branch:
1. `feat:`/`fix:` — the functional change
2. `test:` — unit/integration/regression covering it (if substantial)
3. `docs:` — append a `docs/dev-cycle-log.md` cycle entry + update `docs/progress-ledger.md`

Every cycle entry must cite the PRD section it advances and list the **exact**
verification commands run (not "tested").

## Testing
- Tests live in `tests/` (`unit/`, `integration/`, `regression/`, `fixtures/`).
- Every bug fix gets a regression test that fails before and passes after.
- External services (Gemini, RunPod) are mocked/stubbed in tests — no network.
- Run `./scripts/check.sh` before marking a task done; document any skip.

## Migrations
- The job store is SQLite (`app/db.py`). Prefer **additive** schema changes:
  add columns/tables with `ALTER TABLE … ADD COLUMN` guarded by a `PRAGMA
  table_info` check (see `db.init()`); never drop/rewrite columns in place.
- Record the migration + how it was verified in the cycle log.

## Secrets
- `.env` (GEMINI_API_KEY, RUNPOD_API_KEY, GPU_ARTIFACT_TOKEN) is gitignored and
  must NEVER be committed. Verify `git status` is clean of it before every commit.

## Definition of done
A task is not ready to merge unless you can state: task, branch, base SHA,
PRD section, tests added, cycle-log entry, progress-ledger update, and the
rollback command.
