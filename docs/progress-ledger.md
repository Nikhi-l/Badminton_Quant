# Progress Ledger

Compressed "where are we now" dashboard. Read before planning. Updated with the
docs commit after each functional slice.

## Current branch / mission
- Main branch: `main` (protected; releasable; live at baddyai.com)
- Active branch: none — TASK-003/004/006 merged via PR #2
- UI branch: `feat/TASK-007-reel-editor-ui`
- Current main SHA: `dc9920d`

## Ledger
| Date | Area | Status | Notes |
|---|---|---|---|
| 2026-06-20 | Harness adoption | Done | Pragmatic subset scaffolded (Cycle 1) |
| 2026-06-20 | Camera: follow shuttle | Done | TASK-001, Cycle 1 — follows on 3/5 (soft proxy); regression-tested |
| 2026-06-21 | RunPod worker rebuild | Done | TASK-002, Cycle 5 — GPU TrackNetV3 verified e2e via baddyai.com (`tracknet.status=ok`, 55–122 real pts/rally, q0.82, backend=runpod). Fixed missing matplotlib/pycocotools (`tracknet-src-20260621b`, template `ic265brof1`); workers `ready:2 unhealthy:0`, scale to 0 idle |
| 2026-06-21 | CPU/GPU pipelines + gen-time | Deployed | TASK-003, Cycle 6 — `pipeline=cpu|gpu` recorded from job options; API exposes separate expected gen-time budgets |
| 2026-06-21 | Job model (timing, failed) | Deployed | TASK-004, Cycle 6 — `started_at`/`finished_at` migrated live; legacy `error` rows now `failed`; latest GPU job reports `gen_seconds=424.6` |
| 2026-06-20 | Queue UI + /api/jobs | Todo | TASK-005 (P1) |
| 2026-06-21 | Instance sizing | Done | TASK-006, Cycle 7 — live VM resized in place to `c2d-standard-8` in `us-central1-a`; static production IP `136.113.208.173` preserved as `baddy-agent-ip`; health + DB/API verified |
| 2026-06-21 | Reel editor UI | Reasoned UI complete | TASK-007, Cycle 4 — component rationale added; dead controls removed; Soundtrack is read-only until backend audio render props exist; overlay render contract still future |
| 2026-06-21 | Editor timeline (detailed) | Deployed | TASK-008, Cycle 8 — Descript-style timeline: filmstrip clip lane, Captions lane w/ gap markers, waveform, minor ticks, playhead time bubble. Live on baddyai.com |
| 2026-06-21 | Manual video framing | Deployed | TASK-009, Cycle 8 — Framing layer: Original/Crop toggle, Zoom+Pan, drag-to-pan, "Reset to original". Preview/persisted client state; export-bake is a backend follow-up. Live |
| 2026-06-21 | Upload double-prompt bug | Todo (bug) | TASK-010 — after a reel is generated, a new upload prompts the file picker twice; with Shuttle tracking on the 2nd-attempt upload doesn't start. Fresh/first job is fine. Suspect web/app.js upload bindings (~63–71) + fileInput.value reset on return-to-upload paths. Not yet root-caused |
| 2026-06-21 | Overlay correctness (bug) | Todo | TASK-011 — hide shuttle/pose marker when untracked (the "weird circle"); render pose from real keypoints. Intake `docs/reviews/2026-06-21-studio-camera-feedback.md` |
| 2026-06-21 | Interactive timeline lanes | Todo | TASK-012 — toggle shuttle/pose from timeline; Source mode shuttle track across full video |
| 2026-06-21 | Landscape view + Source framing | Todo | TASK-013 — landscape↔portrait toggle; manual reframe in Source rallies |
| 2026-06-21 | Configurable camera + keyframes | Todo (P0, major) | TASK-014 — target shuttle\|player\|point + keyframes; bake camera plan into export (depends on TASK-015 + render contract) |
| 2026-06-21 | Player/person tracking | Todo | TASK-015 — track players; expose as camera target + lane/overlay (feeds TASK-014) |

## Active priorities
1. TASK-011 — overlay correctness (the "weird circle" + real pose). Cheapest visible win.
2. TASK-014 — configurable virtual camera (targets + keyframes); needs TASK-015 (player
   tracks) + a backend camera render contract. The headline Studio feature.
3. TASK-012 / TASK-013 — interactive timeline lanes; landscape view + Source-mode reframe.
4. TASK-010 — fix the upload double-prompt bug.
5. TASK-005 — queue UI + `GET /api/jobs` list, using TASK-003/004 timing fields.
- Backend: persist `baddy.editor.v1` to jobs and render the camera plan + shuttle/pose
  styles into the MP4 (the render contract TASK-014 depends on).

## Open risks
| Risk | Severity | Source | Mitigation / next task |
|---|---|---|---|
| Mumbai move needs GoDaddy DNS cutover | Low | Cycle 7 GCP audit | TASK-006 completed in place; Mumbai remains optional future migration |
| Original upload soft (rendered from 480p proxy; ~/Downloads TCC-blocked) | Med | session 2026-06-19 | re-run on sharp source when file access restored |
| `if not pov` gates `from_vision` off for handheld clips | Med | track.py:137 | revisit in pipeline cycle |

## Next checkpoint
- Goal: finish TASK-005 queue list/UI on top of the now-deployed job timing API.
- Required tests: unit/API coverage for `GET /api/jobs`, frontend smoke, `./scripts/check.sh`.
- Expected docs update: this ledger + dev-cycle-log Cycle 7.
