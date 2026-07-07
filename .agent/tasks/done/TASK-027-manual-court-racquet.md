# TASK-027: Manual court drawing + configurable racquet detection

**Status:** done
**Branch:** `feat/TASK-027-manual-court-racquet`
**Base SHA:** `c5dc143`
**PRD section:** §16 remediation (user request 2026-07-07: draw the court before
processing; racquet detection via YOLO/open model with a configurable pipeline)

## Goal
(1) Let users mark the court's four outer corners themselves — at upload time
(clicked on a client-side frame grab, riding along in `options.court_corners`)
and on EXISTING jobs (Studio Court inspector → guided draw mode →
`POST /api/jobs/{id}/court`), with the manual geometry treated as authoritative
(`court.source="manual"`, confidence 0.98) and each rally's 3D reconstruction
recomputed from the stored tracks. (2) A configurable racquet-detection chain in
the worker: custom `RACQUET_MODEL` weights → zero-training COCO
'tennis racket' fallback (small detect model, wrist-gated via pose to kill
crowd/floor false positives) → existing pose-guided line candidates; provenance
in `model_status.racquet_source`; measured boxes exposed as bounded
`racquet_track` and outlined in the Studio.

## Acceptance criteria
- [x] `options.court_corners` validated (4 in-frame pairs, non-degenerate) and
      authoritative in run.process → tests/unit/test_manual_court.py
- [x] `POST /api/jobs/{id}/court` recomputes court + rally_3d and persists to
      disk + DB; rejects bad corners/jobs → endpoint tests (ballistic seed)
- [x] Studio draw mode verified on REAL footage: uservid3 (undetectable court)
      → 4 clicks → "5 rallies reconstructed in 3D", court overlay + heatmaps +
      3D replay live; geometry quality tracks corner accuracy
- [x] Racquet chain configurable end-to-end: router requests the racquet task
      with pose; worker source custom|coco-tennis-racket; yolo11s baked;
      `racquet_track` bounded + Studio outline → sampler test
- [~] Image `racquet-20260707` (yolo11s baked) built + rolled out to template
      `ic265brof1`; endpoint healthy (ready 2/unhealthy 0). Measured-box sample
      on a real GPU job pending the next upload.

## Verification commands
- `./scripts/check.sh` → 65 passed
- Browser: Studio draw flow on uservid3 (screenshots in cycle log notes)

## Risks / rollback
- Manual corners trust the user; validation only rejects degenerate quads.
  Redrawing overwrites cleanly (idempotent endpoint).
- COCO fallback recall on badminton racquets is partial → TASK-028 fine-tune.
- rollback: `git reset --hard c5dc143`
