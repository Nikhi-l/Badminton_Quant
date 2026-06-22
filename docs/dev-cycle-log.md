# Dev-cycle log

One entry per meaningful product cycle. Each cites the PRD section it advances and
lists exact verification commands. Newest first.

<!-- New cycles appended below. -->

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
