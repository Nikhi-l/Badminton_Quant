# TASK-013: Landscape preview + manual reframe in Source rallies

**Status:** done (2026-06-21) — Portrait/Landscape preview toggle (landscape shows the source native aspect, full original frame); Framing crop/zoom/pan works in Source mode. Cache-bust bumped to v=18. Verified in preview.
**Branch:** `feat/TASK-013-landscape-source-framing` (off `main`)
**PRD section:** §16 P1

## Goal
The preview is only the 9:16 portrait crop. The user uploaded a **landscape** video
and wants to (a) view it in landscape (original 16:9) and (b) manually reframe in
**Source rallies** to choose which portions of the original landscape video to
highlight.

## Acceptance criteria
- [ ] A **Landscape ↔ Portrait** preview toggle in the canvas bar: Landscape shows
      the original source aspect (16:9) full frame; Portrait shows the 9:16 reel/crop.
- [ ] The Framing controls (Original/Crop, Zoom, Pan, drag, Reset — TASK-009) are
      available in **Source rallies** mode, applied to the source preview, so the
      user can pick highlight regions of the original landscape footage.
- [ ] Framing state is per-mode (reel vs source) where it makes sense; persisted.

## Plan
1. `.stage-frame` aspect is currently hard 9/16 — drive it from a `previewAspect`
   (9/16 | source `videoWidth/videoHeight`) toggle.
2. Ensure `framingState` + `applyFraming` + `videoFitPoint` work for the landscape
   stage (object-fit + transform already generalised in TASK-009).
3. Show the Framing layer/inspector in Source mode (currently reel-centric).

## Verification commands
- `node --check web/app.js`; `./scripts/check.sh`; baddy-web preview, both aspects.

## Risks / rollback
- Overlay alignment must follow the aspect change (videoFitPoint).
- rollback: `git restore web/`.
