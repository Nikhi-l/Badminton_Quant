# TASK-011: Overlay correctness — phantom shuttle circle + real pose

**Status:** done (2026-06-21) — phantom shuttle marker hidden when untracked; fake pose skeleton removed (real pose deferred to TASK-015). Verified in preview.
**Branch:** `fix/TASK-011-overlay-correctness` (to be created off `main`)
**PRD section:** §16 P1 (bug)

## Goal
In the Studio preview a green shuttle ring appears at a fixed/last position even
when there is no tracked shuttle at the current playback time (the "weird circle
at random places"). And the Pose layer shows a static decorative figure, not real
keypoints ("I don't see any pose data"). Fix both.

## Acceptance criteria
- [ ] When `currentShuttlePoint()` is null at the current time, the shuttle marker
      is **hidden** (not drawn at the `{left:58, top:31}` default / last position).
- [ ] Pose overlay is **hidden** when there is no pose at the current time, and
      when present is driven by the real keypoints from `vision … poses/players`
      (not the hard-coded `.pose-figure` limbs).
- [ ] No phantom overlays in Reel or Source mode; verified in the preview.

## Plan
1. `web/app.js updateOverlayPreview()` — only push the shuttle mark when a point
   exists; drop the `{left:58, top:31}` fallback.
2. Pose: read keypoints from the rally vision (`poses`/`players`); position joints
   via `videoFitPoint` (already framing-aware). Hide when none.
3. Confirm the saved data carries pose keypoints (worker `tasks` includes pose);
   if only quality scores are exposed, extend `_public_rally` to surface keypoints.

## Verification commands
- `node --check web/app.js`; `./scripts/check.sh`
- baddy-web preview + mock reel: scrub to a no-shuttle frame → no marker.

## Risks / rollback
- Pose keypoints may not be in the public payload → may need a small API addition.
- rollback: `git restore web/app.js`.
