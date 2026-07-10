# TASK-031: Player + pose tracking v2

**Status:** active
**Branch:** `feat/TASK-031-player-pose-tracking-v2`
**Base SHA:** `0cae987`
**PRD section:** §16 remediation (follow-on to TASK-024/029/030 — "unify render-time
player identity" ledger follow-up; user report: player tracking + pose quality poor)

## Goal
Player tracking looks bad for three compounding reasons found in review: (1) hardcoded
phantom fallback boxes (conf 0.12) pass every downstream gate and steer the camera to
empty court; (2) the virtual camera ignores worker ByteTrack ids and re-derives identity
with a 2-slot nearest-centroid heuristic that never expires ghost slots, never
interpolates 6 Hz samples, and discards 2 of 4 doubles players; (3) ByteTrack runs on
6 Hz seeked frames with a stock 30 fps yaml and no appearance model, so overlapping
players swap ids. Pose is jittery because keypoints are never temporally smoothed.
Upgrade the model (yolo26m→l on GPU), tracker (BoT-SORT + native ReID tuned for 6 Hz),
identity plumbing (camera consumes track ids; softer worker-id acceptance; spatially
guarded fragment merge), and add One-Euro keypoint smoothing.

## Acceptance criteria
- [ ] No phantom player boxes in worker or local output → tests/unit/test_vision_no_phantoms.py
- [ ] Camera player tracks: track_id grouping, linear interpolation, ghost expiry → tests/unit/test_camera_player_tracks.py
- [ ] Court-polygon gating drops off-court detections, fail-safe when gate empties frame → tests/unit/test_worker_court_gate.py
- [ ] _ids_from_worker accepts ≥60% id coverage; fragment merge requires spatial continuity → tests/unit/test_track_identity.py
- [ ] pose_track keypoints One-Euro smoothed per person id → tests/unit/test_pose_smoothing.py
- [ ] GPU default model yolo26l-pose baked in image; BoT-SORT yaml shipped → Dockerfile/config asserts
- [ ] ./scripts/check.sh green

## Plan
1. runpod_worker/handler.py: drop phantom boxes; BoT-SORT tracker yaml (per-rally reset
   of sticky tracker error); court-corner gating before top-4 cap; racquet caps 2→4;
   yolo26l-pose default; WORKER_VERSION trackingv2-20260710.
2. runpod_worker/botsort_baddy.yaml + Dockerfile bake (yolo26l-pose.pt, COPY yaml).
3. app/config.py: POSE_MODEL_GPU default yolo26l-pose.pt.
4. gpu.py/vision.py/run.py: pass court corners into the worker payload; racquet caps 2→4.
5. vision_local.py: drop phantoms; top-2→top-4; court gating shared shape.
6. track.py: _player_tracks v2 (id-aware grouping, interpolation, expiry, near/far
   hysteresis) behind the existing [near, far] contract.
7. main.py: _ids_from_worker cliff 0.9→0.6; _relabel_merged spatial continuity guard;
   One-Euro smoothing on pose_track (new app/pipeline/smooth.py).
8. Tests + check.sh; docs cycle entry.

## Verification commands
- `./scripts/check.sh` → all tests green (was 73 collected before this task)

## Risks / rollback
- Worker changes need an image rebuild (`gcloud builds submit --config
  runpod_worker/cloudbuild.yaml runpod_worker/ --substitutions=_TAG=trackingv2-20260710`)
  + template patch + worker bounce; until then the old worker still answers with the
  old contract (fields are unchanged — additive only), and the app-side improvements
  (camera, ids, smoothing) apply to old results too.
- Removing phantom boxes lowers player_quality on undetectable footage → from_vision
  correctly falls back to motion camera (honest behavior, was hallucinated framing).
- rollback: `git reset --hard 0cae987`
