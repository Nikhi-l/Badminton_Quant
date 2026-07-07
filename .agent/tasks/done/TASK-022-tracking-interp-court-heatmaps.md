# TASK-022: Track interpolation + court.py + Court overlay + movement heatmaps

**Status:** done (Cycle 13)
**Branch:** `fix/TASK-021-studio-review-fixes` (batched with TASK-021 per review)
**Base SHA:** `29af265`
**PRD section:** §16 remediation (review 2026-07-07: "overlay systems and
interpolation systems for the tracked things", "separate court.py", "post game
heat maps")

## Goal
Tracking-first polish on top of the TASK-021 projection fixes: (1) interpolate
all sampled tracks (shuttle points, player boxes per id, pose keypoints per
person) between the ≤10Hz public samples instead of nearest-sample snapping;
(2) `app/pipeline/court.py` detecting the court's boundary lines, corners, and
net plus a DLT homography to the 6.10×13.40m BWF court plane, stored on
`result["court"]`; (3) a Studio Court layer drawing the detected geometry
through the same projection as the tracks; (4) per-player post-game movement
heatmaps (court-plane when homography exists, camera-space fallback).

## Acceptance criteria
- [x] Marker error vs baked ground truth ≤0.5% at probe times in BOTH rallies
      of the fixture (interpolation kills the ±50ms snap) → browser probe
- [x] court.py detects axis-aligned + perspective synthetic courts, rejects
      no-court frames; homography maps corners/center correctly
      → `tests/unit/test_court.py` (4 tests)
- [x] Court overlay aligned in landscape, portrait-source, and portrait-reel
      (through the crop projection) → fixture verification
- [x] Heatmaps render one court schematic per tracked player with all-rally
      foot points → fixture verification (P1 138 pts, P2 138 pts)

## Verification commands
- `./scripts/check.sh` → 42 passed
- `.venv/bin/python scripts/make_studio_fixture.py` then browser probes
  (dot-vs-marker ≤0.41%, box centers exact, scrub 3.0→10.53→3.95)

## Risks / rollback
- Court detection is classical CV; low-confidence/occluded courts return
  `not_found` and the layer shows "not detected" (Gemini fallback = TASK-023).
- rollback: `git reset --hard 29af265`
