# TASK-018: Pose model upgrade

**Status:** active
**Branch:** `feat/TASK-017-pose-camera-upgrades`
**Base SHA:** `251be38`
**PRD section:** §3 / §4a / §16 analysis-depth selection

## Goal
Decouple the public “pose on” option from the concrete YOLO model, default to a
stronger configurable pose model, and let pose-only jobs use RunPod when GPU-first
pose is configured.

## Acceptance criteria
- [ ] `pose: "yolo11"` remains accepted as the backward-compatible public option → config/unit smoke
- [ ] Local and RunPod loaders try configured upgraded pose models with old tiny model fallback → code review + tests/import checks
- [ ] Job/model metadata surfaces pose model, backend, device, and load status → `tests/unit/test_gpu_pose_contract.py`

## Plan
1. Add `POSE_BACKEND`, `POSE_MODEL_GPU`, `POSE_MODEL_LOCAL`, and fallback config.
2. Route pose-only jobs to RunPod when configured and fall back to local pose.
3. Report actual loaded model metadata in vision `models.pose`.

## Verification commands
- pending

## Risks / rollback
- YOLO26 weights may not load on the deployed image until `ultralytics` is current → fallback model remains configured.
- rollback: `git reset --hard 251be38`
