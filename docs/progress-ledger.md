# Progress Ledger

Compressed "where are we now" dashboard. Read before planning. Updated with the
docs commit after each functional slice.

## Current branch / mission
- Main branch: `main` (protected; releasable; live at baddyai.com)
- Active branch: none — all queued tasks (TASK-005, 010–015) merged
- Current main SHA: `cec0db2`
- **Deployed 2026-06-24:** the full editor/camera/queue sweep is LIVE on baddyai.com
  (`bash deploy/deploy.sh`; baddy.service restarted; health ok; `GET /api/jobs` +
  v=18 assets + camera/queue/player code verified live).

## Ledger
| Date | Area | Status | Notes |
|---|---|---|---|
| 2026-06-20 | Harness adoption | Done | Pragmatic subset scaffolded (Cycle 1) |
| 2026-06-20 | Camera: follow shuttle | Done | TASK-001, Cycle 1 — follows on 3/5 (soft proxy); regression-tested |
| 2026-06-21 | RunPod worker rebuild | Done | TASK-002, Cycle 5 — GPU TrackNetV3 verified e2e via baddyai.com (`tracknet.status=ok`, 55–122 real pts/rally, q0.82, backend=runpod). Fixed missing matplotlib/pycocotools (`tracknet-src-20260621b`, template `ic265brof1`); workers `ready:2 unhealthy:0`, scale to 0 idle |
| 2026-06-21 | CPU/GPU pipelines + gen-time | Deployed | TASK-003, Cycle 6 — `pipeline=cpu|gpu` recorded from job options; API exposes separate expected gen-time budgets |
| 2026-06-21 | Job model (timing, failed) | Deployed | TASK-004, Cycle 6 — `started_at`/`finished_at` migrated live; legacy `error` rows now `failed`; latest GPU job reports `gen_seconds=424.6` |
| 2026-06-23 | Queue UI + /api/jobs | Merged (deploy pending) | TASK-005, Cycle 11 — `GET /api/jobs` + "Your queue" UI: status chips, CPU/GPU, submit/gen time, failed errors, Studio button; live-polls while active. Unit-tested. TASK-007 reel-editor-ui filed to done (was Cycle 4) |
| 2026-06-21 | Instance sizing | Done | TASK-006, Cycle 7 — live VM resized in place to `c2d-standard-8` in `us-central1-a`; static production IP `136.113.208.173` preserved as `baddy-agent-ip`; health + DB/API verified |
| 2026-06-21 | Reel editor UI | Reasoned UI complete | TASK-007, Cycle 4 — component rationale added; dead controls removed; Soundtrack is read-only until backend audio render props exist; overlay render contract still future |
| 2026-06-21 | Editor timeline (detailed) | Deployed | TASK-008, Cycle 8 — Descript-style timeline: filmstrip clip lane, Captions lane w/ gap markers, waveform, minor ticks, playhead time bubble. Live on baddyai.com |
| 2026-06-21 | Manual video framing | Deployed | TASK-009, Cycle 8 — Framing layer: Original/Crop toggle, Zoom+Pan, drag-to-pan, "Reset to original". Preview/persisted client state; export-bake is a backend follow-up. Live |
| 2026-06-23 | Upload double-prompt bug | Merged (deploy pending) | TASK-010 — root cause: `#browse` inside `#drop` fired `fileInput.click()` twice (button + bubbled drop handler) → picker re-opened after the first pick. Fix: `openFilePicker()` busy-guard + `stopPropagation`. Shuttle symptom rode on the same double-trigger. Verified in preview (1 open per intent) |
| 2026-06-21 | Overlay correctness (bug) | Merged (deploy pending) | TASK-011, Cycle 9 — phantom shuttle marker hidden when untracked; non-data pose skeleton removed (real pose → TASK-015). Verified in preview |
| 2026-06-21 | Interactive timeline lanes | Merged (deploy pending) | TASK-012, Cycle 9 — Shuttle/Pose lanes toggle the overlay; Source mode shuttle track across whole video (trajectory dots). Verified in preview |
| 2026-06-21 | Landscape view + Source framing | Merged (deploy pending) | TASK-013, Cycle 9 — Portrait/Landscape toggle (source native aspect); framing crop/zoom/pan in Source mode; cache-bust v=18. Verified in preview |
| 2026-06-23 | Configurable camera + keyframes | Merged (deploy pending) | TASK-014, Cycle 10 — target shuttle\|player\|point + keyframes; Camera layer/inspector + timeline lane; preview follows target w/ blend; backend from_camera_plan + camera_segment_for_rally + remix(camera=) bake; _validate_camera. 6 unit tests. e2e MP4 bake wired but not yet visually confirmed on a real render |
| 2026-06-23 | Player/person tracking | Merged (deploy pending) | TASK-015, Cycle 10 — players_track (stable ids) exposed; player boxes overlay (hide when untracked) + Pose-lane presence dots; layer "Players & pose"; feeds TASK-014 player target. Unit-tested |

## Active priorities
**All queued tasks (TASK-005, 010–015) are done, merged, and DEPLOYED (2026-06-24).**
Remaining:
1. **Confirm the TASK-014 camera bake on a real render** — now live: open Studio →
   Camera → keyframes → Rebuild cuts on a done job and watch the exported MP4 (the
   only un-e2e-verified piece; logic is unit-tested). Re-renders that job's reel.
- Follow-ups (not blocking): unify render-time player identity (near/far) with the
  editor's per-player ids; persist full `baddy.editor.v1` (overlay styles) into the
  MP4; click-to-set fixed point on the preview.

## Open risks
| Risk | Severity | Source | Mitigation / next task |
|---|---|---|---|
| Mumbai move needs GoDaddy DNS cutover | Low | Cycle 7 GCP audit | TASK-006 completed in place; Mumbai remains optional future migration |
| Original upload soft (rendered from 480p proxy; ~/Downloads TCC-blocked) | Med | session 2026-06-19 | re-run on sharp source when file access restored |
| `if not pov` gates `from_vision` off for handheld clips | Med | track.py:137 | revisit in pipeline cycle |

## Next checkpoint
- Goal: deploy the merged sweep (TASK-005, 010–015) to baddyai.com and confirm the
  TASK-014 camera bake on a real remix render.
- Required tests: `./scripts/check.sh` (17 passing), baddyai.com health, a remix-with-
  camera render eyeballed.
- Expected docs update: this ledger + a deploy note in dev-cycle-log.
