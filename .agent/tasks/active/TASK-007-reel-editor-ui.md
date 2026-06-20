# TASK-007: Professional AI reel editor UI

**Status:** reasoning cleanup complete (Cycle 4, 2026-06-21)
**Branch:** `feat/TASK-007-reel-editor-ui`
**Base SHA:** `883786f`
**PRD section:** §8a reel editor UI + §16 remediation P1

## Goal
Turn the current Studio viewer into a professional editor for AI-generated
badminton reels. The editor should borrow the product anatomy of Remotion-style
video editors: preview canvas, layer rail, inspector controls, playback, and a
multi-lane timeline for rally cuts, shuttle overlays, pose overlays, and the
current soundtrack.

## Acceptance criteria
- [x] Studio opens into a desktop editor shell with top actions, left layers,
      central 9:16 canvas, right inspector, transport, and multi-lane timeline.
- [x] Editor has a serializable `baddy.editor.v1` state covering rally order,
      mirror, shuttle overlay style, and pose overlay style.
- [x] Shuttle FX controls include visible/style/size/opacity/trail options.
- [x] Pose controls include visible/style/line-width/opacity options.
- [x] Soundtrack appears only as read-only context until backend audio render
      props exist.
- [x] Current remix endpoint still works for rally order + mirror.
- [x] Public rally payload exposes bounded shuttle time-level samples for editor
      overlay preview without dumping the full internal vision payload.
- [x] Every remaining button/control has a written rationale; unbacked flows are
      removed from the UI.
- [x] `./scripts/check.sh` passes or any skip is documented.

## Verification commands
- `.venv/bin/python -m pytest tests/unit/test_public_editor_tracks.py -q`
- `node --check web/app.js`
- `./scripts/check.sh`
- browser visual check of `/` and Studio mode

## Risks / rollback
- Backend currently renders only rally order + mirror; overlay choices are stored
  locally and previewed in the UI until render support lands.
- Music choices were removed because they did not affect export yet.
- The public shuttle track is source-normalized; final reel-space coordinates
  need camera-path mapping in the backend revamp.
- rollback: `git switch feat/TASK-001-shuttle-follow-camera`
