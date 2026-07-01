# TASK-020: Camera framing smoothing

**Status:** done (2026-06-26) — finished + hardened by the takeover session: deterministic pipeline-routing tests, yolo26 verified via build-time weight bake, shuttle false-detection filter, keep-in-frame containment, compose drag fix, comet trail, UI polish.
**Branch:** `feat/TASK-017-pose-camera-upgrades`
**Base SHA:** `251be38`
**PRD section:** §1 / §4 / §16 P0 camera follows shuttle

## Goal
Reduce visible zoom pops in shuttle-follow renders and allow strong TrackNet
shuttle evidence to drive POV/handheld clips instead of disabling the vision
camera wholesale.

## Acceptance criteria
- [ ] Opening render zoom punch is configurable and disabled by default → `tests/regression/test_camera_follows_shuttle.py`
- [ ] Strong `shuttle_quality` allows POV clips to use `from_vision` → `tests/regression/test_camera_follows_shuttle.py`
- [ ] Existing shuttle-follow smoothness regressions remain green → `tests/regression/test_camera_follows_shuttle.py`

## Plan
1. Replace hardcoded render push/punch values with config.
2. Default opening punch to zero and reduce the push-in.
3. Add a quality-gated helper for POV/handheld TrackNet shuttle-follow.

## Verification commands
- pending

## Risks / rollback
- POV clips with noisy TrackNet data could crop poorly → quality threshold defaults high at `0.65`.
- rollback: `git reset --hard 251be38`
