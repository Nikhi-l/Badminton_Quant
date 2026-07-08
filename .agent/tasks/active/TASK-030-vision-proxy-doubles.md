# TASK-030: Detect far doubles players (higher-res vision proxy)

**Status:** in verification (deployed; awaiting doubles reprocess)
**Branch:** `feat/TASK-030-vision-proxy-doubles` → merged `77ff9ce`
**Base SHA:** `9b09c37`
**PRD section:** §16 remediation (user report 2026-07-08: doubles game, only
1–2 players tracked)

## Root cause
Not the player cap (raised 2→4 in TASK-029). The GPU vision pass ran on the
480p analysis proxy; in a wide doubles shot the far players are ~20px tall —
below YOLO's detection floor. Proven locally on the actual proxy: even
conf=0.05 AND imgsz=1920 find only the near player (upscaling a 480p frame
can't recover detail that isn't there).

## Fix (VM-only + template env; no worker rebuild)
- `VISION_PROXY_HEIGHT` (default 1080); run.process builds a separate
  `vision_proxy.mp4` from the source (capped to source height, never upscaled)
  for the pose+shuttle pass; Gemini/rally/motion/court stay on the 480p proxy.
- `gpu.analyze` uploads whichever proxy the caller passes (signed GPU
  artifact); falls back to `proxy.mp4` if the vision proxy wasn't built
  (short/low-res source) — safe on every source resolution.
- RunPod template env `YOLO_IMGSZ=1280`, `YOLO_CONF=0.15` (no rebuild; worker
  reads os.environ). Workers bounced to pick it up.

## Acceptance criteria
- [x] 3 unit tests (artifact whitelist+config, proxy selection, 480p fallback)
- [x] VM deployed (v=32 unchanged; backend only) + template env patched + bounced
- [ ] Doubles job 7a4d98f2da22 reprocess shows >2 players on the far-net rallies
      (record max_people/frame here)

## Risks / rollback
- 1080p vision proxy adds proxy-encode time + a larger GPU download; TrackNet
  also runs on it (also benefits). `VISION_PROXY_HEIGHT=480` env disables it.
- rollback: `git reset --hard 9b09c37`; template env removed.
