# TASK-035 — Kalman-style shuttle confidence + radar-comparable shot speeds

**Branch:** `feat/TASK-035-kalman-shuttle-speed` (base `e7c4714`, on top of TASK-034)
**PRD:** PRIMARY_PRD remediation queue — honest tracking confidence / analytics
**Source:** learnings from a smartphone smash-speed paper (custom YOLOv5 +
constant-velocity Kalman tracking-by-detection, kinematic plausibility bounds,
radar-gun validation). Applied to the two items TASK-034 deferred: real
per-point shuttle confidence + provenance, and speed analytics users can
compare to numbers they know.

## Scope
1. **Measured shuttle confidence (`track.refine_shuttle_track`).** TrackNet
   exposes binary visibility; the stored flat 0.82 taught consumers nothing.
   Adapt the paper's composite scoring: constant-velocity prediction from the
   last accepted points, confidence falls with the innovation normalized by
   the local step scale (resolution/speed independent, like their W/4
   normalization); forward+backward passes so a false positive opening a
   segment can't poison the reference. Kinematic gates from the paper:
   static-run rejection (their <5 km/h reject → lights/net posts/floor-rest)
   and a hard max-speed gate (~500 km/h normalized; theirs 375). Stamp
   `provenance: "observed"`. Hooked once in `gpu._frames_from`, which BOTH the
   RunPod and CPU paths flow through (`vision.py → gpu._canonicalize`).
2. **Radar-comparable shot speeds (rally3d).** The paper's validation insight:
   peak-at-impact and at-net speeds differ by ~66 km/h MAE — a radar gun
   physically measures the decayed at-net value. `fit_shot` already reports
   `speed_kmh` (= |v0|, impact). Add `speed_at_net_kmh` at the net-plane
   crossing so users can sanity-check against radar/app numbers; surface both
   in the Studio 3D panel.
3. **Bench protocol additions.** Speed validation must compare AT-NET numbers
   against radar ground truth (peak is unmeasurable by radar); labelled clips
   must cover camera angles beyond broadcast (TrackNet's training domain).

## Out of scope
Kalman gap-fill (`provenance: predicted`) — needs a consumer story first;
InpaintNet A/B; TrackNet fine-tune (Phase 1 queue).

## Definition of done
- check.sh green; refinement + speed fields unit-tested; real-artifact sanity
  run recorded in the cycle log; VM deploy (no worker rebuild needed — app-side
  only); ledger + cycle log + PRD queue updated.
- Rollback: revert the TASK-035 commits (worker untouched).
