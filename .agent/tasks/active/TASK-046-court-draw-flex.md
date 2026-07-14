# TASK-046 — Court drawing: out-of-frame corners + frame scrubbing

**Branch:** `feat/TASK-046-court-draw-flex` (stacked on 045 @ 3c0384d; merge
order 044 → 045 → 046)
**PRD:** §16 TASK-046 row (owner request 2026-07-14).

## Why

Owner-reported gaps in the manual court flow (TASK-027):
1. A side-angle camera cuts court endpoints off-image — the pickers clamped
   corners to 0..1, so those courts could never be marked accurately.
2. The upload picker grabbed ONE fixed frame (25% mark); if a player blocks
   the court there (happened to the owner), you were stuck.

## Shipped

- `config.court_corners_option`: corners accepted in **[-0.75, 1.75]** (was
  ±0.05 slack). The homography and every court gate are plane geometry — an
  extrapolated corner is exactly as usable as an in-frame one. Degenerate-span
  rejection unchanged.
- Upload picker (`web/index.html` + `app.js`):
  - the frame is drawn inside a dark **margin** (14% of the canvas per side,
    dashed frame outline, "outside camera" label) and margin clicks record
    normalized coords past 0..1 — no clamp;
  - a **frame scrubber** (0.1s steps + time label) re-seeks the kept-alive
    client-side video, so a blocked court is one drag away; corners survive a
    frame change (the court doesn't move).
- Studio draw mode (`app.js`):
  - drawing zooms the stage video out to **0.72** so the same dark margin
    exists; `videoFitPoint` was already zoom-aware, and `courtDrawClick` now
    inverts the scale-about-centre before the contain box (round-trip vs the
    forward mapping verified exact to 2e-16);
  - framing restores to zoom 1 when drawing ends/cancels;
  - hints tell the user to scrub to a clear frame first (drawing pauses the
    video; the timeline still seeks while paused).
- Asset bumps: `app.js?v=41`, `style.css?v=36`.

## Verification

- `./scripts/check.sh` → 209 passed (+8: `test_court_corner_extrapolation.py`
  — option bounds, options round-trip, manual_result homography on
  extrapolated corners projecting onto the exact court rectangle,
  court_player_gate with an off-frame quad, worker `_court_polygon`
  acceptance, in-frame behavior pinned).
- Browser (static preview): drove the REAL upload-picker click handler with a
  synthetic video — out-of-frame corners recorded unclamped
  (x=1.129, x=-0.121), validity + `currentOptions().court_corners` wiring
  intact, scrubber sought 7.5s and updated the label.
- `node --check web/app.js` OK; Studio inversion round-trip 2.2e-16.

## Rollback

Revert the merge; corners already stored in old jobs are all in-frame and
remain valid under the widened bounds.
