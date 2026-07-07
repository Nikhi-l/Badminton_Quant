# TASK-025: 3D rally replay layer (toggleable, low-fps)

**Status:** done (a+b+c; real-footage sample pending a full-court video)
**Branch:** `feat/TASK-025-3d-rally-replay`
**Base SHA:** `d4d19d5`
**PRD section:** §16 remediation + `docs/roadmap/RALLY_3D_RECONSTRUCTION.md`
(full plan; review 2026-07-07: "make the 3d render toggleable, and keep it at
low fps since simulating at the same fps might not be feasible")

## Goal
Studio "3D replay" layer: court + net + player marionettes + reconstructed 3D
shuttle trajectory with replay controls. OFF by default; simulation clock at
10–12 fps (vision sample rate), decoupled from render rAF.

## Slices (each its own PR)
- **a. Reconstruction backend**: camera pose (K,R,t) from the TASK-022 court
  homography; per-segment ballistic-with-drag shuttle fit over TrackNet rays;
  `result["rally_3d"]` (bounded). Fixture with a KNOWN 3D trajectory → apex
  within 10%, landing within 0.3m.
- **b. Viewer**: vendored three.js scene (court/net/shuttle ribbon/orbit
  presets), transport-driven replay, lazy-loaded on first toggle.
- **c. Players + racket**: homography-anchored marionettes from pose_track;
  wrist-extended racket line at hit times; Phase-2 monocular pose lift on GPU.

## Acceptance criteria
- [x] Fixture reconstruction error bounds → tests/unit/test_rally3d.py (camera f within 3%, corner reproj <1px, apex within 10%, speed within 12%, landing within 0.3m, two-shot split, graceful degradation)
- [x] Toggle on/off leaves the classic preview untouched; sim clock 12 fps (repaint gated on sim bucket/camera/size)
- [ ] Real rally sanity on production footage (needs a full-court upload; uservid3 court not fully visible — honest not_found)

## Risks / rollback
- Monocular 3D is approximate; every rendered quantity carries the fit
  residual as a confidence and the layer is presentation-only (never feeds the
  render or camera). rollback: layer flag off.
