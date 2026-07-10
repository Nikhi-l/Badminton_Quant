# TASK-032: 3D environment mapping flow fixes

**Status:** active
**Branch:** `feat/TASK-032-court3d-flow` (stacked on feat/TASK-031-player-pose-tracking-v2)
**Base SHA:** `76fc19f`
**PRD section:** §16 remediation (follow-on to TASK-022/023/025/027; user report: 3D
environment mapping flow broken/confusing)

## Goal
The court→homography→rally3d→replay3d flow failed silently at every stage: a Hough quad
of ANY confidence was accepted as "ok" and drove heatmaps/3D with garbage geometry when
Gemini declined; every non-ok rally3d status was stripped from the payload so the Studio
could only say "no reconstruction"; POST /court discarded per-rally reasons and blocked
the whole FastAPI event loop for multi-second LM fits; the court-draw flow was
undiscoverable from the 3D empty state; the upload picker said "Court marked ✓" for
quads the server silently drops; and replay3d.js had four real bugs (mirrored_frame
ignored, stale-dims repaint memo, dead-code shot ribbon, 12 Hz stepping marionettes).

## Acceptance criteria
- [ ] Weak CV court → status "low_confidence", never drives 3D → tests/unit/test_court3d_flow.py
- [ ] Manual/Gemini courts carry a synthetic net from the homography → test_court3d_flow.py
- [ ] Non-ok rally_3d slim statuses flow to the public payload → test_court3d_flow.py
- [ ] POST /court returns rally_statuses and runs off the event loop (asyncio.to_thread)
- [ ] Studio: 3D empty state explains why + "Draw court corners" CTA; court layer shows
      provisional/uncertain states; upload picker warns on degenerate quads
- [ ] replay3d: mirrored_frame honored, resize-safe repaint, current-shot ribbon draws,
      30 Hz visual interpolation over the 12 Hz sim
- [ ] ./scripts/check.sh green

## Plan
1. court.py: ACCEPT_CONFIDENCE_FLOOR=0.35 → "low_confidence"; _net_from_homography;
   frame_wh recorded on results.
2. run.py: manual corners calibrated against SOURCE dims; failure notes; slim non-ok
   rally_3d on every rally.
3. main.py: _public_rally forwards slim statuses; POST /court off-thread + per-rally
   statuses kept on rallies and returned.
4. replay3d.js: sampleX(mirrored_frame), resize-before-memo, ribbon fix, 30 Hz repaint
   bucket, per-status empty message.
5. app.js: courtSub/courtRawOf/r3dWhyNot; 3D→court draw CTA; pause video on draw;
   per-rally outcome hint after recompute; client-side degenerate-quad warning.
6. Asset bump v=33/v=32.

## Verification commands
- `./scripts/check.sh` → 97 passed
- Browser: Studio court/3D inspectors + draw flow (preview pane)

## Risks / rollback
- Jobs whose court silently passed at conf <0.35 now show "uncertain — redraw corners"
  and lose (garbage) 3D until corners are drawn — intended behavior change.
- rollback: `git reset --hard 76fc19f`
