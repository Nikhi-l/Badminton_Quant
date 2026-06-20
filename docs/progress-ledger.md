# Progress Ledger

Compressed "where are we now" dashboard. Read before planning. Updated with the
docs commit after each functional slice.

## Current branch / mission
- Main branch: `main` (protected; releasable; live at baddyai.com)
- Active branch: `feat/TASK-001-shuttle-follow-camera`
- UI branch: `feat/TASK-007-reel-editor-ui`
- Base SHA: `5f1c165`

## Ledger
| Date | Area | Status | Notes |
|---|---|---|---|
| 2026-06-20 | Harness adoption | Done | Pragmatic subset scaffolded (Cycle 1) |
| 2026-06-20 | Camera: follow shuttle | Done | TASK-001, Cycle 1 — follows on 3/5 (soft proxy); regression-tested |
| 2026-06-20 | RunPod worker rebuild | Todo | TASK-002 (P0) |
| 2026-06-20 | CPU/GPU pipelines + gen-time | Todo | TASK-003 (P1) |
| 2026-06-20 | Job model (timing, failed) | Todo | TASK-004 (P1) |
| 2026-06-20 | Queue UI + /api/jobs | Todo | TASK-005 (P1) |
| 2026-06-20 | Instance sizing | Decided | TASK-006: c2d-standard-8 Mumbai 1yr CUD (PRD §P1-INSTANCE) |
| 2026-06-20 | Reel editor UI | Done | TASK-007: Studio editor shell, `baddy.editor.v1`, shuttle/pose/music lanes; overlay render contract still future |

## Active priorities
1. TASK-001 — camera actively follows + centers the shuttle (regression-tested).
2. TASK-002 — rebuild RunPod worker from source; verify baddyai.com.
3. TASK-003/004/005 — dual pipelines + job timing + queue UI.
4. Next editor backend slice — persist `baddy.editor.v1` to jobs and render shuttle/pose/music styles into MP4 output.

## Open risks
| Risk | Severity | Source | Mitigation / next task |
|---|---|---|---|
| RunPod worker won't boot (re-wrapped image inherits defect) | High | session 2026-06-19 | TASK-002: clean Cloud Build from Dockerfile |
| Original upload soft (rendered from 480p proxy; ~/Downloads TCC-blocked) | Med | session 2026-06-19 | re-run on sharp source when file access restored |
| `if not pov` gates `from_vision` off for handheld clips | Med | track.py:137 | revisit in pipeline cycle |

## Next checkpoint
- Goal: camera keeps the shuttle centered across a rally; regression test green.
- Required tests: `tests/regression/test_camera_follows_shuttle.py`.
- Expected docs update: this ledger + dev-cycle-log Cycle 1.
