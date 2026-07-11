# Dev-cycle log

One entry per meaningful product cycle. Each cites the PRD section it advances and
lists exact verification commands. Newest first.

<!-- New cycles appended below. -->

## Cycle 19: Phase-0 audit fixes — deterministic tracking/3D bugs (TASK-034)
**Date:** 2026-07-11
**Goal:** Implement Phase 0 of the 2026-07-11 codebase audit: the deterministic
pipeline bugs behind jerky trails, unstable player counts, lagging boxes, and
impossible 3D — before any model swaps.
**PRD:** §16 remediation (TASK-034 + Phase-1 queue rows added this cycle).
**Branch:** `fix/TASK-034-phase0-tracking-audit` (base `bfb2152`, atop TASK-033).
**Task file:** `.agent/tasks/active/TASK-034-phase0-tracking-audit.md`

**Fixes (each verified against the installed deps / real artifact):**
- **Worker tracker lifecycle (P0):** ultralytics registers tracking callbacks on
  the FIRST `model.track()` call, permanently capturing that call's `persist`
  (verified in 8.4.70 `engine/model.py` + `trackers/track.py`). The old
  `persist=not reset_tracker` baked in `persist=False` → the tracker was
  rebuilt every predict, minting fresh ids per frame at "100% id coverage".
  Now `persist=True` always + explicit `tracker.reset()` per rally (also
  resets the global id counter). `ultralytics` pinned `==8.4.70`.
  `new_track_thresh` 0.3→0.18 / `track_high_thresh` 0.25→0.2 to match the
  deployed `YOLO_CONF=0.12` — post-reset, far players must be able to BIRTH
  tracks. Worker default version → `phase0-20260711`.
- **Honest shuttle quality (P0):** worker score was mean(constant 0.82) ×
  coverage — a teleporting track read "82%" like a clean one. Now coverage ×
  longest-gap (proportional, ≤0.5 s free) × teleport penalty; components
  (`coverage`/`longest_gap_sec`/`teleports`) exported on `tracknet`.
- **Public shuttle-track contract (P0):** uniform 180-point decimation spread
  long rallies past Studio's 0.35 s dropout cutoff — trail always empty,
  marker flickering (audit repro: 70 s smooth track → 0.4 s spacing). Now
  gap-preserving per-segment resampling at 12.5 Hz (worst in-segment spacing
  0.33 s), real dropouts survive as gaps; player/pose public caps 120→180
  (= worker `MAX_FRAMES_PER_RALLY`, no second decimation).
- **Studio interpolation (P0):** `interpPlayerBoxes`/`interpPoseFrame` unioned
  unmatched ids from both bracket frames (relabel {1,2}→{3,4} drew FOUR
  boxes) and held vanished ids across 1.2 s. Now: one-sided ids render only
  ≤0.3 s from their observing frame AND on its side of the bracket midpoint;
  window/maxGap 1.0/1.2→0.6/0.9; the extra 140 ms wall-clock box EMA removed
  (lag + fabricated glide); pose render gate 0.12→0.15 (= One-Euro gate).
- **One canonical shuttle track (P0):** baked-MP4 marker (render.py) and 3D
  (rally3d.py) now consume the same `filter_shuttle_points` output as
  camera/Studio. Exposed filter weakness fixed: endpoint windows are
  one-sided, so the launch step after a hit (the contact point!) read as an
  outlier vs the forward median — endpoints now judged against linear
  extrapolation of the two nearest kept neighbours; edge teleports still die.
- **3D physical gates (P0):** floor (−0.05 m), trajectory bounds (court
  +2/+3 m), contact height 0.02–3.6 m, net crossing ≥1.0 m, launch ≤55 m/s,
  residual ≤35 px (was 60), adjacent-shot continuity (≤0.4 s ⇒ hand-off ≤2 m,
  higher-residual member dropped). Multi-start picks best GATE-PASSING
  candidate; `rejected{reason:count}` on the payload; new `implausible`
  status + Studio copy; layer relabelled "3D replay (2.5D)" (billboards, not
  measured pose).
- **Phase-0 bench (scaffold):** `scripts/bench/metrics.py` (audit release
  gates as tested functions) + `run_bench.py` (manifest → gate table, exit 1
  on failure) + `docs/benchmarks/PHASE0_BENCH.md` (clip-set recipe + label
  formats). Labelled clips themselves = owner action.

**Tests/verification performed:**
- `./scripts/check.sh` → compile OK, **124 passed** (was 102; new coverage:
  tracker lifecycle ×4 incl. pinned-dependency semantics, track quality ×4,
  shuttle-track contract ×2, filter endpoints ×2, 3D gates/continuity/
  canonical ×3, bench metrics ×7).
- `node --check web/app.js` + scratch Node harness running the REAL extracted
  `interpPlayerBoxes`/`interpPoseFrame`: relabel ≤2 boxes at every t, lerp
  intact, hold capped, beyond-maxGap honest (no fabricated glide).
- **uservid3 real-artifact rerun** (gated vs audit's ungated baseline of 20
  accepted shots with 5 below-floor / 9 out-of-bounds / 8 start-outside):
  13 accepted / 10 gated (`speed 1, peak 1, continuity 4, floor 1, bounds 2,
  contact_height 1`), **zero impossible acceptances**, median residual
  3.0 px, every rally still reconstructs (2–3 shots each).
- Bench smoke on uservid3 correctly FAILs `d3_below_floor_accepted` on the
  STORED (old-solver) rally_3d — the runner detects stale artifacts.

**Rollout (DONE 2026-07-11, same day):**
- Worker image `phase0-20260711` built via Cloud Build (5m03s, SUCCESS —
  weight bake verified the pinned ultralytics loads yolo26l/m), template
  `ic265brof1` patched via REST, warm workers bounced 0→2 (Cycle-17 gotcha),
  endpoint healthy (idle 1 / unhealthy 0).
- VM deployed via `bash deploy/deploy.sh`: baddy.service active,
  `{"ok":true}`, assets `app.js?v=36` live with the new interp code.
- GPU smoke (8s HSBC window via /media proxy, run `6997f947…-e2`, 42s):
  `worker_version=phase0-20260711`, tracker `botsort_baddy`, no track_error;
  **ids 1/2 present 48/48 frames (persistence fix confirmed on real GPU)**;
  tracknet `{coverage 1.0, longest_gap 0.8s, teleports 2, quality 0.886}` —
  honest metric live (not the flat 0.82). Old stored reels keep old tracking
  until reprocessed (`/api/jobs/{id}/retry?reprocess=1`).

**Open risks / next steps:** Phase-1 queue rows in PRD §16 (match_type
contract, crop-based pose, TrackNet overlap/InpaintNet A/B via the bench,
worker sampling-cap raise, real heatmap confidence + provenance, per-segment
calibration). Old stored reels keep old-solver `rally_3d` until reprocessed.

## Cycle 18: Tracking v2 + 3D flow fixes + timeline redesign (TASK-031/032/033)
**Date:** 2026-07-10
**Goal:** The three user-reported quality gaps: "player tracking is very shitty",
"pose tracking not good", "improve the timeline design", "fix the 3D environment
mapping flow".
**PRD:** §16 remediation (follow-ons to TASK-024/025/027/029/030), §8a editor anatomy.
**Branches (stacked):** `feat/TASK-031-player-pose-tracking-v2` →
`feat/TASK-032-court3d-flow` → `feat/TASK-033-timeline-redesign`, all off `0cae987`.

**TASK-031 — why tracking looked bad (found in review, fixed):**
- Phantom fallback boxes: worker+local injected two HARDCODED conf-0.12 player
  boxes whenever YOLO whiffed a frame; they passed the canonicalize (≥0.05) and
  camera (≥0.10) gates, steering the virtual camera to empty court and inflating
  player_quality past the pq≥0.28 trust gate. Removed — empty frames are honest.
- The camera ignored worker ByteTrack ids entirely (`_two_player_tracks` 2-slot
  nearest-centroid heuristic): rebuilt on continuous per-player tracks — track_id
  grouping, linear interpolation between ~6 Hz samples (was nearest-hold
  stair-steps), ghost expiry (slots used to persist forever), near/far hysteresis
  (anchor no longer teleports between crossing doubles partners).
- Tracker upgrade: BoT-SORT + native-feature ReID (`botsort_baddy.yaml`) tuned
  for the 6 Hz seeked-frame regime (gmc none, buffer 60 samples ≈10 s,
  match 0.85, proximity 0.25, appearance 0.6); per-rally reset of the sticky
  tracker-failure latch. Model default yolo26m→yolo26l-pose (l+m baked).
- Court gating: person detections gated to the (22%-expanded) court polygon
  BEFORE the top-4 cap on both backends, corners plumbed run.py→vision→payload;
  fail-safe to ungated when a bad quad would blank the frame.
- Identity plumbing: `_ids_from_worker` cliff 0.9→0.6 (one thin stretch used to
  discard ALL tracker ids); `_relabel_merged` now requires spatial continuity —
  height-only merging fused same-height doubles partners into one id.
- Pose: One-Euro filter per (person id, keypoint) on the public `pose_track`
  (`app/pipeline/smooth.py`); local path top-2→top-4; racquet caps 2→4.
**Rollout note:** worker image rebuild required for the worker-side pieces
(`gcloud builds submit --config runpod_worker/cloudbuild.yaml runpod_worker/
--substitutions=_TAG=trackingv2-20260710` → `python
scripts/runpod_update_endpoint_image.py --image …:trackingv2-20260710 --apply` →
bounce workers 0→2). Contract is additive; old workers keep working, and all
app-side fixes apply to old results too.

**TASK-032 — 3D mapping flow (silent failures made loud, real bugs fixed):**
- court.py: weak CV quad with Gemini declined was returned status "ok" at ANY
  confidence and drove heatmaps/3D with garbage geometry → now
  `low_confidence` below 0.35 (geometry kept for provisional display);
  synthetic net from the homography for manual/Gemini courts (the "Net line"
  toggle silently did nothing on them); `frame_wh` recorded.
- run.py: manual corners calibrated vs SOURCE dims (was proxy); pipeline notes
  when the court is missing/uncertain; slim non-ok `rally_3d` status on every
  rally. main.py forwards those statuses; POST /court runs the LM fits in
  `asyncio.to_thread` (it used to block the single event loop for seconds) and
  returns per-rally statuses.
- replay3d.js: honors `mirrored_frame` (legacy shuttle rendered x-mirrored vs
  marionettes); resize-before-memo (stale stretched canvas); removed the dead
  duplicated `break` that made the current-shot ribbon unreachable; 30 Hz
  repaint bucket = smooth marionette/shuttle interpolation over the 12 Hz sim;
  per-status empty-state text.
- Studio UX: 3D empty state explains WHY + "Draw court corners" CTA
  (cross-links to the Court layer + draw mode, pausing playback); Court layer
  shows uncertain/not-detected as actionable text; recompute reports per-rally
  outcomes; upload picker warns on degenerate quads the server silently drops
  (and no longer sends them).

**TASK-033 — timeline redesign (structural bugs, then polish):**
- Lanes fit: pose + soundtrack lanes (incl. the entire waveform feature)
  rendered into CLIPPED invisible space (202px row vs 240px content) — heights
  rebudgeted to 170px, row 236px (mobile 208px + scrollable board).
- Zoom: 80–99 was a dead range that desynced the playhead (%×scale vs a block
  lane that can't shrink) → floor 1x, max 6x, % readout, cursor/playhead
  anchoring, pinch/ctrl-wheel; playhead now pixel-positioned with edge-flip
  chip + auto-follow; adaptive ruler density (≥70px labels; was ~60 colliding
  labels on a 30-min source); per-SEGMENT selection; hover timecode ghost;
  `,`/`.` frame-step; filmstrip capture cache (zoom rebuilds stop re-seeking
  video); dead source-mode lanes removed; geometric lane icons.
- Assets bumped to style v=34 / app v=35 / replay3d v=32.

**Concurrent session note:** while TASK-033 was in flight another
session/editor was working in the same checkout; its Studio changes are
preserved verbatim in `4bc82f7` + `f5c65fd` + its own `0a87869` (landscape
response, media HEAD route) — not part of these tasks.

**Tests:** 102 passing (was 73): +19 TASK-031 (camera tracks, identity guards,
one-euro, court gate, phantom tripwire), +5 TASK-032 (acceptance floor,
synthetic net, status forwarding), +5 TASK-033 structural guards.
**Verification commands:**
- `./scripts/check.sh` → `102 passed`
- `node --check web/app.js` → OK
- Browser (live :8011 instance, viewport 1280×820, manual `studioTick()` ticks —
  the preview pane reports `visibilityState=hidden` so rAF never fires): all six
  lanes fully visible (soundtrack 34/34px, pose 24/24px — were 0px); playhead
  pixel-exact at 3× zoom (1689px @ t=dur/2); zoom anchor exact
  (scrollLeft 1126 after 1×→3× around center); hover ghost + per-seg selection +
  source-mode lane set verified; 3D-layer "Draw court corners" CTA enters draw
  mode with playback paused.

## Cycle 17: Production triage — GPU worker crash, render crash, doubles caps, retry (TASK-029)
**Date:** 2026-07-08
**Goal:** Fix the two crashes surfaced by real uploads and support doubles.
**Root causes (from live logs + RunPod status API):**
- Every GPU job that reached the pose-guided racquet-candidates fallback died:
  `HoughLinesP` returns `(N,4)` on the worker's OpenCV build (not `(N,1,4)`),
  so `line[0]` was a scalar → `TypeError: 'numpy.int32' object is not
  iterable` → whole vision job FAILED → silent CPU fallback (that's why
  today's job ran `local-…`). Latent since June; first executed when TASK-027
  wired the racquet task into the router. Fix: shape-agnostic flatten.
- Render crash `(138,1024,3) vs (138,1056,1)`: a long Gemini rally note made
  the lower-third badge wider than the 1080px frame; `_blend` clipped the
  frame slice but not the overlay. Fix: `_blend` crops both to the
  intersection; `_badge` ellipsizes the note to fit (job 9cca230f32a6).
- Doubles: worker/API capped players+poses at 2/frame → raised to 4 across
  `_detect_pose`, canonical `players`, confidences, wrist gates.
- `POST /api/jobs/{id}/retry` + queue Retry button: failed jobs re-run from
  the still-on-disk upload (no re-upload, no wasted GPU pass).
**Worker image:** `doubles-20260708` (Cloud Build) → template `ic265brof1`.
**Tests:** 70 passing (blend clip regression with the exact failing shapes,
badge cap, 4-player canonical passthrough, retry endpoint guards).
**Verification (live, 2026-07-08):**
- Warm-worker gotcha: patching the template does NOT recycle warm workers — the
  first retry still hit the old image (same Hough traceback). Bounced workers
  (workersMax 0→2); after that a direct contract job on `doubles-20260708`
  COMPLETED in 10.2s over the same footage: yolo26m pose, ByteTrack ids
  [1,2] (`track_error` empty), `racquet_source=coco-tennis-racket` with
  measured boxes on 9 frames, the once-fatal candidates path ran on 63 frames.
- Added `/api/jobs/{id}/retry?reprocess=1` (done-job reprocess through the
  current pipeline) and reprocessed the crashed HSBC job end-to-end on GPU:
  `worker_version=doubles-20260708`, pipeline=gpu, gen 395s, TrackNet 0.82,
  pose_track 90 frames ids [0,1], **racquet_track 35 frames (measured)**,
  court auto-detected (cv, 0.665), camera_path present, **rally_3d ok with 26
  shots** (221 km/h smash + 18–38 km/h exchanges) — the review's "no pose /
  no 3D / crash" symptoms all resolved on the user's own video. Doubles job
  reprocess queued for the 4-player caps.

## Cycle 16: Manual court drawing + configurable racquet chain (TASK-027)
**Date:** 2026-07-07
**Goal:** User-drawn court corners (upload + existing jobs, with instant
heatmap/3D recompute) and a configurable racquet-detection chain.
**Roadmap alignment:** PRD §16 TASK-027 (user request 2026-07-07).
**Branch:** `feat/TASK-027-manual-court-racquet` off `c5dc143`.
**Shipped:**
- `config.court_corners_option` validation; `court.manual_result`
  (source="manual", conf 0.98, handedness-normalized); run.process treats drawn
  corners as authoritative; upload UI grabs a frame CLIENT-SIDE from the picked
  file and guides 4 corner clicks while chunks upload.
- `POST /api/jobs/{id}/court`: recomputes court + every rally's `rally_3d`
  from stored tracks, persists to result.json + DB. Studio Court inspector
  gains a guided draw mode (landscape + reset framing → pure contain-box
  inversion of clicks).
- Racquet chain: router now requests the racquet task with pose; worker
  `RACQUET_MODEL` (custom) → COCO 'tennis racket' fallback (yolo11s baked,
  conf 0.18, wrist-gated ≤0.14 via pose) → pose-guided line candidates;
  provenance `model_status.racquet_source`; canonical rallies carry
  `racquets`; bounded `racquet_track` in the public payload; dashed amber
  outline overlay in the Studio. WORKER_VERSION `racquet-20260707`.
**Tests/verification performed:**
- `./scripts/check.sh` → 65 passed (option validation, manual_result
  handedness, endpoint recompute on a ballistic seed incl. disk+DB
  persistence, bad-corner rejection, racquet_track sampler).
- Browser on REAL footage: uservid3 (court undetectable by CV and declined by
  Gemini) → Studio draw mode → 4 clicks → "court saved — 5 rallies
  reconstructed in 3D"; court overlay 98%, heatmaps in court space, 3D replay
  panel live on real TrackNet tracks. Geometry quality tracks corner accuracy.
**Docs updated:** this log, ledger, PRD §16 (TASK-027 done, TASK-028 queued),
task files.
**Open risks / next steps:** COCO-fallback racquet recall is partial →
TASK-028 fine-tune; worker image `racquet-20260707` rollout + real-job racquet
sample pending.

## Cycle 15: Ship + queued tasks — deploy, ByteTrack ids, Gemini corners, 3D replay (TASK-023/024/025)
**Date:** 2026-07-07
**Goal:** Merge + deploy Cycles 13/14 to baddyai.com, then clear the queued task
files: worker-side player identity, Gemini court-corner fallback, and the
toggleable low-fps 3D rally replay.
**Roadmap alignment:** PRD §16 TASK-023/024/025; `docs/roadmap/RALLY_3D_RECONSTRUCTION.md`.
**Branches:** `feat/TASK-024-worker-bytetrack-ids`, `feat/TASK-023-gemini-court-corners`,
`feat/TASK-025-3d-rally-replay` (each ff-merged to main).
**Shipped:**
- **Deploy**: main `7137bcb` live on baddyai.com (assets v=27→v=29 by cycle end);
  health ok; login page 200; /api/auth/me 401; new Studio JS confirmed served.
- **TASK-024**: worker `_detect_pose` → `model.track(persist=True, bytetrack)`
  with per-rally id reset, `track_id` on boxes AND paired poses, predict
  fallback recorded in `model_status.track_error`; `lap` dep; gpu.py carries
  track_id; main.py samplers prefer worker ids at ≥90% coverage (shared
  fragment-merge + near-player-first relabel); ids never leak to the public
  payload. Image `bytetrack-20260707` (Cloud Build 3m37s) rolled out: template
  `ic265brof1` patched, endpoint healthy (ready 2 / unhealthy 0).
- **TASK-023**: `detect_from_video` shares sampled frames with a Gemini
  structured-output corner query when CV confidence < 0.5; schema-validated
  (visibility flag, 4 in-frame corners, ≥10% area, ≤0.08 cross-frame spread);
  provenance `court.source = cv | gemini | cv+gemini` (midpoint merge, done in
  a shared labeling BEFORE handedness normalization). Honest negative recorded:
  uservid3's court is not fully visible → Gemini correctly says so → no court.
- **TASK-025**: `rally3d.py` — camera pose from the homography (plane
  calibration + right-handed frame normalization now applied in court.py at
  detection time), drag-ballistic shot fitting (box-projected multi-start LM,
  recursive fused-shot bisect, mirror-minimum gates), `rally_3d` on each rally
  at 12Hz; Studio "3D replay" layer (OFF by default): dependency-free canvas
  3D panel — court/net/trajectory ribbon + km/h label/marionettes/racket
  lines, orbit + presets, repaint gated to the sim clock.
**Tests/verification performed:**
- `./scripts/check.sh` → 66 passed (4 ByteTrack-id tests, 5 Gemini-fallback
  tests, 6 rally3d ground-truth tests incl. apex ≤10% / speed ≤12% / landing
  ≤0.3m / focal ≤3%).
- Browser (fixture3d, a perspective ground-truth job built through the real
  reconstruction path): panel renders court+net+both marionettes; Side preset
  shows the shuttle mid-arc above net height with ribbon + "37.2 km/h";
  inspector lists 3 shots with residuals ≤13.4px; zero console errors.
- Live smoke after deploy: health ok, v=29 assets, auth endpoints, capabilities.
**Docs updated:** this log, `docs/progress-ledger.md`, task files 023/024/025 → done.
**Open risks / next steps:**
- Real-footage 3D sample still pending a video with the FULL court visible
  (record job id + shot speeds here when one lands).
- ByteTrack ids verified in contract/tests; confirm `worker_version=
  bytetrack-20260707` + 2 stable ids on the next real GPU job.
- Schools P1 (assign-to-student from a Studio track, cohorts) is the next
  platform slice.

## Cycle 14: Schools platform P0 — auth, tenancy, student progress panels (TASK-026)
**Date:** 2026-07-07
**Goal:** Start the school-platform pivot: authentication pages, school tenancy on
jobs, coach/admin panel, and the student profile (progress, highlights, rallies,
AI-coach details) — P0 of `docs/roadmap/SCHOOL_PLATFORM_PRD.md`.
**Roadmap alignment:** SCHOOL_PLATFORM_PRD §5 P0 (+ profile slice pulled forward
from P1/P2 since the pipeline data already supports it) · PRD §16 TASK-026.
**Branch:** `feat/TASK-026-schools-p0` (stacked on `fix/TASK-021-studio-review-fixes`).
**Files changed:** `app/{db,auth,main}.py`, `web/{login.html,app.html,platform.js,platform.css,index.html}`,
`tests/unit/test_schools_auth.py`, `requirements-dev.txt` (httpx for TestClient).
**Schema/API/interface changes:** additive tables users/schools/memberships/
auth_sessions/job_students; jobs +`school_id`/`uploaded_by` (guarded ALTERs);
new endpoints: auth register-school/join/login/logout/me, school/overview,
jobs/{id}/assign (+DELETE), students/{id}/profile. Session cookie
`baddy_session` (HttpOnly, SameSite=Lax, scrypt hashes, 14-day TTL); join codes
ST-/CO- (coach code visible to admins only). Signed-in uploads own their jobs;
anonymous flow byte-identical (regression-pinned).
**Tests/verification performed:**
- `./scripts/check.sh` → 46 passed (register/join/roles, tenancy scoping —
  cross-school assign 404s, student→overview 403, student→other-profile 403 —
  profile aggregation incl. court-space movement via the TASK-022 homography,
  anonymous-flow regression, migration idempotency).
- Browser walkthrough on localhost: created "Sunrise Academy" through the login
  page; student joined by ST- code; admin Overview showed join codes (copy
  buttons), roster, sessions with assignee chips + P1/P2 assign controls;
  student login rendered My Progress — stat cards with sparklines (2 sessions,
  7 rallies, 8s longest, 15m court distance), session videos, per-rally note
  chips, AI-coach box, "tracked as P1".
**Docs updated:** this log, `docs/progress-ledger.md`, PRD §16 row, TASK-026
filed to done (P0 scope; P1–P4 remain in the platform PRD).
**Open risks / next steps:**
- P1 next: Studio "assign to student" on a player track; student dashboard
  polish; cohorts. P2: assessments + progress aggregation server-side.
- Password reset flows + Google SSO deferred (P4); one-school-per-user in P0.
- Gallery/queue remain global (marketing surface) — school scoping of the
  public pages lands with the platform cutover decision.

## Cycle 13: Review fixes — portrait projection, court geometry, heatmaps (TASK-021/022)
**Date:** 2026-07-07
**Goal:** Fix the four baddyai.com review defects (portrait overlay shift, timeline
drag hijacked by the canvas, pose rendering as giant blobs, "only P1 tracked") and
land the tracking-first feature batch: track interpolation, `court.py`, Court
overlay, post-game movement heatmaps.
**Roadmap alignment:** PRD §16 TASK-021/022 (review intake 2026-07-07).
**Branch:** `fix/TASK-021-studio-review-fixes` off `29af265`.
**Files changed:** `app/pipeline/{render,run,court}.py`, `app/main.py`,
`runpod_worker/handler.py`, `web/{app.js,style.css,index.html}`,
`scripts/make_studio_fixture.py`, tests (3 new files / extended).
**Root causes fixed:**
- Portrait shift: the reel is a per-frame virtual-camera CROP; the Studio mapped
  source-normalized track coords onto it as if it were the source frame, and the
  reel→source time base ignored PAD_BEFORE (1.0s) and the 0.45s stitch crossfade
  per boundary. Renderer now exports the exact crop rect (`camera_path`) +
  `render_window`; the Studio inverts them (`toDisplayNorm`), landscape runs on
  source time (`effectiveMode`), legacy reels hide overlays with a rebuild hint.
- Timeline: no drag-to-scrub existed and the old seek divided by the whole #tl
  rect (label column skew); the transformed stage-frame painted above the
  non-positioned transport. Added board scrubbing with lane-rect math + pointer
  capture; transport/timeline got a stacking context.
- Pose blobs: 0–100 viewBox + `preserveAspectRatio:none` stretched joint circles
  to ~3% of frame WIDTH; skeleton SVG now renders in pixel space, 4 styles,
  velocity mode colored by measured motion.
- "Only P1": worker sorted boxes after building poses (pairing desync, fixed in
  `_detect_pose`) and serve-time greedy `next_id++` churned ids past a 0.22 gate;
  replaced with `_stable_ids` — bounded slot pool, motion+size-aware costs,
  size-based reuse after dropouts, fragment merging, near-player-first relabel.
**Features:** shuttle/box/pose keypoint interpolation between ≤10Hz samples;
`court.py` (line mask → Hough → quad + DLT homography to 6.10×13.40m plane,
`result["court"]`); Studio Court layer (boundary/net/corners through the same
projection); per-player post-game heatmaps (court-plane via homography, camera
space fallback); `scripts/make_studio_fixture.py` ground-truth fixture job.
**Tests/verification performed:**
- `./scripts/check.sh` → 42 passed (new: crop-rect export/inversion, camera_path
  passthrough, fast-motion+dropout id stability, 4 court-detection tests).
- Fixture verification in Chrome against baked ground truth: portrait-reel
  shuttle marker vs actual white-dot pixels ≤0.41% error at 5 probe times
  (both rallies, across the crossfade); landscape P1/P2 box centers exact
  (32.1/30.0 vs expected 32.1/30.0); court quad on the drawn lines in all views;
  drag-scrub seeks 3.0→10.53→3.95 across a synthetic pointer drag; legacy job
  (no camera_path) hides overlays + shows the rebuild hint in portrait and
  aligns correctly in landscape.
**Docs updated:** this log, `docs/progress-ledger.md`, PRD §16 rows
TASK-021..026, `docs/roadmap/RALLY_3D_RECONSTRUCTION.md`,
`docs/roadmap/SCHOOL_PLATFORM_PRD.md`, task files.
**Open risks / next steps:**
- RunPod worker pairing fix needs an image rebuild/deploy (`pose-pairing-20260707`).
- Real-footage identity still fragments under long occlusions (P3 shows up
  occasionally) → TASK-024 ByteTrack in the worker.
- 3D replay (TASK-025) and Schools P0 (TASK-026) are specced, not started.

## Cycle 12: Pose end-to-end + tracking robustness (TASK-017/018/019/020 + feedback batch)
**Date:** 2026-06-26
**Goal:** Ship real pose skeletons in Studio, harden shuttle tracking (false-detection
filter, keep-in-frame camera, smoother motion), fix Compose drag, comet trail, UI polish.
**Roadmap alignment:** PRD §16 (TASK-017–020) + 2026-06-26 user feedback.
**Branch:** `feat/TASK-017-pose-camera-upgrades` (codex WIP snapshot `8d09e11` +
takeover hardening `8deb7c1`).
**Files changed:** `app/config.py`, `app/main.py`, `app/pipeline/{vision,vision_local,gpu,track,render,run}.py`,
`runpod_worker/{handler.py,Dockerfile}`, `web/{app.js,style.css,index.html}`, tests.
**Schema/API/interface changes:** `_compact_vision` exposes bounded `pose_track`
(COCO-17 keypoints, stable person ids); `/api/capabilities` reports pose backend/model;
pose-only jobs route GPU-first (`POSE_BACKEND`, default gpu) with local fallback;
`RENDER_ZOOM_PUNCH` default 0.
**Tests/verification performed:**
- 32 passed (`./scripts/check.sh`): 5 new filter/containment regressions (spike
  rejection, spike-doesn't-move-camera ±0.02, fast-smash survival, conf/bounds,
  shuttle+player containment ≤0.005 escape), deterministic pose-routing tests,
  WIP's pose-contract + overlay-JS tests.
- yolo26 verified empirically (ultralytics 8.4.70 loads yolo26s); worker Dockerfile
  bakes yolo26m+yolo11n at build → build fails fast if a model is unavailable.
- Preview: 2 skeletons render (32 limbs/34 joints, per-person colours); comet trail
  + pulsing tip; Compose fast-drag lands exactly (window listeners); library
  ghost-drag drops at pointer (clientToWorld); no console errors.
- Deployed VM (v=25): live app.js serves POSE_LIMBS/initLibraryDrag/clientToWorld;
  capabilities → pose backend runpod, model yolo26m-pose.pt; health ok.
**Docs updated:** this log, `docs/progress-ledger.md`, `.agent/tasks/done/TASK-017–020`.
**Open risks / next steps:**
- RunPod worker image `pose-20260626a` building (Cloud Build) — template patch +
  worker-ready verification, then a representative GPU pose job to see skeletons live.
- Follow-ups: bake overlay styles into the MP4; unify render player identity with
  editor ids; per-edge NL agent for Compose.

## Cycle 11: Job queue UI + GET /api/jobs (TASK-005)
**Date:** 2026-06-23
**Goal:** Close the last queued backlog item — a queue view of submitted jobs with
live status, pipeline, and timing, on top of the TASK-003/004 timing fields.
**Roadmap alignment:** PRD §3/§7/§8 (queue), §16 P1 (TASK-005).
**Branch:** `feat/TASK-005-queue-ui`.
**Files changed:** `app/db.py`, `app/main.py`, `web/index.html`, `web/app.js`,
`web/style.css`, `tests/unit/test_job_model.py`.
**Schema/API/interface changes:** new `GET /api/jobs` (queue list) + `db.recent_jobs`.
No schema change (reads existing timing columns).
**Tests/verification performed:**
- Unit: `test_jobs_queue_lists_all_statuses_newest_first` — all statuses present,
  newest-first, error only on failed jobs, thumb on done, pipeline derived.
- Preview: `renderQueue` with 4 mock jobs → 4 cards; chips
  queued/processing/done/failed; failed-job error shown; done job has thumb +
  Studio button; section auto-hides when empty.
- `./scripts/check.sh` → 17 passed; no console errors.
- Merged to `main` (7a1226f). Also filed TASK-007 (reel-editor-ui, Cycle 4) to done.
**Docs updated:** this log, `docs/progress-ledger.md`.
**Open risks / next steps:**
- Single-tenant: the client filters the queue by its own `myJobs` ids; a server-side
  per-user filter is a later concern.
- Whole editor/camera/queue sweep (TASK-005, 010–015) merged but **not deployed**.

## Cycle 10: Player tracking + configurable virtual camera (TASK-015/014/010)
**Date:** 2026-06-23
**Goal:** Finish the editor/camera sweep — player/person tracking, a fully
configurable virtual camera (target shuttle|player|point + keyframes, baked into
the export), and the upload double-prompt fix.
**Roadmap alignment:** PRD §16 P0 (TASK-014), P1 (TASK-015, TASK-010); intake
`docs/reviews/2026-06-21-studio-camera-feedback.md`.
**Branches:** `fix/TASK-010-upload-double-prompt`, `feat/TASK-015-player-tracking`,
`feat/TASK-014-camera-keyframes`.
**Files changed:** `app/main.py`, `app/worker.py`, `app/pipeline/run.py`,
`app/pipeline/track.py`, `web/app.js`, `web/style.css`,
`tests/unit/test_public_editor_tracks.py`, `tests/unit/test_camera_plan.py`.
**Schema/API/interface changes:**
- `_compact_vision` now exposes `players_track` (bounded per-frame player boxes with
  stable ids). `baddy.editor.v1` gains `camera {enabled, keyframes[]}`
  (backward-compatible merge). `POST /api/jobs/{id}/remix` accepts an optional
  `camera` plan (sanitized by `_validate_camera`); `remix()` + worker thread it
  through to bake into the MP4.
**Tests/verification performed:**
- TASK-010: preview `fileInput.click()` spy — button/drop/rapid-double/retry all open
  the picker exactly once (was 2 on the button path). Root cause: `#browse` inside
  `#drop` double-fired; fixed with a busy guard + `stopPropagation`.
- TASK-015: `from app.main._sample_player_track` → bounded track, stable ids (unit
  test); preview — 2 player boxes at a tracked time, 0 in a gap / pose-off, 180
  Pose-lane presence dots in source mode; layer relabeled "Players & pose".
- TASK-014: preview — camera follows shuttle (L→pan right, R→pan left) and a chosen
  player; 3 keyframes (shuttle→player→point) render in the inspector + as 3 colour-
  coded diamonds on the Camera lane; plan persists across reload. Backend: 6 unit
  tests (target follow+switch, fixed-point steadiness, empty→None, reel→source
  keyframe mapping, plan validation).
- `node --check web/app.js` OK; `./scripts/check.sh` → 16 passed; no console errors.
- Merged to `main` (TASK-010 403b8ba, TASK-015 a75d99f, TASK-014 f550fec+aa4ef3d).
**Docs updated:** this log, `docs/progress-ledger.md`, PRD §16, `.agent/tasks/done/`.
**Open risks / next steps:**
- The TASK-014 export bake composes unit-tested pieces but is **not yet visually
  confirmed on a real render** — remix a job with a camera plan and watch the MP4.
- Render-time player identity (near/far) is not yet unified with the editor's
  per-player ids (singles approximation).
- Whole sweep (TASK-010–015) is merged but **not deployed** (held by the user).

## Cycle 9: Studio overlay/timeline/landscape fixes (TASK-011/012/013)
**Date:** 2026-06-21
**Goal:** Address the 2026-06-21 product-owner Studio review — kill the phantom
shuttle overlay, make the timeline lanes interactive, and let the user view +
reframe the original landscape footage. First three items of the
"all UI fixes first" sweep.
**Roadmap alignment:** PRD §16 P1 (TASK-011/012/013); intake
`docs/reviews/2026-06-21-studio-camera-feedback.md`.
**Branch:** `fix/TASK-011-overlay-correctness`, `feat/TASK-012-interactive-timeline`,
`feat/TASK-013-landscape-source-framing`.
**Files changed:** `web/app.js`, `web/style.css`, `web/index.html`.
**Schema/API/interface changes:** none (client-only). `index.html` cache-bust
bumped `v=17 → v=18` so deployed clients fetch the new app.js/style.css.
**Tests/verification performed (baddy-web preview, mock reel):**
- TASK-011: shuttle marker renders only at a tracked time — tracked time → 1
  marker, untracked time → 0 (the "weird circle" at the fixed 58%,31% default is
  gone); non-data pose skeleton removed (`currentPose()` returns null until
  TASK-015 exposes keypoints).
- TASK-012: Shuttle/Pose lane labels are ON/OFF toggles — clicking the Shuttle
  label flips `overlays.shuttle.enabled`; Source mode draws the shuttle track
  across the whole video (120 trajectory dots over `source_duration`).
- TASK-013: Portrait/Landscape toggle — landscape stage computes to the source
  native aspect (854/480, 646×363, wider than tall), full court visible; the
  Framing crop/zoom/pan applies in Source mode (`object-fit:cover` + transform).
- `node --check web/app.js` OK; `./scripts/check.sh` → 9 passed; no console errors.
- Merged to `main` (7b93916, 7cba2e8, 087d9fe), pushed. **Deploy to baddyai.com
  pending explicit authorization** (auto-mode blocked the production deploy).
**Docs updated:** this log, `docs/progress-ledger.md`, PRD §16,
`docs/reviews/2026-06-21-studio-camera-feedback.md`, `.agent/tasks/done/`.
**Open risks / next steps:**
- TASK-014 (configurable camera + keyframes) and TASK-015 (player/pose tracking)
  remain — TASK-015 also unblocks the real pose overlay deferred from TASK-011.
- Pending deploy to make 011/012/013 live (v=18 assets).

## Cycle 8: Detailed editor timeline + manual video framing (crop/reset)
**Date:** 2026-06-21
**Goal:** Make the Studio timeline more detailed/refined like a Descript-style
editor (filmstrip, captions, waveform); add manual video framing so the user can
re-crop the preview and reset to the original frame.
**Roadmap alignment:** PRD §8a reel editor UI.
**Branch:** `feat/TASK-008-timeline-refine`, `feat/TASK-009-manual-framing`
**Files changed:** `web/app.js`, `web/style.css`, `web/index.html`, `.claude/launch.json`.
**Schema/API/interface changes:** `baddy.editor.v1` gains `framing {fit, zoom, x, y}`
(client state, persisted; merged backward-compatibly). No backend API change.
**Tests/verification performed:**
- TASK-008 timeline: filmstrip clip lane (canvas frame capture, thumb fallback),
  Captions lane with dashed gap markers (trimmed dead-time), waveform lane
  (Web Audio peaks + stylized fallback), minor ticks, playhead time bubble.
  Driven in the `baddy-web` preview with a mock reel: 5 lanes, filmstrip frames,
  4 gap markers (15/8/14/25s), 141 waveform bars; no console errors.
- TASK-009 framing: Framing layer + inspector (Original/Crop toggle, Zoom + Pan
  sliders, drag-to-pan, "Reset to original"). Preview crop applies
  object-fit:cover + translate/scale; Reset restores contain + no transform;
  `videoFitPoint` updated so the shuttle overlay stays aligned under crop.
- `node --check web/app.js` OK; `./scripts/check.sh` → 9 passed.
- Merged to `main` (4a73dda, aaeeaef), pushed, deployed to baddyai.com (served
  app.js contains applyFraming/wave-bar/gap-mark; health ok).
**Docs updated:** this log, `docs/progress-ledger.md`.
**Open risks / next steps:**
- Framing + shuttle/pose styles are preview/persisted client state; baking the
  crop and overlay styles into the exported MP4 is a backend render-contract slice.

## Cycle 7: TASK-006 production VM resized to c2d-standard-8
**Date:** 2026-06-21
**Goal:** Finish TASK-006 by applying the chosen C2D production sizing without
breaking the live `baddyai.com` DNS target.
**Roadmap alignment:** PRD §16 P1 (TASK-006); §P1-INSTANCE.
**Branch:** `feat/TASK-003-004-006-pipeline-jobs-instance`
**Task file:** `.agent/tasks/done/TASK-003-004-006-pipeline-jobs-instance.md`
**Files changed:**
- `deploy/deploy.sh` — production default is now the actual live target:
  `us-central1-a` + `c2d-standard-8`. Mumbai remains a future DNS-backed
  migration option.
- `.agent/tasks/done/TASK-003-004-006-pipeline-jobs-instance.md`,
  `docs/progress-ledger.md` — TASK-006 evidence updated from guarded to applied.
**Schema/API/interface changes:** none.
**Tests/verification performed:**
- Pre-resize queue check via SSH: no `queued` or `processing` jobs.
- `gcloud compute instances stop baddy-agent --zone us-central1-a --quiet` → OK.
- `gcloud compute instances set-machine-type baddy-agent --zone us-central1-a --machine-type c2d-standard-8 --quiet`
  → OK.
- `gcloud compute instances start baddy-agent --zone us-central1-a --quiet` → OK.
- `gcloud compute instances describe baddy-agent --zone us-central1-a --format='table(...)'`
  → `MACHINE_TYPE c2d-standard-8`, `NAT_IP 136.113.208.173`.
- `gcloud compute addresses list --filter='name=baddy-agent-ip'` →
  `136.113.208.173`, `IN_USE`, `baddy-agent`.
- SSH systemd check → `baddy` and `caddy` active.
- `curl -fsS https://baddyai.com/api/health` → `{"ok":true}`.
- `dig +short baddyai.com A` → `136.113.208.173`.
- `https://baddyai.com/api/jobs/989cdb218317` still reports
  `pipeline=gpu`, `gen_seconds=424.6`, `expected_gen_seconds=600`.
- Live DB after reboot: columns include `pipeline`, `started_at`,
  `finished_at`; status counts `done=12`, `failed=2`; pipeline counts `cpu=9`,
  `gpu=5`; no active jobs.
- `./scripts/check.sh` → compile OK, `9 passed`.
**Docs updated:** this log, `docs/progress-ledger.md`, TASK-003/004/006 file.
**Open risks / next steps:**
- Mumbai remains a future migration/cost-latency optimization, not the current
  deployment, because `baddyai.com` DNS is hosted at GoDaddy
  (`domaincontrol.com`) outside this GCP project.

## Cycle 6: Pipeline metadata + job timing deployed; instance sizing guarded
**Date:** 2026-06-21
**Goal:** Complete TASK-003/TASK-004 runtime metadata and verify TASK-006 GCP
state without risking the live DNS target.
**Roadmap alignment:** PRD §4a two inference pipelines; §6 job model; §16 P1
(TASK-003, TASK-004, TASK-006); §P1-INSTANCE.
**Branch:** `feat/TASK-003-004-006-pipeline-jobs-instance`
**Task file:** `.agent/tasks/done/TASK-003-004-006-pipeline-jobs-instance.md`
**Files changed:**
- `app/db.py`, `app/config.py`, `app/worker.py`, `app/pipeline/run.py` — additive
  SQLite migration for `pipeline`, `started_at`, `finished_at`; CPU/GPU pipeline
  derivation from per-job options; canonical `failed` status; expected CPU/GPU
  generation budgets.
- `app/main.py` — job API now exposes submitted/start/finish timing,
  `gen_seconds`, `pipeline`, and expected generation seconds.
- `web/app.js`, `web/style.css` — polling handles `failed` jobs and displays
  pipeline/timing context.
- `deploy/deploy.sh` — default new-instance target updated to TASK-006
  `asia-south1-a` + `c2d-standard-8`, with explicit override note for current
  production until DNS cutover.
- `tests/unit/test_job_model.py` — migration + timing lifecycle coverage.
**Schema/API/interface changes:**
- `jobs` table adds nullable `pipeline`, `started_at`, `finished_at`.
- Legacy `status='error'` rows migrate to `status='failed'`.
- `GET /api/jobs/{id}` includes `pipeline`, `submitted_at`, `started_at`,
  `finished_at`, `gen_seconds`, and `expected_gen_seconds`.
**Tests/verification performed:**
- `.venv/bin/python -m pytest tests/unit/test_job_model.py -q` → `3 passed`.
- `.venv/bin/python -m pytest tests/unit/test_job_model.py tests/unit/test_public_editor_tracks.py -q`
  → `4 passed`.
- `node --check web/app.js` → OK.
- `python3 -m py_compile app/config.py app/db.py app/main.py app/worker.py app/pipeline/run.py`
  → OK.
- `./scripts/check.sh` → compile OK, `9 passed`.
- Production deploy: `ZONE=us-central1-a MACHINE=e2-standard-4 bash deploy/deploy.sh`
  → `{"ok":true} <- app healthy`.
- Production DB verification via `gcloud compute ssh baddy-agent --zone us-central1-a`:
  columns include `pipeline`, `started_at`, `finished_at`; status counts
  `done=12`, `failed=2`; pipeline counts `cpu=9`, `gpu=5`; all 14 terminal
  jobs timed.
- Live API verification:
  `https://baddyai.com/api/jobs/989cdb218317` reports `pipeline=gpu`,
  `gen_seconds=424.6`, `expected_gen_seconds=600`.
- TASK-006 GCP audit:
  live VM is `baddy-agent`, `us-central1-a`, `e2-standard-4`,
  `136.113.208.173`; DNS `baddyai.com` points to that IP; Mumbai supports
  `c2d-standard-8`; current IP promoted to reserved static address
  `baddy-agent-ip`.
**Docs updated:** this log, `docs/progress-ledger.md`, active TASK-003/004/006 file.
**Open risks / next steps:**
- Full TASK-006 cutover is not applied yet: the PRD target is
  `c2d-standard-8` in `asia-south1`, but production remains the existing
  `e2-standard-4` in `us-central1-a` to avoid unplanned DNS/downtime. Next step:
  choose either in-place `c2d-standard-8` resize on the now-static us-central IP,
  or create a Mumbai VM and cut DNS to its new address.

## Cycle 5: GPU TrackNetV3 deps fix — shuttle tracking verified end-to-end
**Date:** 2026-06-21
**Goal:** TrackNetV3 ran on the rebuilt GPU worker but failed every rally (fell
back to the motion shuttle). Fix it and verify real shuttle points flow through
baddyai.com.
**Roadmap alignment:** PRD §16 P0 (worker rebuild); §4a GPU pipeline.
**Branch:** `feat/TASK-007-reel-editor-ui` (integrated)
**Files changed:** `runpod_worker/requirements.txt` (+matplotlib, +pycocotools —
predict.py's `utils.general` import chain needs them; without them predict.py
exited 1 at import), `runpod_worker/handler.py` (surface predict.py stderr in
`_tracknet_error` instead of a bare CalledProcessError).
**Schema/API/interface changes:** none.
**Tests/verification performed:**
- rebuilt `tracknet-src-20260621b` (Cloud Build `f8c14a58`, single-arch); created
  template `ic265brof1`; PATCHed endpoint to it.
- e2e via baddyai.com (upload proxy → GPU): every rally `tracknet.status=ok`,
  55–122 real TrackNetV3 points, quality 0.82, `backend=runpod`. (Was
  `status=failed`/0 points → motion fallback before the fix.)
- worker boots `ready:2 unhealthy:0`; scales to 0 when idle (no idle cost).
**Docs updated:** this log, `docs/progress-ledger.md`.
**Open risks / next steps:**
- Soft-proxy framing still safe-cams some rallies (camera choice, not tracking).
- Server `.env` now carries the live RunPod key (deployed); rotate if leaked.
- Merge `feat/TASK-007` → `main` (worker verified end-to-end).

## Cycle 4: Reasoned reel editor controls + dead-flow removal
**Date:** 2026-06-21
**Goal:** Audit every visible Studio editor control, remove user flows that do
not have a current preview/backend/evidence path, and document the reason each
remaining component exists.
**Roadmap alignment:** PRD §8a reel editor UI; §16 remediation P1 (TASK-007).
**Branch:** `feat/TASK-007-reel-editor-ui`
**Task file:** `.agent/tasks/active/TASK-007-reel-editor-ui.md`
**Files changed:**
- `web/index.html`, `web/style.css`, `web/app.js` — removed the non-functional
  top tool ribbon, generic Editor button, manual save, split/snap controls, and
  editable music controls; kept top actions, layer rail, inspector, transport,
  and timeline controls that have concrete behavior.
- `web/app.js` — changed `baddy.editor.v1` audio state to read-only
  `audio.bed/current-stitch`; Soundtrack is context only until backend audio
  render props exist.
- `docs/roadmap/REEL_EDITOR_COMPONENT_RATIONALE.md` — new component-by-component
  rationale and removed-flow ledger.
- `docs/roadmap/PRIMARY_PRD.md`, `docs/roadmap/REEL_EDITOR_UX_RESEARCH.md`,
  `.agent/tasks/active/TASK-007-reel-editor-ui.md` — updated product contract
  language for reasoned controls and read-only Soundtrack.
**Schema/API/interface changes:** no backend API change. Client editor state now
models the current audio bed as read-only instead of exposing editable music
choices that do not affect export.
**Tests/verification performed:**
- `node --check web/app.js` → OK.
- `./scripts/check.sh` → compile OK, `6 passed`.
- Static rendered QA via `python3 -m http.server 8018 --directory web` plus
  bundled Playwright:
  `/tmp/baddy-reasoned-editor-desktop.png`,
  `/tmp/baddy-reasoned-editor-shuttle.png`, and
  `/tmp/baddy-reasoned-editor-mobile.png`; verified `topToolButtons: 0`,
  `timelineDeadButtons: 0`, `editButton: 0`, no horizontal overflow, four
  layers/tracks (`Reel cuts`, `Shuttle FX`, `Pose skeleton`, `Soundtrack`), and
  Shuttle Fire preview state.
**Docs updated:** this log, `docs/progress-ledger.md`, PRD §8a, research/schema
doc, component rationale doc, TASK-007 file.
**Open risks / next steps:**
- Export still renders only rally order + mirror. Baking shuttle FX, pose
  skeletons, text/graphics, and soundtrack choices into MP4 remains a backend
  render-contract slice.
- Trim/split, undo/redo, text, and editable music should stay hidden until the
  corresponding persisted edit document and render contracts exist.

## Cycle 3: Clean from-source RunPod worker image + tracking confirmation
**Date:** 2026-06-21
**Goal:** Rebuild the GPU worker so it boots (every prior "clean" image was a
re-wrap that inherited the OCI-attestation defect); confirm shuttle tracking works
independent of the camera.
**Roadmap alignment:** PRD §16 P0 (worker rebuild); §4a (GPU pipeline).
**Branch:** `feat/TASK-001-shuttle-follow-camera`
**Files changed:** `runpod_worker/cloudbuild.yaml` (new), `runpod_worker/patch_dataset.py`
(new), `runpod_worker/Dockerfile` (heredoc → COPY+RUN patch script).
**Schema/API/interface changes:** none (worker image + build only).
**Tests/verification performed:**
- `gcloud builds submit --config runpod_worker/cloudbuild.yaml runpod_worker/` →
  build `e13cb560` SUCCESS; pushed `baddy-vision-worker:tracknet-src-20260621`.
- manifest check → `application/vnd.docker.distribution.manifest.v2+json`,
  single-arch (no OCI index / no unknown/unknown attestation — the prior defect).
- tracking confirmation: drew saved `vision.shuttle` coords on the proxy
  (`/tmp/overlay.py` → `baddy_shuttle_tracking_overlay.mp4`); crosshair tracks the
  shuttle in the play area (146 tracked frames in one rally). Coords are persisted
  in `result.json` `rallies[].vision.shuttle` and exposed via `vision.shuttle_track`.
- `./scripts/check.sh` → `6 passed`.
**Docs updated:** progress-ledger.
**Open risks / next steps:**
- Deploy: point the RunPod endpoint at `tracknet-src-20260621` and verify health +
  a test job. Blocked: `RUNPOD_API_KEY` in `.env` returns 401 → needs a fresh key
  (then API deploy) or a console release.
- Then verify baddyai.com runs a GPU shuttle job end-to-end.

## Cycle 2: Professional reel editor UI
**Date:** 2026-06-20
**Goal:** Turn Studio from a rally viewer into a professional AI reel editor for
badminton highlights.
**Roadmap alignment:** PRD §8a reel editor UI; §16 remediation P1 (TASK-007).
**Branch:** `feat/TASK-007-reel-editor-ui` (base `883786f`)
**Task file:** `.agent/tasks/active/TASK-007-reel-editor-ui.md`
**Files changed:**
- `web/index.html`, `web/style.css`, `web/app.js` — Remotion-style editor shell:
  tool ribbon, layer rail, central 9:16 canvas, right inspector, transport, and
  multi-lane timeline.
- `web/app.js` — local `baddy.editor.v1` state for rally order, mirror, shuttle
  FX, pose skeleton, and music choices; inspector controls for shuttle
  ring/fire/square/trail, pose styles, and music settings.
- `app/main.py` — bounded `vision.shuttle_track` public payload for editor
  overlay preview.
- `docs/roadmap/REEL_EDITOR_UX_RESEARCH.md` — reference review and editor schema.
- `tests/unit/test_public_editor_tracks.py` — regression for public shuttle track
  exposure.
**Schema/API/interface changes:** public rally vision objects may include
`shuttle_track` with up to 180 normalized source-time samples:
`{t,x,y,confidence}`. Client editor state uses `baddy.editor.v1`.
**Tests/verification performed:**
- `.venv/bin/python -m pytest tests/unit/test_public_editor_tracks.py -q` →
  `1 passed`
- `node --check web/app.js` → OK
- `./scripts/check.sh` → compile OK, `6 passed`
- Static visual QA via `python3 -m http.server 8018 --directory web` plus
  bundled Playwright mock Studio:
  desktop `/tmp/baddy-editor-ui.png` and `/tmp/baddy-editor-shuttle.png` checked;
  mobile `/tmp/baddy-editor-mobile.png` checked; no horizontal overflow; 4 layers,
  4 timeline tracks, Shuttle FX inspector and Fire preview verified.
**Docs updated:** this log, `docs/progress-ledger.md`, PRD §8a, research/schema doc.
**Open risks / next steps:**
- FastAPI startup begins queued background jobs; for visual QA use static serving
  or add a dev flag to disable the worker.
- Current backend remix endpoint renders rally order + mirror only. Persisting
  `baddy.editor.v1` server-side and baking shuttle/pose/music choices into MP4 is
  the next editor backend slice.

## Cycle 1: Camera follows the shuttle + harness adoption
**Date:** 2026-06-20
**Goal:** Make the virtual camera actively follow/centre the shuttle (it tracked
players, not the shuttle); adopt the pragmatic v2 harness.
**Roadmap alignment:** PRD §16 remediation P0 (camera follows shuttle); §4a.
**Branch:** `feat/TASK-001-shuttle-follow-camera` (base `5f1c165`)
**Task file:** `.agent/tasks/active/TASK-001-shuttle-follow-camera.md`
**Files changed:**
- `app/pipeline/track.py` — `_shuttle_track()` (gap-interpolated shuttle) + rewrote
  `from_vision()` to follow the shuttle horizontally, contain the nearest player
  (far too when it fits), and anchor vertically on the player+shuttle span.
- `app/pipeline/validate.py` + `app/pipeline/run.py` — `lenient_framing` audit for
  the shuttle-follow camera (only true off-court frames count); motion camera keeps
  the strict audit.
- harness scaffolding (AGENTS/CLAUDE/docs/.agent/tests/scripts) — chore `dc4f763`.
**Schema/API/interface changes:** `validate.validate_clip(..., lenient_framing=False)`
and `validate.gemini_review(..., lenient=False)` added (backwards-compatible defaults).
No DB/HTTP changes.
**Tests/verification performed:**
- `./scripts/check.sh` → compile OK, `6 passed` (pytest tests/)
- re-render user clip via cached-vision harness → `DONE 38.2s | 5 rallies`; rallies
  3–5 use the shuttle-follow camera (verified frames: shuttle ring centred, both
  players framed); rallies 1–2 fall back to safe (hard source angle: foreground
  spectator + arena ceiling make a full-height crop read as empty).
**Docs updated:** this log, `docs/progress-ledger.md`.
**Open risks / next steps:**
- Soft 480p proxy + hard angle limit 2/5 rallies → re-run on the sharp original
  (currently TCC-blocked) for a full follow + crisp output.
- `if not pov` (run.py:137) still gates `from_vision` off for handheld clips → P2.
- Next: TASK-002 RunPod worker rebuild; TASK-003/004/005 dual pipelines + queue.
