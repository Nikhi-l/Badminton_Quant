# 🏸 Baddy — AI Badminton Highlight Agent

Upload a raw badminton recording → get back a beat-synced, vertical (9:16) highlight
reel of your longest rallies, framed by an AI virtual camera. Fully automated.

## Pipeline

```
upload (any res, 4K ok; one file or several clips of the same game)
  └─ combine ──────── multi-clip: order by recording time (creation_time metadata;
  │                   upload order when absent), normalize to common geometry, concat
  └─ probe ────────── ffprobe metadata + rotation handling
  └─ proxy ────────── 480p/30fps H.264 proxy (all analysis is low-res; final render is full-res)
  └─ rallies ──────── proxy uploaded to Gemini Files API; gemini-3.5-flash returns every
  │                   rally's start/end/intensity as JSON (gemini-3.1-pro-preview fallback)
  └─ select ───────── rallies ranked longest-first, capped to ~59 s story budget
  └─ vision ───────── optional Runpod Serverless GPU pass on the proxy: players / pose /
  │                   racquet / shuttle tracks returned as normalized coordinates; weak or
  │                   missing results fall back to CPU tracking
  └─ tracking ─────── GPU player boxes can drive a two-person crop; otherwise per-rally
  │                   motion analysis on the proxy: flicker-masked motion cells →
  │                   weighted 2-means = the two players (with stillness memory) → shuttle =
  │                   coherent motion away from both bodies → framing by CONTAINMENT: the
  │                   shuttle + active player must sit inside the crop with padding, the
  │                   second player joins whenever zoom-out can fit them; keyframes every
  │                   0.5 s + cosine interpolation + EMA + pan-speed clamp
  └─ render ───────── ORIGINAL full-res frames piped through ffmpeg; animated crop window
  │                   with adaptive zoom (1.02–1.40x) + gentle push-in; 1080×1920 output
  └─ validate ─────── every clip is audited: heuristics (black / flat / frozen frames) +
  │                   Gemini visually reviewing sampled frames (players visible? anyone cut
  │                   off? empty court?); failures re-render with a safe wide camera and are
  │                   dropped if still bad; the stitched reel gets a final heuristic sweep
  └─ coach ────────── Gemini Flash receives measured Runpod signals plus a few sampled
  │                   rally frames, then returns grounded coach notes: short strengths,
  │                   focus items, and caveats; low-confidence pose/racquet/shuttle
  │                   signals are called out instead of hallucinated into technique
  └─ stitch ───────── clips concatenated, court audio kept, procedural 120 BPM track
                      (accent every 2 s) mixed underneath, thumbnail extracted
```

Per-edit Gemini token usage and an estimated cost (rates configurable via
`GEMINI_IN_RATE`/`GEMINI_OUT_RATE`, $/1M tokens) are recorded in each result and
shown on gallery cards. POV/head-mounted footage is detected (global camera motion)
and rendered with a gentle centered camera instead of noise-chasing.

When the GPU worker reports a confident shuttle track (`SHUTTLE_MASK_MIN_QUALITY`,
default `0.65`), the final render draws a small tracked halo around the shuttle
after applying the same virtual camera transform. This keeps the overlay locked
to camera movement and avoids showing a mask for low-confidence tracks.

## Run locally

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
# .env needs GEMINI_API_KEY
.venv/bin/uvicorn app.main:app --port 8000          # web app on :8000
.venv/bin/python -m app.pipeline.run game.mov       # or run the pipeline directly
```

Optional Runpod GPU enrichment:

```bash
PUBLIC_BASE_URL=https://your-baddy-host.example
GPU_ARTIFACT_TOKEN=$(openssl rand -hex 32)
RUNPOD_ENDPOINT_ID=...
RUNPOD_API_KEY=...
COACH_ENABLED=1
COACH_MODEL=gemini-3.5-flash
COACH_FRAME_COUNT=4
COACH_FRAME_HEIGHT=360
```

See `docs/runpod-highlight-engine.md` for the worker input/output contract.
The containerized worker scaffold lives in `runpod_worker/`.

Once the Runpod endpoint exists, smoke it against the production contract:

```bash
./venv/bin/python scripts/runpod_smoke.py --job-id <app_job_id> --start 0 --end 8
```

## Deploy (GCP VM)

```bash
bash deploy/deploy.sh    # creates e2-standard-4 'baddy-agent' in us-central1-a if missing,
                         # pushes code, installs deps, (re)starts uvicorn (:8000) + Caddy
```

Live at **https://136-113-208-173.sslip.io** — Caddy terminates TLS (Let's Encrypt via the
sslip.io hostname, which resolves to the VM's IP); plain-IP HTTP requests 301 there.

## Analysis workers (per-job vision flags)

Every upload picks which vision workers run; only the selected ones execute. The
default is the free CPU motion camera. Flags (`app/config.normalize_options`):

| Worker | Option | Backend | Cost |
|---|---|---|---|
| Shuttle tracking | `shuttle: tracknetv3` | **Runpod serverless GPU** (`app/pipeline/gpu.py` → `runpod_worker/`) | ~$0.01–0.02/reel, scale-to-zero |
| Pose / players | `pose: yolo11` | **VM CPU in-process** (`app/pipeline/vision_local.py`) | free |
| Coach notes | `coach: true` | Gemini API | cents |
| (none) | defaults | CPU motion-centroid camera | free |

Routing lives in `app/pipeline/vision.py`: `shuttle=tracknetv3` goes to Runpod
(bundling pose if also selected, since the GPU box is already warm); `pose` alone
runs YOLO11 on the VM CPU (no GPU spin-up). The browser reads `/api/capabilities`
to enable/disable toggles based on what the deployment can run.

### Why this split (infra decision, ~10k INR VM + $10 Runpod)

- **TrackNetV3 on CPU is ~1 hour/reel** (measured ~0.5 fps) — unusable in-process.
- **A 24/7 GPU on GCP is ~$500/mo** — 5× the VM budget, and the work is *bursty*.
- **Runpod serverless GPU** bills per-second and scales to zero ($0 idle); at
  ~$0.01–0.02/reel the **$10 credit ≈ 500–1000 reels**, so shuttle tracking is
  **opt-in** to conserve it.
- Everything CPU-viable (rally detection, YOLO pose, motion camera, render, coach)
  stays on the always-on **e2-standard-4** (~8,100 INR/mo). No instance bump needed;
  committed-use e2-standard-8 (~10k INR) is the upgrade if parallel throughput is wanted.

The vendored TrackNetV3 (`vendor/TrackNetV3`, device-patched by
`scripts/patch_tracknet_device.py` to run on CUDA/MPS/CPU) also enables an on-device
shuttle fallback (`VISION_ALLOW_CPU_TRACKNET=1`), off by default because of the CPU cost.

## Shuttle tracking — research notes & upgrade path

The virtual camera currently follows a **motion-energy centroid** (frame differencing on
the static-camera proxy, pooled in 8×8 cells, robust median keyframes each second). This is
fast on CPU and looks like a human camera operator, but it tracks *the action*, not the
shuttle itself.

Researched options for true shuttle (x,y) tracking:

| Approach | Verdict |
|---|---|
| **TrackNetV3** ([qaz812345/TrackNetV3](https://github.com/qaz812345/TrackNetV3)) | ✅ Best upgrade. MIT license, public pretrained weights (TrackNet + InpaintNet), per-frame x,y CSV out of the box. ~25 fps on GPU, only 1–5 fps on CPU → needs a T4/L4 spot instance. |
| **WASB-SBDT** ([nttcom/WASB-SBDT](https://github.com/nttcom/WASB-SBDT)) | Strong accuracy, MIT, badminton weights in model zoo; more wiring (Hydra/research code). Plan B. |
| YOLO per-frame | ❌ No quality public shuttle weights; single-frame detectors lose the motion-blurred shuttle. |
| Gemini per-frame coords | ❌ Video input is sampled ~1 fps; tiny fast objects score poorly; cost/latency explode at 30 fps. Gemini is used where it shines: clip-level rally understanding. |
| Classical frame-diff + Kalman | ✅ Used as v1 "action centroid". Fine for framing, not for shuttle-precise coords. |

**Upgrade plan:** run TrackNetV3 on a GPU instance for the selected rallies only
(~25 fps ≈ real-time), feed shuttle x,y + visibility through the existing `FocusPath`
interface in `app/pipeline/track.py`, blended with the player centroid (shuttle leads the
frame, players keep it stable). Fine-tune on ~50–100 labeled amateur clips if needed.

## Roadmap
- [ ] Shot-type filters (smashes only, drop shots, jump smashes) via Gemini per-rally labels
- [x] TrackNetV3 shuttle tracking on the Runpod GPU worker
- [x] Experimental pose-guided racquet candidates for Gemini context
- [ ] Badminton racquet detector wired through `RACQUET_MODEL`
- [ ] Instagram DM intake + auto-story posting with tag
- [ ] User accounts; private reels
