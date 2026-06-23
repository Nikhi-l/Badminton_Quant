# TASK-014: Configurable virtual camera — targets + keyframes

**Status:** active (major, multi-cycle)
**Branch:** `feat/TASK-014-camera-keyframes` (off `main`; likely several task branches)
**PRD section:** §16 P0
**Depends on:** TASK-015 (player tracks for the "player" target); a backend render
contract that accepts a per-job camera plan.

## Goal
Give the user a configurable virtual camera in Studio instead of only the
auto-follow: choose what the camera tracks, and **keyframe** changes over time so it
can switch (e.g. shuttle → player) when the user wants. Builds on the existing
zoom + pan X/Y (TASK-009).

## Acceptance criteria
- [ ] **Target selector** per camera segment: `Track shuttle | Track player | Fixed
      point`. "Fixed point" = the user clicks a spot in the preview.
- [ ] **Keyframes** on the video timeline for the camera (target + zoom + pan +
      framing); the camera interpolates between keyframes; the user can add/move/
      delete keyframes and switch target at a keyframe.
- [ ] The preview reflects the keyframed camera during playback.
- [ ] **Export bakes the camera plan**: the backend render consumes the user's
      camera plan and renders the reel accordingly (extend `track.FocusPath` /
      `from_vision` to accept an authored plan; new `camera` block in the render
      request). Falls back to the auto camera when no plan.
- [ ] Camera plan persisted in `baddy.editor.v1` (`camera.keyframes[]`).

## Plan (slices)
1. Data model: `editorState.camera = { keyframes: [{t, target, x?, y?, zoom, pan}], default }`.
2. UI: target selector in the Framing/Camera inspector; keyframe markers on a camera
   timeline lane; click-to-set fixed point on the preview.
3. Preview: evaluate the camera plan at `currentTime` (interpolate) → drive
   `applyFraming` (or a dedicated camera transform) + the chosen target's position
   (shuttle point / player box centre / fixed point).
4. Backend render contract: `POST /api/jobs/{id}/remix` (or a new endpoint) accepts a
   `camera` plan; `run.py`/`track.py` build a `FocusPath` from it (sample target
   positions per frame, blend on keyframe target switches) and re-render. Reuse the
   existing smooth-path solver.

## Verification commands
- Unit: camera-plan → FocusPath sampling (target switch blends; keyframe interp).
- `./scripts/check.sh`; preview QA; an end-to-end re-render on baddyai.com.

## Risks / rollback
- Largest task — land in slices behind a flag; keep auto-camera as default.
- Target switches must blend (no teleport) — reuse the takeover-blend lesson.
- rollback: per-slice branch revert; auto camera unaffected.
