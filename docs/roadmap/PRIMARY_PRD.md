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
  YOLO11 pose, optional CPU TrackNetV3. No external GPU. Slower; used when GPU is
  off/unavailable or the user picks the cheap path.
- **GPU pipeline** — TrackNetV3 (+pose bundled) on **RunPod serverless GPU**
  (`runpod_worker/`), CPU camera/render still on the VM. Faster shuttle tracking.

Pipeline selection is derived from per-job `options` (shuttle=tracknetv3 → GPU;
else CPU) and recorded on the job as a `pipeline` field so the UI and timing can
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
- top tool ribbon for select, trim, shuttle FX, pose, text, music, undo/redo,
  save, and export;
- left layer rail for Reel cuts, Shuttle FX, Pose skeleton, and Music bed;
- central 9:16 canvas preview;
- right inspector with controls for the selected layer;
- bottom multi-lane timeline synchronized to video playback.

Editor state uses `baddy.editor.v1` (see
`docs/roadmap/REEL_EDITOR_UX_RESEARCH.md`) and must cover rally order, mirror,
shuttle graphic style (ring/fire/square/trail), pose skeleton style, and music
track/volume/ducking. Today the remix API renders rally order + mirror; shuttle,
pose, and music style controls are preview/persisted client state until the
backend render contract accepts overlay style props.

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

### P1-INSTANCE decision (research 2026-06-20)
Budget 10k INR/mo (~$120). **Recommended: `c2d-standard-8`, region `asia-south1`
(Mumbai), 1-year CUD ≈ $110/mo (~9,150 INR)** — 2× vCPU/RAM vs current
e2-standard-4 (8 vCPU / 32 GB, AMD Milan), ~2.2–2.5× CPU-pipeline throughput,
lower latency to IN users. **Runner-up:** `c2d-standard-4` Mumbai on-demand
($87/mo, < current bill, ~1.4× faster, zero commitment). Mumbai c2d is ~34%
cheaper than us-central1 — confirm in the GCP calculator before a 1-yr CUD.
