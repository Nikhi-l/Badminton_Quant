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
  └─ tracking ─────── per-rally motion analysis on the proxy: flicker-masked motion cells →
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
  └─ stitch ───────── clips concatenated, court audio kept, procedural 120 BPM track
                      (accent every 2 s) mixed underneath, thumbnail extracted
```

Per-edit Gemini token usage and an estimated cost (rates configurable via
`GEMINI_IN_RATE`/`GEMINI_OUT_RATE`, $/1M tokens) are recorded in each result and
shown on gallery cards. POV/head-mounted footage is detected (global camera motion)
and rendered with a gentle centered camera instead of noise-chasing.

## Run locally

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
# .env needs GEMINI_API_KEY
.venv/bin/uvicorn app.main:app --port 8000          # web app on :8000
.venv/bin/python -m app.pipeline.run game.mov       # or run the pipeline directly
```

## Deploy (GCP VM)

```bash
bash deploy/deploy.sh    # creates e2-standard-4 'baddy-agent' in us-central1-a if missing,
                         # pushes code, installs deps, (re)starts uvicorn (:8000) + Caddy
```

Live at **https://136-113-208-173.sslip.io** — Caddy terminates TLS (Let's Encrypt via the
sslip.io hostname, which resolves to the VM's IP); plain-IP HTTP requests 301 there.

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
- [ ] TrackNetV3 shuttle-precise camera on GPU
- [ ] Instagram DM intake + auto-story posting with tag
- [ ] User accounts; private reels
