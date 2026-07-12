# TASK-042: Cycle-24 review batch — court player gate, action camera, audio rally veto

**Owner review (2026-07-12, job `1faaa5e4a02f`, doubles):**
1. Pose data extracted but not displayed by default — visible when selecting
   heat/velocity/minimal, invisible for Glow.
2. Final reel "very still — no camera movement, not even tracking the
   shuttle"; no shuttle highlight wanted in the reel.
3. Fake rally detections.
4. Adjacent-court players tracked again; owner proposal: "ask the user to
   mask the area in which they are playing… only track people inside that
   court, and use the Gemini API to differentiate."

## Root causes (from the job's real artifacts)
| Symptom | Root cause |
|---|---|
| Glow invisible | `.glow` landing-page blob CSS (fixed, blur 120px, opacity .16) captured the pose SVG's style class |
| Static reel | Z_MAX 1.40 + hard player+shuttle containment unzoomed to 1.0x on every far-half crossing |
| Background players | 39–48% of stored boxes on the LEFT court; evaluator kept 2 left-court ids; exact-id prune under id churn collapsed 4-player match to 1 box/frame |
| Fake rallies | Gemini tiled 18 windows over 91% of the video; audio shows 7–9.6s silent stretches inside them and 1-impact windows |

## Shipped
- `track.court_player_gate` + wiring in `gpu._frames_from` (fail-open; both
  backends; the Studio court-draw flow now powers player filtering too)
- `evaluate._prune_rally` IoU id-churn continuation + revert guard
- `track._action_zoom` constant per-rally court-aware zoom (≤2.25),
  blend-follow pan, `_contain_targets(shuttle_soft)`
- `config.REEL_SHUTTLE_MASK` default off
- `rally.refine_with_audio` (shrink/split/drop, fail-open) + impact peaks in
  the segmentation prompt; `audio.find_peaks` top_n 160
- Studio `ps-*` pose style classes; assets v=40 (app.js), style.css 35/28

## Verification
- 168 tests green; camera + gate + refine all replayed on the job's real
  `vision_raw.json` / proxy audio before deploy (numbers in dev-cycle-log).

## Queued next (recorded, not started)
- Far-player detection recall: worker YOLO misses far doubles players in
  half the frames (median 2 boxes/frame raw) — tiled/crop inference or
  higher imgsz on the worker (TASK-037 overlaps). arXiv 2508.13507 (doubles
  with singles-trained models) is prior art.
- Evaluator on CPU-fallback path (no track_ids → position-based prune).
- Post-vision shuttle in-play window trim (audio veto covers the bulk).
