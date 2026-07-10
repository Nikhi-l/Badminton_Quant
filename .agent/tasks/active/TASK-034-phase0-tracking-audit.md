# TASK-034 — Phase 0 tracking-audit fixes (deterministic pipeline bugs)

**Branch:** `fix/TASK-034-phase0-tracking-audit` (base `bfb2152`, on top of TASK-033)
**PRD:** PRIMARY_PRD remediation queue — tracking correctness / honest quality
**Source:** 2026-07-11 codebase audit (Phase 0 slice). Findings verified against
the checkout before any change; the Ultralytics claim was verified against the
installed 8.4.70 sources.

## Scope (Phase 0 only — no model swaps)
1. **Worker tracker lifecycle (P0).** `model.track()` registers its tracking
   callbacks once, on the FIRST call, permanently capturing that call's
   `persist` value (`engine/model.py:573`, `trackers/track.py:44→partial`).
   The handler's first call passes `persist=False` (rally reset), so every
   subsequent predict rebuilds the tracker → fresh ids every sampled frame.
   Fix: `persist=True` always + explicit `tracker.reset()` at rally starts.
   Pin `ultralytics==8.4.70`. Align `new_track_thresh` with the deployed
   detector floor (`YOLO_CONF=0.12`).
2. **Honest shuttle quality (P0).** Worker quality was coverage×0.82. Add
   longest-gap + teleport penalties; expose the components.
3. **Public shuttle track contract (P0).** Replace whole-rally uniform
   decimation (180-point cap → 0.4s spacing on long rallies → Studio draws no
   trail, marker flickers) with gap-preserving per-segment resampling at
   12.5Hz; emitted spacing stays under Studio's 0.35s dropout threshold.
4. **Studio interpolation (P0).** Stop unioning unmatched old+new ids
   (2 players → 4 boxes); hold a vanished id ≤0.3s then drop; remove the extra
   140ms wall-clock box smoother (lag + fabricated motion during dropouts);
   align pose display gate with the smoother gate (0.15).
5. **One canonical shuttle track (P0).** Camera already filters; make the
   baked-MP4 marker (render.py) and 3D solver (rally3d.py) consume the same
   `filter_shuttle_points` output instead of raw points.
6. **3D physical gates (P0).** Reject fits with below-floor samples,
   off-court trajectories, low net crossings, implausible contact heights or
   speeds; tighten solver bounds + residual acceptance; adjacent-shot
   continuity prune; new `implausible` status + Studio copy; label the layer
   2.5D (billboards, not measured pose).
7. **Bench scaffolding.** Labelled-clip manifest format + pure metric
   functions (shuttle F1/teleports, player count/ID switches, 3D gates) +
   release-gate thresholds from the audit; runner script.

## Out of scope (queued for Phase 1 in the PRD)
match_type singles|doubles contract, per-player crop pose, TrackNet
overlap/InpaintNet A/B, raising the worker 180-frame sampling cap, real
heatmap confidence + observed|inpainted provenance, per-segment camera
calibration.

## Definition of done
- `./scripts/check.sh` green; every fix has a regression test that fails on
  the old behavior.
- Cycle-log entry (Cycle 19) + progress-ledger row + PRD queue update.
- Worker rebuild flagged as REQUIRED (handler/yaml/requirements changed):
  suggested tag `phase0-20260711`. Not deployed by this task.
- Rollback: `git revert` of the TASK-034 commits; worker rollback = previous
  image tag (`doubles-20260708` template state).
