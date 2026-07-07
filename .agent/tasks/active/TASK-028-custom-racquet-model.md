# TASK-028: Custom badminton-racquet detection model

**Status:** queued
**Branch:** `feat/TASK-028-custom-racquet-model` (not started)
**Base SHA:** TBD
**PRD section:** §16 remediation (follow-up to TASK-027's configurable chain)

## Goal
Replace the COCO 'tennis racket' fallback with a fine-tuned badminton-racquet
detector. The pipeline is already pluggable — training + packaging is the whole
task: set `RACQUET_MODEL=/models/racquet/badminton-racquet.pt` in the worker
and everything downstream (provenance, racquet_track, Studio overlay) works
unchanged.

## Plan
1. Dataset: merge the public badminton-racket sets (Roboflow Universe hosts
   several thousand annotated frames across "badminton racket"/"racket
   detection" projects; verify licenses per set) + ~500 frames auto-mined from
   our own proxies (COCO fallback boxes at high confidence as weak labels,
   human-cleaned).
2. Train: ultralytics fine-tune of `yolo11s.pt` (single class `racquet`),
   640px, ~100 epochs; eval mAP50 target ≥0.75 on a held-out split of OUR
   footage (not just the public sets).
3. Package: bake weights into the worker image (`models/racquet/`), set
   `RACQUET_MODEL`; `model_status.racquet_source="custom"`.
4. Wire measured racquet boxes into rally3d's racket line (replace the
   wrist-extension heuristic when a box is present at hit time).

## Acceptance criteria
- [ ] mAP50 ≥ 0.75 on held-out own-footage frames; report in this file
- [ ] Real GPU job: racquet_quality > 0.4 with `racquet_source=custom`
- [ ] 3D replay racket line uses measured boxes when available

## Risks / rollback
- Weights bloat the image (~20MB) — acceptable; keep the COCO fallback env
  switch as instant rollback (`RACQUET_MODEL=""`).
