# TASK-001: Camera actively follows + centers the shuttle

**Status:** done (Cycle 1, 2026-06-20) — follows the shuttle horizontally, anchored
vertically; regression-tested (6 tests). On the soft proxy 3/5 rallies follow,
2/5 safe-fallback (hard source angle). See docs/dev-cycle-log.md Cycle 1.
**Status (orig):** active
**Branch:** `feat/TASK-001-shuttle-follow-camera`
**Base SHA:** `5f1c165`
**PRD section:** §16 remediation P0 (camera follows shuttle)

## Goal
In current clips the shuttle is tracked but the camera zoom/pan does not follow
it — `from_vision` centers on the player bounding box and only nudges toward the
shuttle within a band, so the camera tracks players, not the shuttle. Make the
**shuttle the primary follow target**: the camera pans/zooms to keep the shuttle
centered while still containing the nearest player.

## Acceptance criteria
- [ ] When shuttle data is present and confident, the camera center tracks the
      shuttle position over the rally (not the static player midpoint).
      → `tests/regression/test_camera_follows_shuttle.py`
- [ ] The nearest player remains contained (shuttle-follow does not abandon the
      player). → same test
- [ ] Camera path stays smooth (passes existing `validate.path_smoothness`).
      → test asserts acceleration percentiles within bounds
- [ ] Re-render of the user clip keeps the shuttle ring nearer frame center than
      before. → manual frame check

## Plan
1. Add a shuttle-follow term: bias the camera center toward the shuttle trajectory
   (interpolated across short gaps) with the player box as a containment
   constraint rather than the primary target.
2. Keep the existing smoothing solver so motion stays cinematic.
3. Add a regression test on `from_vision` geometry using a synthetic rally where
   the shuttle sweeps across the court — assert the camera center correlates with
   the shuttle x over time.

## Verification commands
- `.venv/bin/python -m pytest tests/regression/test_camera_follows_shuttle.py -q`
- re-render via `/tmp/rerender.py` (cached vision) + frame extraction check

## Risks / rollback
- Over-following a fast shuttle → jitter. Mitigation: smoothing solver + cap pull.
- rollback: `git reset --hard 5f1c165`
