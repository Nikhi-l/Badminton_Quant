# Baddy — Primary PRD (canonical)

> Canonical product + architecture + remediation queue. On conflict this overrides
> README and old notes. See `AGENTS.md` for precedence.

## 1. Executive summary
Baddy turns uploaded game video into beat-synced vertical (9:16) highlight reels
of the longest rallies, with a virtual camera that tracks the action and centers
the shuttle. Badminton-first, multi-sport. Live at baddyai.com.

## 2. Users / personas
- **Player / hobbyist** uploads a match clip, wants a shareable highlight reel.
- **Operator (us)** needs a cheap, predictable cost envelope (≤10k INR/mo VM +
  small GPU burst credits) and visibility into the job queue.

## 3. Core use cases
1. Upload one or more clips → get a highlight reel.
2. Watch submitted jobs in a **queue** with live status (queued / processing /
   done / failed) and submission + generation time.
3. Choose analysis depth per job (shuttle tracking, pose, coach).

## 4. Architecture
FastAPI + uvicorn; SQLite (WAL) job store; single background worker thread.
Pipeline (`app/pipeline/run.py`): combine → probe → proxy → rallies (Gemini) →
**vision** → tracking → render → validate → stitch.

### 4a. Two inference pipelines (this milestone)
A job runs through exactly one of:
- **CPU pipeline** — runs entirely **on the VM instance** (`vision_local.py`):
  configurable YOLO pose, optional CPU TrackNetV3. No external GPU. Slower; used
  when GPU is off/unavailable or the user picks the cheap path.
- **GPU pipeline** — TrackNetV3 and/or configurable YOLO pose on **RunPod
  serverless GPU** (`runpod_worker/`), CPU camera/render still on the VM. Faster
  shuttle tracking and higher-accuracy pose when configured.

Pipeline selection is derived from per-job `options` (`shuttle=tracknetv3` → GPU;
pose-only can also use GPU when `POSE_BACKEND` is GPU-first and RunPod is
configured) and recorded on the job as a `pipeline` field so the UI and timing can
distinguish them. CPU and GPU have **separate expected generation-time** budgets.

## 5. Service layout
- `app/main.py` — HTTP API + static web.
- `app/db.py` — SQLite job store (additive migrations only).
- `app/pipeline/` — run, media, rally (Gemini), vision (router), vision_local
  (CPU/MPS), gpu (RunPod transport), track (camera), render, validate.
- `runpod_worker/` — Docker image + handler for the GPU pipeline.
- `web/` — static SPA (upload, gallery, queue).

## 6. Data architecture — job model
`jobs` table (SQLite). Existing: id, filename, status, stage, message, result,
error, options, created_at, updated_at. **Additive columns this milestone:**
`pipeline` (cpu|gpu|unknown), `started_at`, `finished_at`. Status vocabulary:
`queued` → `processing` → `done` | `failed`. Submission time = `created_at`;
generation time = `finished_at − started_at`.

## 7. API contracts (current + planned)
- `POST /api/upload*` create job. `GET /api/jobs/{id}` single job.
  `GET /api/gallery` done jobs. **Planned:** `GET /api/jobs` list (queue) with
  status, pipeline, submitted_at, gen_seconds.

## 8. Frontend flows
Upload → job appears in **Queue** with live status + timer → on done moves to
gallery / My Reels. Queue shows failed jobs with the error.

### 8a. Reel editor UI
After a reel is done, **Studio** opens as a professional AI reel editor, not just
a video viewer. Required editor anatomy:
- top-level actions for Reel/Source analysis view, export, and close;
- left layer rail for Reel cuts, Shuttle FX, Pose skeleton, and Soundtrack;
- central 9:16 canvas preview;
- right inspector with controls for the selected layer;
- bottom multi-lane timeline synchronized to video playback.

Editor state uses `baddy.editor.v1` (see
`docs/roadmap/REEL_EDITOR_UX_RESEARCH.md`) and must cover rally order, mirror,
shuttle graphic style (ring/fire/square/trail), and pose skeleton style. Today
the remix API renders rally order + mirror; shuttle and pose style controls are
preview/persisted client state until the backend render contract accepts overlay
style props. Studio pose preview must use real `vision.pose_track` keypoints when
available, with the Pose layer toggle gating all pose/player overlay visuals.
Music selection/ducking controls are intentionally absent until a server-rendered
audio-track contract exists.

## 9–12. Auth / observability / local dev / testing
No auth yet (single-tenant). Logs via stage/message on the job. Local dev: run
uvicorn against the venv. Testing: `tests/` with regression coverage for camera
geometry and the job model; external services mocked.

## 13. Migration plan
Additive SQLite column adds guarded by `PRAGMA table_info`. VM resize is a
separate ops step (see remediation P1-INSTANCE).

## 14. Release plan
Per-task branch → PR → `main` → deploy (`deploy/`) → verify baddyai.com health.

## 15. Non-goals (now)
Multi-tenant auth, billing, real-time streaming, mobile app.

## 16. Implementation review intake + remediation queue
Source: user request 2026-06-20 (this session) + harness PDF.

| Pri | Item | Decision | Task |
|---|---|---|---|
| P0 | Camera must actively follow + center the shuttle (zoom not following today) | Accept | TASK-001 (active) |
| P0 | Rebuild RunPod GPU worker from source (Cloud Build) so GPU pipeline works; verify baddyai.com | Accept | TASK-002 |
| P1 | Formalize CPU vs GPU pipelines; record `pipeline` on each job; separate gen-time budgets | Accept | TASK-003 |
| P1 | Job model: add `started_at`/`finished_at`, `failed` status; submission-time tracking | Accept | TASK-004 |
| P1 | Queue UI + `GET /api/jobs`: live status, failed jobs, CPU/GPU gen time | Accept | TASK-005 |
| P1 | **Instance sizing** — see decision below | Accept | TASK-006 |
| P1 | Professional reel editor UI: layer rail, inspector, multi-lane timeline, overlay/music controls | Accept | TASK-007 |
| P1 | (bug) Overlay correctness: hide shuttle/pose marker when untracked at current time (the "weird circle" at a fixed/last spot); render pose overlay from real keypoints | Accept | TASK-011 |
| P1 | Interactive timeline lanes: toggle shuttle/pose overlays from the timeline; Source mode shows the shuttle track across the whole video timeline | Accept | TASK-012 |
| P1 | Landscape (16:9) ↔ portrait (9:16) preview toggle; manual reframe in Source rallies to pick highlight regions of the original landscape video | Accept | TASK-013 |
| P0 | Configurable virtual camera: target = shuttle \| player \| fixed point + zoom/pan + **keyframes** (switch target over time); bake the camera plan into the exported reel (render contract) | Accept | TASK-014 |
| P1 | Person/player tracking: detect + track players; expose as a camera follow-target and a timeline lane/overlay (feeds TASK-014) | Accept | TASK-015 |
| P1 | Preserve real pose keypoints end-to-end and expose bounded `pose_track` for Studio skeletons | Accept | TASK-017 |
| P1 | Decouple public pose option from model version; configure stronger YOLO pose models and GPU-first pose routing | Accept | TASK-018 |
| P1 | Make Studio Pose layer a true toggle and render skeletons from `pose_track` | Accept | TASK-019 |
| P1 | Smooth camera zoom by removing hardcoded opening punch and allowing high-quality TrackNet shuttle-follow on POV clips | Accept | TASK-020 |
| P0 | (bug, review 2026-07-07) Portrait overlay misalignment: invert the baked virtual camera (export `camera_path`/`render_window`), xfade-aware reel time; timeline drag-to-scrub + stacking; pixel-space pose skeletons; stable bounded player ids (near player = P1) | Accept | TASK-021 (**done**) |
| P1 | Tracking polish batch: track interpolation (shuttle/boxes/pose), `court.py` line/corner detection + homography, Studio Court layer, post-game per-player movement heatmaps, ground-truth fixture harness | Accept | TASK-022 (**done**) |
| P2 | Gemini court-corner refinement fallback when classical detection is low-confidence | Accept | TASK-023 |
| P1 | Worker-side identity: ultralytics ByteTrack (`model.track(persist=True)`) so player ids come from the tracker, not serve-time heuristics; carry ids through `players`/`poses` payloads | Accept | TASK-024 |
| P1 | 3D rally replay layer (toggleable, low-fps sim): camera pose from court homography, ballistic shuttle 3D fit, three.js court/net/players/replay — see `docs/roadmap/RALLY_3D_RECONSTRUCTION.md` | Accept | TASK-025 |
| P1 | Schools platform P0: auth (admin/coach/student), school tenancy on jobs, role dashboards — see `docs/roadmap/SCHOOL_PLATFORM_PRD.md` | Accept | TASK-026 (**P0 done**; P1–P4 in the platform PRD) |
| P0 | (audit 2026-07-11, Phase 0) Deterministic tracking/3D bugs: worker tracker persist-capture (ids reborn every frame), threshold misalignment, misleading "82%" shuttle score, public-track decimation below Studio continuity, Studio id-union/stale-hold, raw-vs-filtered track divergence (export/3D), ungated physically-impossible 3D fits | Accept | TASK-034 (**done + deployed 2026-07-11**: worker `phase0-20260711` + VM, GPU-smoke verified) |
| P1 | (smash-speed paper intake 2026-07-11) Measured shuttle confidence at canonicalization: constant-velocity innovation scoring fwd+bwd, static-run + max-speed kinematic gates, `provenance:"observed"`; radar-comparable `speed_at_net_kmh` next to impact `speed_kmh` on 3D shots; bench speed protocol (validate AT-NET vs radar, camera-angle diversity) | Accept | TASK-035 (**done**) |
| P1 | (audit Phase 1) `match_type=singles\|doubles\|auto` contract end-to-end: per-court-half player cardinality, doubles-aware quality expectations, roster pinning | Queued | TASK-036 |
| P1 | (audit Phase 1) Pose on per-player crops (court-aware detect → persistent tracks → high-res crop → top-down pose → kinematic filter) instead of whole-frame; far-player PCK is the gate, not model size | Queued | TASK-037 |
| P1 | (audit Phase 1) TrackNet config A/B on the labelled bench (overlap vs nonoverlap eval, InpaintNet on/off), then fine-tune vs replace decision by `scripts/bench/run_bench.py` gates | Queued | TASK-038 |
| P2 | (audit Phase 1) Worker sampling: raise/replace the 180-frame rally cap so long rallies keep true 6 Hz; REAL TrackNet heatmap confidence on shuttle points (TASK-035 shipped app-side measured confidence + `observed` provenance; the model's own heatmap scores + inpainted\|predicted labels still pending) | Queued | — |
| P2 | (audit Phase 2) Per-static-segment camera calibration; fuse audio impacts/wrists/rackets/net crossings into hit detection; joint adjacent-shot fitting with contact continuity; measured player roots before 3D pose lifting — see `docs/roadmap/RALLY_3D_RECONSTRUCTION.md` | Queued | — |

Intake: `docs/reviews/2026-06-21-studio-camera-feedback.md`. **TASK-011/012/013
(Cycle 9) and TASK-010/014/015 (Cycle 10) are merged to `main`** (statuses +
caveats in `docs/progress-ledger.md`). TASK-017/018/019/020 are the follow-up
vision/editor/camera hardening slice for real pose skeletons, configurable pose
models, pose-only GPU routing, and smoother shuttle-follow camera output.

### P1-INSTANCE decision (research 2026-06-20)
Budget 10k INR/mo (~$120). **Recommended: `c2d-standard-8`, region `asia-south1`
(Mumbai), 1-year CUD ≈ $110/mo (~9,150 INR)** — 2× vCPU/RAM vs current
e2-standard-4 (8 vCPU / 32 GB, AMD Milan), ~2.2–2.5× CPU-pipeline throughput,
lower latency to IN users. **Runner-up:** `c2d-standard-4` Mumbai on-demand
($87/mo, < current bill, ~1.4× faster, zero commitment). Mumbai c2d is ~34%
cheaper than us-central1 — confirm in the GCP calculator before a 1-yr CUD.
