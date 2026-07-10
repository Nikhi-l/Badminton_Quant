# TASK-033: Studio timeline redesign

**Status:** active
**Branch:** `feat/TASK-033-timeline-redesign` (stacked on feat/TASK-032-court3d-flow)
**Base SHA:** `8940927`
**PRD section:** §8a editor anatomy / §16 remediation (TASK-007/008/012/021 follow-on;
user report: timeline design needs improvement)

## Goal
The timeline had structural bugs dressed as design problems: the pose + soundtrack
lanes rendered into clipped invisible space (202px row vs 240px content — the entire
waveform feature was invisible while still fetching+decoding the reel), zoom 80–99 was
a dead range that desynced the playhead (%*scale math vs a block lane that can't
shrink), the ruler drew ~60 colliding labels on long sources, selection ringed every
segment in a lane, and every zoom tick rebuilt the DOM and re-seeked filmstrip frames.
Redesign: lanes fit the row (170px budget, dead lanes removed), pixel-space playhead
with edge-flip chip, 1x–6x zoom with cursor/playhead anchoring + pinch/ctrl-wheel,
adaptive ruler density, hover timecode ghost, per-segment selection, frame-step keys,
cached filmstrip upgrades, geometric lane icons + label polish.

## Acceptance criteria
- [x] All lanes visible at desktop (soundtrack 34/34px, pose 24/24px) → browser-verified
- [x] Zoom floor 1x, playhead pixel-exact at any zoom (1689px @ t=dur/2, 3x) → browser-verified
- [x] Zoom anchors the playhead (scrollLeft 1126 exact after 1x→3x) → browser-verified
- [x] Adaptive ruler ≥70px label spacing → tests/regression/test_timeline_redesign_js.py
- [x] Per-segment selection (1 ring, not per-lane) → browser-verified
- [x] Hover ghost shows/hides with timecode → browser-verified
- [x] Dead lanes gone in source mode (camera, Ambient) → structural test
- [x] ./scripts/check.sh green (102 tests)

## Plan
(see diff: web/app.js TRACK_META/tlScale/buildTimeline/studioTick/setTimelineZoom/
initTimelineHover, web/index.html timeline-tools + tlGhost, web/style.css studio rows
236px + timeline block + ghost/flip styles; assets v=34/v=35)

## Verification commands
- `./scripts/check.sh` → 102 passed
- Browser (preview pane vs live :8011 instance, viewport 1280x820): lane visibility,
  zoom/playhead/anchor px-exact checks, ghost + selection + source-mode lanes, court
  draw CTA pauses playback. Note: pane reports visibilityState=hidden so rAF never
  fires — ticks driven manually via studioTick() (known verification gotcha).

## Risks / rollback
- Concurrent session was editing web/ during this task; its work is preserved in
  commits 4bc82f7 + f5c65fd (not part of this task).
- rollback: `git reset --hard 8940927`
