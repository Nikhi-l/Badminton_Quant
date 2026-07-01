# TASK-019: Studio pose toggle and skeleton render

**Status:** active
**Branch:** `feat/TASK-017-pose-camera-upgrades`
**Base SHA:** `251be38`
**PRD section:** §8a / §16 TASK-011 + TASK-012 follow-up

## Goal
Make the Studio Pose layer a real on/off control for pose-layer visuals and render
actual skeletons from `pose_track` rather than keeping `currentPose()` as a null
stub.

## Acceptance criteria
- [ ] `currentPose()` reads nearest `pose_track` frame in Reel and Source modes → `tests/regression/test_studio_pose_overlay_js.py`
- [ ] Pose timeline toggle gates skeletons, player boxes, and source lane pose dots → `tests/regression/test_studio_pose_overlay_js.py`
- [ ] Frontend JavaScript parses cleanly → `node --check web/app.js`

## Plan
1. Implement pose lookup against source-time mapped `pose_track`.
2. Draw COCO-17 skeleton limbs/joints as an SVG overlay using existing framing mapping.
3. Gate source-mode Pose lane dots and counts with `overlays.pose.enabled`.

## Verification commands
- pending

## Risks / rollback
- Sparse pose tracks can flicker → nearest-frame window is tolerant and player boxes remain as fallback.
- rollback: `git reset --hard 251be38`
