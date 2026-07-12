# TASK-041 — Upload-review batch: pose visibility, eval, court gate, trim button

**Branch:** `feat/TASK-041-review-batch` (base `f2b3f6e`, atop TASK-039/040v0)
**PRD:** §16 — owner upload review 2026-07-12 (job `adda60dbf93e`) + trim button.

## Diagnosis first (recorded)
- Pose data on the job is healthy (132 frames, q 0.79–0.83, ids match boxes);
  interp+render verified in node against the real payload (29 limbs drawn).
  Skeletons were only ever LIVE Studio overlays — nothing baked into pixels.
- "Top 3 rallies": TOP_RALLIES was already 5; MAX_REEL_SEC=59 was the binding
  cap (3 longest rallies + pads = 59s exactly).
- shuttle_quality 0.0 with 183 points = the honest metric flagging constant
  background-court re-locking (teleport penalty floor) — the geometry gap.

## Shipped
1. **annotated.mp4** (`annotate.py`): shuttle + players + pose baked into
   pixels at exact frame times from the STORED tracks (no live-render lag, no
   layer toggles); per-rally clips with ambient audio, concatenated.
   "Analysis video" button in the Studio. Drawing primitives shared with the
   evaluator so Gemini judges exactly what users see.
2. **Gemini frame evaluator** (`evaluate.py`, PRO_MODEL): 2 annotated frames
   from the best rally → {main_court_players, keep_track_ids, boxes_correct};
   prunes stored player/pose tracks (judged rally: exact ids; others: top-N
   persistent) BEFORE the camera plans. Fail-open on any implausible verdict.
3. **Background-shuttle court gate** (`track.court_shuttle_gate`): flight
   segments mostly outside the expanded court quad drop wholesale (a
   neighbouring court's rally passes every kinematic filter — only geometry
   separates courts). Runs at canonicalization for both backends.
4. **MAX_REEL_SEC 59→90** so TOP_RALLIES=5 actually fits real rallies.
5. **Trim dead time button**: POST/GET `/api/jobs/{id}/trim` — every DETECTED
   rally cut from the source chronologically (pads merged), background ffmpeg
   filter_complex trim+concat, audio with video-only fallback → trimmed.mp4.
6. **Frame-exact overlay clock**: requestVideoFrameCallback drives Studio
   overlays on the PRESENTED frame's mediaTime (rAF's currentTime ran a frame
   ahead — the "marker lags the shuttle" review item).

## Done means
147 tests green; deployed; owner job reprocessed and verified (evaluation
applied, shuttle quality recovered, annotated.mp4 + trim available).
