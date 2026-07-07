# Progress Ledger

Compressed "where are we now" dashboard. Read before planning. Updated with the
docs commit after each functional slice.

## Current branch / mission
- Main branch: `main` (protected; releasable; live at baddyai.com)
- Active branch: `main` (all Cycle 13-15 branches ff-merged)
- Current branch base SHA: `29af265` (Cycle 13 stack base)
- **Deployed 2026-06-24:** the full editor/camera/queue sweep is LIVE on baddyai.com,
  plus a follow-up Studio polish deploy (`227e05a`, v=19 assets): real shuttle
  trail (was a stray green bar) + temporal smoothing (EMA, snap-on-cut) for the
  camera and player overlays. Health ok; new code verified live.

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
| 2026-06-26 | Pose contract + model/camera upgrade | Merged (Cycle 12) | TASK-017/018/019/020 — `pose_track` keypoints end-to-end, configurable YOLO pose (yolo26, verified via build-time weight bake; yolo11n fallback), real Studio skeletons + toggle gating, zoom punch off by default, POV shuttle-follow when quality high. Takeover hardening: deterministic routing tests, GPU-first routing test |
| 2026-06-26 | Shuttle filter + keep-in-frame + compose drag | Merged (Cycle 12) | User feedback batch — Hampel-style false-detection filter (camera + overlay), `_contain_targets` keep-in-frame guarantee, wider zoom smoothing, Compose drag via window listeners + library ghost-drag-to-drop, comet trail effect, UI polish. 5 new regression tests |
| 2026-07-07 | Portrait overlay projection + review bug batch | On branch (Cycle 13) | TASK-021 — renderer exports `camera_path`/`render_window`; Studio inverts the baked crop (portrait pixel-exact ≤0.41% vs ground-truth fixture), xfade-aware reel time, landscape = source time; timeline drag-to-scrub + stacking fix; pixel-space skeletons (blob bug); worker pose/box pairing fix; `_stable_ids` (near player = P1, fragment merge). 42 tests green |
| 2026-07-07 | Interpolation + court.py + heatmaps | On branch (Cycle 13) | TASK-022 — shuttle/box/pose lerp between ≤10Hz samples; `court.py` corners/lines/net + homography to court-plane meters (`result["court"]`), Court overlay layer, per-player post-game movement heatmaps, ground-truth Studio fixture (`scripts/make_studio_fixture.py`) |
| 2026-07-07 | Schools platform P0 | On branch (Cycle 14) | TASK-026 — auth pages (create school / join with ST-/CO- codes / sign in), scrypt+cookie sessions, school tenancy on jobs, coach panel (roster, join codes, assign sessions w/ P1/P2 pin), student My Progress (stat cards+sparklines, highlights, rally chips, AI-coach box, court-space movement via homography). 46 tests; browser-verified E2E |
| 2026-07-07 | Cycles 13/14 deployed to baddyai.com | **LIVE** (Cycle 15) | main `7137bcb` deployed via deploy.sh; health ok; v=27+ assets; auth pages live |
| 2026-07-07 | Worker ByteTrack identity | Done + rolled out (Cycle 15) | TASK-024 — track_id end-to-end (worker→gpu.py→samplers, ≥90%-coverage gate, shared relabel); image `bytetrack-20260707` on template `ic265brof1`, endpoint ready 2/unhealthy 0. Real-GPU-job id check pending next upload |
| 2026-07-07 | Gemini court-corner fallback | Done (Cycle 15) | TASK-023 — structured-output corners on weak CV (<0.5), schema+agreement validation, `court.source` provenance; 5 mocked tests. uservid3: honest not_found (court not fully visible) |
| 2026-07-07 | 3D rally replay | Done (Cycle 15) | TASK-025 — rally3d.py (camera pose from homography, drag-ballistic multi-start LM, 12Hz `rally_3d`), court.py handedness normalization, Studio "3D replay" layer (canvas 3D, orbit+presets, sim-clock-gated). 6 ground-truth tests; browser-verified on fixture3d |

## Active priorities
1. ~~Rebuild + redeploy the RunPod worker~~ **DONE 2026-07-01**: image
   `pose-20260626a` (Cloud Build 3m41s, SUCCESS — yolo26m+yolo11n weights baked,
   bake step doubles as build-time model verification); template `ic265brof1`
   patched from `tracknet-src-20260621b`; endpoint `radst7uhhhl6q0` health:
   workers ready 2 / unhealthy 0. VM deployed (v=25), health ok.
2. ~~Merge + deploy TASK-021/022~~ **DONE (Cycle 15)** — live on baddyai.com.
   Note: portrait overlays only align on reels rendered after the deploy;
   old reels show the rebuild hint by design.
3. ~~Rebuild RunPod worker~~ **DONE (Cycle 15)** — `bytetrack-20260707` carries
   BOTH the pairing fix and ByteTrack ids; endpoint healthy.
4. **Verify on a real upload**: next GPU job should show
   `worker_version=bytetrack-20260707`, two stable player ids, `court.source`,
   and (full-court footage) `rally_3d` shots — record here.
5. **Schools P1**: assign-to-student from a Studio player track, cohorts,
   student dashboard polish (`docs/roadmap/SCHOOL_PLATFORM_PRD.md` §5).
6. Deploy cadence: bump web asset `?v=` on EVERY same-session JS/CSS edit
   (browser heuristic-caches versioned URLs).
- Follow-ups (not blocking): unify render-time player identity (near/far) with the
  editor's per-player ids; persist full `baddy.editor.v1` (overlay styles) into the
  MP4; click-to-set fixed point on the preview; definitive e2e GPU pose-proof job
  record (pose-20260626a live per 2026-07-01 note).

## Open risks
| Risk | Severity | Source | Mitigation / next task |
|---|---|---|---|
| Mumbai move needs GoDaddy DNS cutover | Low | Cycle 7 GCP audit | TASK-006 completed in place; Mumbai remains optional future migration |
| Original upload soft (rendered from 480p proxy; ~/Downloads TCC-blocked) | Med | session 2026-06-19 | re-run on sharp source when file access restored |
| YOLO26 pose defaults depend on deployed `ultralytics` support and weight availability | Closed | TASK-018 | yolo26s verified loading locally (ultralytics 8.4.70); worker Dockerfile bakes yolo26m+yolo11n at build (build fails fast if unavailable) |
| Pose keypoint tracks increase full job payload size | Low | TASK-017 | bounded `pose_track` sampler; gallery light payload still omits per-rally tracks |

## Next checkpoint
- Goal: worker image rebuilt (`pose` output + baked weights) + VM deployed; then a
  representative RunPod pose/shuttle job opened in Studio showing skeletons.
- Required tests: `./scripts/check.sh` (32 passing), baddyai.com health, workers
  ready on the new image.
