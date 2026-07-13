# TASK-044 — Tracking foundations: cadence + health telemetry + pose sanitizer

**Branch:** `feat/TASK-044-tracking-foundations` (base `c3a9ec1` on `main`)
**PRD:** remediation queue — the "worker sampling / 180-frame cap" row (P2), the
Phase-1 identity rows (TASK-036/037 groundwork), and the accepted plan
`docs/reviews/2026-07-14-tracking-pose-segmentation-plan.md` (Slices 0 + A).

## Why

Model quality and temporal tracking quality are separate problems. Before any
model swap (RF-DETR shadow, per-player crops) can be judged, the pipeline needs
(a) true 6 Hz cadence on long rallies instead of a silently degrading 180-frame
spread, (b) per-track health telemetry so A/B results are interpretable, and
(c) identity/kinematic rejection so a high-confidence keypoint teleport becomes
missing data instead of a smoothed-but-false glide.

## Scope (plan Slices 0 + A)

Slice 0 — measurement, cadence, health:
- worker `_sample_times`: keep ~6 Hz; the frame cap becomes a safety ceiling
  (default 1080 ≈ 3 min at 6 Hz, env `BADDY_MAX_FRAMES_PER_RALLY`); per-rally
  `sampling` metadata: requested/effective fps, frame counts, cap, degraded
  reason. Uniform spread only past the ceiling — explicit, never silent.
- canonicalization (`gpu.py`): surface worker `sampling` fail-open; add
  per-rally `track_health` (per worker track id: samples, span, coverage,
  longest gap, mean confidence; plus measured effective fps) for players and
  poses. Works against old workers (no sampling block → measured-only).
- `PUBLIC_TRACK_MAX_FRAMES` 180 → 1080 to match (public sampling must never
  decimate below the worker cadence — TASK-034 rule).

Slice A — identity + pose sanitizer:
- `_stable_ids`: similarly-sized slot reuse now requires a dt-scaled absolute
  distance gate (closes the cross-court id-inheritance hole).
- new `app/pipeline/sanitize.py`, run in `_sample_pose_track` after id
  assignment and BEFORE One-Euro:
  - whole-person displacement gate → same-id identity transition marks a new
    `seg` (segment) on the person; joints re-seed, nothing is deleted;
  - per-joint body-relative displacement/time gate (zero-velocity innovation;
    see plan §4.2 implementation note) — rejected joints get `confidence: 0`
    + `rejected: true` and do NOT update filter state; consecutive-rejection
    escape re-seeds after 3;
  - bone-surge check: a limb bone exceeding its rolling max length by 1.75×
    (≥3 prior observations) rejects the child joint (attachment error);
    foreshortening/re-extension never rejects;
  - joint groups: torso/head 3.0, elbow/knee 4.5, wrist/ankle 7.0
    body-heights/s + noise floor.
- `smooth.py`: One-Euro filter state keyed by (id, seg, joint) — smoothing
  never drags across an identity transition.
- Studio (`web/app.js`): pose interpolation maxGap 0.9 → 0.45s; interpolation
  never lerps a person across a `seg` change (handoff via the hold rule, same
  as relabeled ids).

## Out of scope (queued as PRD rows)

Slice B (burst windows, per-player crops, racquet microtracking), Slice C
(RF-DETR segmentation/keypoint shadow), Slice D (fused hit events, segmented
forward-backward smoothing, qualified analytics), Slice E (canonical-track
consumer rollout + shuttle provenance contract). Shared box↔pose identity map
remains TASK-036.

## Verification

- `./scripts/check.sh` (full suite)
- `.venv/bin/python -m pytest tests/unit/test_pose_sanitize.py
  tests/unit/test_worker_sampling.py tests/unit/test_gpu_track_health.py
  tests/unit/test_track_identity.py -q`
- worker cadence/payload note: handler changes require a worker image rebuild;
  until then the app reads old payloads fail-open. Rollback lever without an
  image rollback: endpoint env `BADDY_MAX_FRAMES_PER_RALLY=180`.
- before enabling on prod: RunPod smoke + fresh real upload; watch result.json
  and vision_raw.json sizes on a long-rally job (payload grows with cadence).

## Rollback

`git revert` the branch merge; worker env `BADDY_MAX_FRAMES_PER_RALLY=180`
restores the old sampling budget on a new-image worker.
