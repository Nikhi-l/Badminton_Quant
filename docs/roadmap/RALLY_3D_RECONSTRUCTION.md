# Rally 3D reconstruction — plan (TASK-025)

Goal: a **toggleable "3D view" layer** in the Studio that replays a rally as a
3D simulation — court + net + player positions + shuttle trajectory (+ racket
line later) — reconstructed from ONE camera, in the spirit of the
smashspeed-style monocular reconstructions (Instagram reference from the
2026-07-07 review: TCN over TrackNet points + known court dimensions).

Constraints set in review:
- **Toggleable** — a Studio layer ("3D replay"), OFF by default; never replaces
  the video preview, renders beside/over it.
- **Low FPS** — the simulation runs at ~10–12 fps (matching the ≤10Hz vision
  sampling); no attempt to simulate at video rate. Playback interpolates
  visually (three.js lerp between sim states) but the SOLVER stays low-rate.
- Tracking correctness first: this builds strictly on the now-verified
  camera_path/track projection + `court.py` foundations (TASK-021/022).

## Already landed (foundations, TASK-022)
- `app/pipeline/court.py`: court boundary corners + net in normalized image
  coords, and an image→court-plane homography from the BWF dimensions
  (6.10m × 13.40m); attached per job as `result["court"]`; unit-tested.
- Player ground positions: `players_track` foot points (box bottom-center)
  projected through the homography — already powering 2D heatmaps.
- Interpolation systems for all tracks (shuttle, boxes, pose keypoints).

## Reconstruction pipeline (backend, per rally — offline, cached)
1. **Camera calibration from the court.** The homography fixes the ground
   plane. Recover full camera pose (K, R, t): assume square pixels + principal
   point at center; solve focal length from the homography (standard
   plane-based calibration — two constraints from r1⊥r2, |r1|=|r2|), then
   R, t by decomposition. Validate: reprojected court corners < 1% error.
   The net (known height 1.55m at posts, 1.524m center) gives a consistency
   check and refines focal length if visible.
2. **Shuttle 3D from the 2D track.** Each TrackNet point defines a camera ray.
   Between hits (detected as direction reversals / speed spikes in the 2D
   track), fit a ballistic-with-drag trajectory: state (p0, v0), dynamics
   `a = g − k|v|v` with badminton drag k ≈ 0.44 m⁻¹ (published shuttle CdA/m),
   minimizing ray-reprojection error over the segment (scipy least_squares,
   ~20 params/segment, runs in ms). Segment endpoints anchor near player
   positions (hit height prior 1.2–2.6m). Output: `shuttle_3d` samples
   [{t, x, y, z}] at 10Hz + per-segment fit residual as confidence.
3. **Players in 3D.** Phase 1: upright "marionettes" — feet on the court plane
   at the projected foot point, skeleton scaled to bbox height, keypoints
   mapped onto a billboarded plane (cheap, robust). Phase 2 (optional):
   monocular pose lift (VideoPose3D-style TCN or MotionBERT-lite on the GPU
   worker) for true 3D joints, root-anchored to the homography foot point.
4. **Racket line.** From wrist–elbow keypoints extended 0.65m (racket length)
   toward the shuttle at hit times; rendered as a 3D segment. True racket
   detection stays a separate worker task (racquet model already stubbed).
5. Persist as `result["rally_3d"]` (bounded ~20KB/rally), served with the full
   job payload only.

## Viewer (frontend)
- three.js scene (vendored, no build step): court plane with painted lines
  (exact BWF layout), net with posts, shuttle comet + trajectory ribbon,
  player marionettes, orbit camera with presets (broadcast / side / top).
- Sim clock at 10–12 fps decoupled from render rAF; visual lerp between
  states; replay controls reuse the Studio transport (play/pause/scrub/speed).
- Toggle lives in the layer rail ("3D replay"); opens as a split panel over
  the stage; heavy assets lazy-loaded on first toggle.

## Acceptance (fixture-first, like TASK-021/022)
- Synthetic fixture with a KNOWN 3D trajectory rendered to 2D via a known
  camera → reconstruction recovers apex height within 10% and landing point
  within 0.3m.
- Real rally: shuttle lands inside the court model when the 2D track says in;
  net crossings happen above net height; smash speed estimate within
  published amateur ranges (sanity band 80–250 km/h).

## Order of work
1. TASK-023: Gemini corner refinement fallback (court.py confidence < 0.5 →
   ask Gemini for the 4 corners on 3 sampled frames, structured output).
2. TASK-025a: camera pose recovery + `shuttle_3d` ballistic fit + fixture test.
3. TASK-025b: three.js viewer layer (court/net/shuttle/replay, low-fps sim).
4. TASK-025c: player marionettes + racket line; Phase-2 pose lift on GPU.
