# TASK-015: Person / player tracking

**Status:** active
**Branch:** `feat/TASK-015-player-tracking` (off `main`)
**PRD section:** §16 P1
**Feeds:** TASK-014 (the "track player" camera target), TASK-011/012 (pose/overlay).

## Goal
Detect and track players across frames so the camera can follow a chosen player and
the editor can show player/pose data. YOLO11 pose already detects player boxes +
keypoints per sampled frame; add per-player identity/tracking and surface it.

## Acceptance criteria
- [ ] Per-rally **player tracks**: stable player ids across frames (near/far or
      left/right), each with a box + keypoints over time. (`vision_local` /
      worker already emit `players`/`poses`; add a light tracker for identity.)
- [ ] Player tracks exposed via the public job payload (like `shuttle_track`) so the
      editor can render them and the camera can target them.
- [ ] A **Players** timeline lane / overlay; pose overlay driven by real keypoints
      (with TASK-011).
- [ ] A player is selectable as a camera follow-target (consumed by TASK-014).

## Plan
1. Tracker: associate per-frame player boxes into tracks (nearest-continuity, like
   `track._two_player_tracks`); assign ids; keep keypoints per track.
2. Persist tracks in `result.json` `rallies[].vision.players` (already partly there);
   add a bounded public `players_track` in `_public_rally`.
3. UI: Players lane + overlay; selection wiring for TASK-014.

## Verification commands
- Unit: box-association tracker (ids stable across a synthetic sequence).
- `./scripts/check.sh`; preview shows player tracks/overlay.

## Risks / rollback
- Identity swaps on occlusion → hysteresis (reuse SWITCH_RATIO lesson).
- rollback: additive; auto camera + existing overlays unaffected.
