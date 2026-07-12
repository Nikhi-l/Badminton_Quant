# Progress Ledger

Compressed "where are we now" dashboard. Read before planning. Updated with the
docs commit after each functional slice.

## Current branch / mission
- Main branch: `main` (protected; releasable; live at baddyai.com)
- Active branches (Cycle 18 stack, base `0cae987`):
  `feat/TASK-031-player-pose-tracking-v2` → `feat/TASK-032-court3d-flow` →
  `feat/TASK-033-timeline-redesign` (merge in that order; 033 also carries a
  concurrent session's Studio commits `4bc82f7`/`f5c65fd`/`0a87869`)
  → `fix/TASK-034-phase0-tracking-audit` (Cycle 19, base `bfb2152`)
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
| 2026-07-07 | Manual court + racquet chain | Done + rolled out (Cycle 16) | TASK-027 — upload corner picker + Studio draw mode + court recompute endpoint (uservid3: 5 rallies gained 3D from drawn corners); racquet: custom→COCO-tennis-racket (wrist-gated)→candidates, racquet_track + overlay. Image `racquet-20260707` (yolo11s baked) on template `ic265brof1`, endpoint ready 2/unhealthy 0 |
| 2026-07-08 | Production triage: GPU crash + render crash + doubles + retry | Done (Cycle 17) | TASK-029 — Hough unpack fix (GPU jobs were silently falling back to CPU), badge/_blend render crash fix, 2→4 player caps for doubles, retry endpoint + UI. Worker `doubles-20260708` |
| 2026-07-08 | Doubles far-player detection (resolution) | **Done + verified** (Cycle 17b) | TASK-030 — root cause: 480p analysis proxy makes far doubles players ~20px (undetectable); cap 2→4 (TASK-029) necessary but not sufficient. Fix: separate higher-res `vision_proxy.mp4` (1080p, capped to source) for the GPU pose+shuttle pass only (Gemini/rally/motion stay 480p); `gpu.analyze` uploads whichever proxy passed, 480p fallback. Template env `YOLO_IMGSZ=1920`, `YOLO_CONF=0.12` (no rebuild). **Verified on IMG_0477: player_quality 0.44→0.63, max_boxes/frame 1→2-3 across all 3 rallies (was 1).** Far cluster of 3 overlapping players partial — 2 stable ids (near+far), not 4; closer camera / TASK-028 fine-tune is the ceiling. |
| 2026-07-10 | Player + pose tracking v2 | On branch (Cycle 18) | TASK-031 — phantom conf-0.12 fallback boxes removed (they steered the camera to empty court); camera rebuilt on continuous tracks (worker track_id grouping, 6Hz interpolation, ghost expiry, near/far hysteresis); BoT-SORT+ReID tuned for 6Hz (`botsort_baddy.yaml`); court-polygon gating pre-cap; yolo26l-pose default; worker-id cliff 0.9→0.6 + spatial fragment-merge guard; One-Euro pose_track smoothing; local top-4; racquet caps 4. **Worker rebuild pending**: `_TAG=trackingv2-20260710` + template patch + worker bounce |
| 2026-07-10 | 3D mapping flow | On branch (Cycle 18) | TASK-032 — weak-CV court now `low_confidence` (was silently "ok" → garbage 3D); slim non-ok `rally_3d` statuses to the UI; POST /court off the event loop + per-rally outcomes; replay3d bugs fixed (mirrored_frame, resize memo, dead shot-ribbon break, 30Hz visual lerp); Studio: 3D empty state explains why + Draw-corners CTA, degenerate-quad warning at upload |
| 2026-07-10 | Timeline redesign | On branch (Cycle 18) | TASK-033 — pose+soundtrack lanes were clipped invisible (202px row vs 240px content) → 170px lane budget in a 236px row; zoom dead-range killed, pixel playhead + anchor-preserving 1–6x zoom + pinch; adaptive ruler; per-seg selection; hover ghost; frame-step keys; filmstrip cache. Browser-verified px-exact |
| 2026-07-11 | Phase-0 audit fixes (deterministic tracking/3D bugs) | On branch (Cycle 19) | TASK-034 — worker tracker persist-capture bug (ids reborn EVERY frame; verified in ultralytics 8.4.70 sources) → persist=True + explicit per-rally reset, thresholds aligned to deployed YOLO_CONF=0.12, ultralytics pinned; honest shuttle quality (coverage×gap×teleports, components exported); gap-preserving 12.5Hz public shuttle track (long-rally trail restored); Studio: no id-union (2 players ≠ 4 boxes), 0.3s hold + midpoint handoff, box EMA removed; render+3D use the same filtered track (filter endpoint fix: contact points survive); 3D physical gates (floor/bounds/net/contact/speed/residual/continuity, `rejected` tally, `implausible` status, "2.5D" labeling) — uservid3: 20→13 shots, ZERO impossible acceptances; Phase-0 bench scaffold (metrics+gates+runner). 124 tests green. **DEPLOYED 2026-07-11: VM (assets v=36, health ok) + worker `phase0-20260711` rolled (template patched, workers bounced 0→2; GPU smoke: worker_version confirmed, ids 1/2 stable 48/48 frames, tracknet coverage/teleports live)** |
| 2026-07-11 | Measured shuttle confidence + radar-comparable speeds | Done (Cycle 20) | TASK-035 — smash-speed-paper intake: `track.refine_shuttle_track` at canonicalization (both vision backends) — fwd+bwd constant-velocity innovation scoring (miss ÷ local median step), static-run rejection (lights/net posts/floor-rest), hard >~500 km/h gate, `provenance:"observed"`; flat 0.82 replaced by measured 0.05–0.95 (uservid3: 467 pts → 24 static-dropped, 27 distrusted, flight medians 0.86–0.92); `rally_3d` shots add `speed_at_net_kmh` (radar-comparable; paper: ~66 km/h MAE between impact and radar) next to impact `speed_kmh`, shown in the 3D panel (v=37); bench speed protocol (MAPE gate on AT-NET vs radar) + camera-angle diversity. 131 tests green. App-side only (no worker rebuild) |
| 2026-07-12 | Rally-break audit + analysis.json + architecture board | Done (Cycle 21) | TASK-039 — audit: boundaries are Gemini-only/whole-second, no in-rally play/no-play split, audio discarded (`docs/reviews/2026-07-12-rally-break-inplay-audit.md`; in-play mask v1 design queued as TASK-040); `analysis.json` per job (`GET /api/jobs/{id}/analysis`, cached): play/no-play timeline, hits w/ impact+at-net km/h, shuttle-flight segments, audio impact peaks, per-player court-space movement series; `audio.py` RMS+peaks stored per new job; verbatim `gemini_rallies_raw.json`/`vision_raw.json` persisted; `/architecture` live board + demo runner (stage chips, per-model panels, movement canvas). uservid3: 336s → play 56s / no-play 280s, 33 peaks. 140 tests green |
| 2026-07-12 | Owner review intake: shuttle in-play index v0 + wrist signals + future vision | Done (Cycle 22) | TASK-040 v0 — analysis schema v2: flight segments carry median/max speed + `in_play` verdict (airborne AND ≥0.15 norm/s ≈2 m/s AND ≥0.4s — carried-shuttle false positives speed-gated per owner spec); per-rally `in_play` spans; `wrists` series (COCO 9/10) saved for hit detection; endpoint rebuilds stale-schema caches; audit §4 rewritten (v1 corroborated mask, v2 signals→Gemini verification — Gemini never grades its own cold guess), §4b canonical camera (behind players ~10ft, full court); bench: canonical-rig clips + `play_spans` labels; `docs/roadmap/FUTURE_VISION.md` (school streaming: multi-view live cuts, shirt tracking, scoreboard, student app). uservid3: slow/static segs gated out, fast exchanges in-play. 142 tests |
| 2026-07-12 | Upload-review batch: annotated preview, Gemini evaluator, court gate, trim button | Done (Cycle 23) | TASK-041 — diagnosis: pose data healthy (skeletons were live-overlay-only), MAX_REEL_SEC=59 capped reel at 3 rallies, shuttle_q 0.0 = teleport penalty flagging background court. Shipped: `annotated.mp4` baked shuttle+pose preview + Studio button; Gemini frame evaluator (main-court player count + keep ids, prunes tracks pre-camera, fail-open); `court_shuttle_gate` (background-court flight segments dropped by geometry); MAX_REEL_SEC 90; one-button whole-match trim (`/api/jobs/{id}/trim` → trimmed.mp4); requestVideoFrameCallback frame-exact overlays (v=38). 147 tests |

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
4. **Verify on a real upload**: next GPU job should show `racquet_source` +
   measured racquet boxes (image `racquet-20260707`), plus
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
