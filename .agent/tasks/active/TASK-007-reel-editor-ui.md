# TASK-007: Professional AI reel editor UI

**Status:** done in working tree (Cycle 2, 2026-06-20)
**Branch:** `feat/TASK-007-reel-editor-ui`
**Base SHA:** `883786f`
**PRD section:** §8a reel editor UI + §16 remediation P1

## Goal
Turn the current Studio viewer into a professional editor for AI-generated
badminton reels. The editor should borrow the product anatomy of Remotion-style
video editors: tool ribbon, preview canvas, layer rail, inspector controls, and a
multi-lane timeline for rally cuts, shuttle overlays, pose overlays, and music.

## Acceptance criteria
- [ ] Studio opens into a desktop editor shell with a top toolbar, left layers,
      central 9:16 canvas, right inspector, transport, and multi-lane timeline.
- [ ] Editor has a serializable `baddy.editor.v1` state covering rally order,
      mirror, shuttle overlay style, pose overlay style, and music choices.
- [ ] Shuttle FX controls include visible/style/size/opacity/trail options.
- [ ] Pose controls include visible/style/line-width/opacity options.
- [ ] Music controls include track, volume, and ducking options.
- [ ] Current remix endpoint still works for rally order + mirror.
- [ ] Public rally payload exposes bounded shuttle time-level samples for editor
      overlay preview without dumping the full internal vision payload.
- [ ] `./scripts/check.sh` passes or any skip is documented.

## Verification commands
- `.venv/bin/python -m pytest tests/unit/test_public_editor_tracks.py -q`
- `node --check web/app.js`
- `./scripts/check.sh`
- browser visual check of `/` and Studio mode

## Risks / rollback
- Backend currently renders only rally order + mirror; overlay/music choices are
  stored locally and previewed in the UI until render support lands.
- The public shuttle track is source-normalized; final reel-space coordinates
  need camera-path mapping in the backend revamp.
- rollback: `git switch feat/TASK-001-shuttle-follow-camera`
