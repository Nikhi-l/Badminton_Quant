# CLAUDE.md

**Operating rules live in [AGENTS.md](AGENTS.md)** — source-of-truth precedence,
branching (never commit to `main`), commit rhythm, testing, migrations, secrets,
definition of done. Read it first. This file adds Baddy-specific quick context.

## What Baddy is
Automated sports-highlight generator. Users upload game video (badminton-first,
multi-sport); the app returns a beat-synced vertical (9:16) highlight reel of the
longest rallies with a virtual camera that tracks the action and centers the
shuttle. Dark Midjourney-style UI + gallery. Deployed on GCP (profile
`dotredlabs`), live at **baddyai.com** (Caddy + Let's Encrypt TLS).

## Architecture (one-liner)
FastAPI + uvicorn; SQLite (WAL) job store (`app/db.py`); single background worker
thread. Pipeline (`app/pipeline/run.py`): combine → probe → proxy → rallies
(Gemini) → vision → tracking → render → validate → stitch.

## Vision workers (per-job flags)
`config.normalize_options`: `shuttle` = off | tracknetv3, `pose` = off | yolo11,
`coach` = bool. Routing in `app/pipeline/vision.py`:
- **GPU pipeline**: TrackNetV3 (+pose) → RunPod serverless GPU (`runpod_worker/`).
- **CPU pipeline**: YOLO11 pose (and optional CPU TrackNetV3) on the VM in-process
  (`app/pipeline/vision_local.py`), CUDA > MPS > CPU device auto-select.

## Camera
`app/pipeline/track.py`: `from_vision()` builds the virtual-camera FocusPath from
player boxes + shuttle; `track.track()` is the motion-centroid fallback.
`run.py:137` uses `from_vision` only when `not pov`.

## Canonical plan
`docs/roadmap/PRIMARY_PRD.md` — architecture + the remediation queue (current
work items). `docs/progress-ledger.md` — where we are now.

## Gotchas (carried)
- numpy 2.x: `np.asarray(PIL)` is read-only → use `np.array()` for writable copies.
- TrackNetV3 `predict.py` runs with `cwd=REPO`; clip paths MUST be absolute.
- `~/Downloads` may be sandbox/TCC-blocked; work from files inside the project dir.
