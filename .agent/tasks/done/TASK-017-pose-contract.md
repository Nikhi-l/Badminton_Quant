# TASK-017: Pose keypoint contract

**Status:** done (2026-06-26) — finished + hardened by the takeover session: deterministic pipeline-routing tests, yolo26 verified via build-time weight bake, shuttle false-detection filter, keep-in-frame containment, compose drag fix, comet trail, UI polish.
**Branch:** `feat/TASK-017-pose-camera-upgrades`
**Base SHA:** `251be38`
**PRD section:** §4a / §8a / §16 P1 overlay correctness + player tracking follow-up

## Goal
Preserve normalized pose keypoints from the local/RunPod vision workers through
canonical vision output and the public job payload so Studio can render real pose
skeletons instead of placeholder or box-only data.

## Acceptance criteria
- [ ] Canonical `baddy.vision.v1` rallies retain per-frame `poses[].people[].keypoints` → `tests/unit/test_gpu_pose_contract.py`
- [ ] Full job payload exposes bounded `vision.pose_track` with stable person ids → `tests/unit/test_public_editor_tracks.py`
- [ ] Gallery/list payloads stay lightweight and omit heavy per-rally tracks → `tests/unit/test_public_editor_tracks.py`

## Plan
1. Extend GPU canonicalization to keep pose people/keypoints plus bbox metadata.
2. Add public `pose_track` sampling alongside `shuttle_track` and `players_track`.
3. Thread canonical `poses` into rendered rally result objects.

## Verification commands
- pending

## Risks / rollback
- Larger full job payloads → bounded sampler and gallery-light omission.
- rollback: `git reset --hard 251be38`
