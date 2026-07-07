# TASK-021: Studio review fixes — portrait overlays, timeline scrub, pose skeleton, stable player ids

**Status:** done (Cycle 13; verified against ground-truth fixture)
**Branch:** `fix/TASK-021-studio-review-fixes`
**Base SHA:** `29af265`
**PRD section:** §Studio editor / remediation (baddyai.com review 2026-07-07)

## Goal
Fix the four defects found reviewing baddyai.com: (1) tracking overlays (shuttle
dot, player boxes, pose) align in Landscape but shift in Portrait — the reel is a
virtual-camera crop and the Studio maps source-normalized coordinates onto it as
if it were the source frame, and the reel→source time base ignores clip padding
(PAD_BEFORE=1.0s) and stitch crossfade drift (0.45s/boundary); (2) dragging on
the timeline pans the canvas instead of scrubbing (no drag-to-scrub; seek math
uses the wrong rect; canvas can visually cover the transport); (3) pose renders
as giant distorted blobs — the overlay SVG uses a 0-100 viewBox with
`preserveAspectRatio="none"`, so joint circles stretch to ~3% of frame width;
(4) only "P1" ever appears — the worker's confidence sort breaks pose/box
pairing, and the API's greedy id assignment churns ids on fast motion
(unbounded `next_id++` past a 0.22 gate).

## Acceptance criteria
- [x] Renderer exports the actual per-frame crop rect; result carries
      `camera_path` + `render_window` per rally and the stitch xfade
      → `tests/unit/test_render_camera_path.py`
- [x] Remix (mirror/camera re-render) refreshes each re-rendered rally's
      camera_path → covered by crop-rect helper test + code path review
- [x] Player/pose track ids stay in {0,1} for a fast-moving 2-player rally
      (no id churn) → `tests/unit/test_public_editor_tracks.py`
- [x] Studio maps overlays correctly on: landscape+proxy (source time),
      portrait+source (letterboxed), portrait+reel (crop projection);
      hides overlays with a hint on legacy jobs without camera_path
      → manual verification via local preview (fixture job)
- [x] Timeline supports drag-to-scrub; transport/timeline always win pointer
      events over the canvas
- [x] Pose skeleton renders undistorted in both aspects, one color per player,
      four styles (glow/minimal/heat/velocity)

## Plan
1. Backend: render.py crop-rect helper + camera samples; run.py attach + remix
   refresh; main.py expose (full result only, bounded size).
2. Backend: slot-based id tracker for players_track/pose_track; worker pairing fix.
3. Frontend: displayed-video-aware mapping + xfade-aware segments + projection;
   timeline scrub; pixel-space pose SVG.
4. Tests + local preview verification with a synthetic fixture job.

## Verification commands
- `./scripts/check.sh` → all tests pass
- `uvicorn app.main:app` + browser preview on a fixture job → screenshots in PR

## Risks / rollback
- Old jobs lack camera_path → overlays hidden (with hint) in portrait reel view
  instead of rendering wrong; landscape/source views unaffected.
- rollback: `git reset --hard 29af265`
