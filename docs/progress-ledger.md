# Progress Ledger

Compressed "where are we now" dashboard. Read before planning. Updated with the
docs commit after each functional slice.

## Current branch / mission
- Main branch: `main` (protected; releasable; live at baddyai.com)
- Active branch: `feat/TASK-007-reel-editor-ui`
- UI branch: `feat/TASK-007-reel-editor-ui`
- Base SHA: `883786f` for TASK-007 UI work

## Ledger
| Date | Area | Status | Notes |
|---|---|---|---|
| 2026-06-20 | Harness adoption | Done | Pragmatic subset scaffolded (Cycle 1) |
| 2026-06-20 | Camera: follow shuttle | Done | TASK-001, Cycle 1 — follows on 3/5 (soft proxy); regression-tested |
| 2026-06-21 | RunPod worker rebuild | Worker healthy | TASK-002, Cycle 3 — `tracknet-src-20260621` deployed (template `lwjbpdx6qf`, workersMax 0→2); workers boot `ready:2 unhealthy:0`; handler runs (boot-test failed only on dummy URL). Full GPU shuttle e2e pending via baddyai.com + server key refresh |
| 2026-06-20 | CPU/GPU pipelines + gen-time | Todo | TASK-003 (P1) |
| 2026-06-20 | Job model (timing, failed) | Todo | TASK-004 (P1) |
| 2026-06-20 | Queue UI + /api/jobs | Todo | TASK-005 (P1) |
| 2026-06-20 | Instance sizing | Decided | TASK-006: c2d-standard-8 Mumbai 1yr CUD (PRD §P1-INSTANCE) |
| 2026-06-21 | Reel editor UI | Reasoned UI complete | TASK-007, Cycle 4 — component rationale added; dead controls removed; Soundtrack is read-only until backend audio render props exist; overlay render contract still future |

## Active priorities
1. TASK-001 — camera actively follows + centers the shuttle (regression-tested).
2. TASK-002 — rebuild RunPod worker from source; verify baddyai.com.
3. TASK-003/004/005 — dual pipelines + job timing + queue UI.
4. Next editor backend slice — persist `baddy.editor.v1` to jobs and render shuttle/pose/audio styles into MP4 output; keep trim/text/music edits hidden until contracts exist.

## Open risks
| Risk | Severity | Source | Mitigation / next task |
|---|---|---|---|
| RunPod worker won't boot (re-wrapped image inherited defect) | Resolved? | session 2026-06-19 | TASK-002 Cycle 2: clean from-source `tracknet-src-20260621` built (single-arch docker v2) — confirm health after deploy |
| RunPod API key in .env returns 401 (expired) | Med | 2026-06-21 | blocks API deploy + GPU jobs; user to refresh key, then redeploy + verify |
| Original upload soft (rendered from 480p proxy; ~/Downloads TCC-blocked) | Med | session 2026-06-19 | re-run on sharp source when file access restored |
| `if not pov` gates `from_vision` off for handheld clips | Med | track.py:137 | revisit in pipeline cycle |

## Next checkpoint
- Goal: PR-review the reasoned TASK-007 editor UI and decide the next backend
  render-contract slice.
- Required tests: `node --check web/app.js`, `./scripts/check.sh`, and rendered
  desktop/mobile Studio QA.
- Expected docs update: this ledger + dev-cycle-log Cycle 4.
