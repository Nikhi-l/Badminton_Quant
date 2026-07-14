# TASK-045 — Retro track hygiene: id coherence guard + sampler-time court gate

**Branch:** `feat/TASK-045-retro-track-hygiene` (stacked on `feat/TASK-044-tracking-foundations` @ dff2380; merge order 044 → 045)
**PRD:** §16 — owner-reported pose issue on job `713a86e5db5a` (2026-07-14);
extends the TASK-042 court gate and the TASK-034 tracker-rebirth remediation.

## Report

Owner screenshots (baddyai.com/#studio/713a86e5db5a, Prannoy vs Weng, SINGLES
broadcast): 4 tracked "players" (P2–P4 on line judges/staff, the actual far
player unboxed) and pose keypoints "juggling" between them.

## Diagnosis (from the job's stored data via the public API)

- Job created 2026-07-10 18:36 UTC, `worker_version: doubles-20260708` —
  BEFORE the 2026-07-11 tracker-persist fix, the 07-12 evaluator (`evaluation:
  null`), and the 07-13 court player gate deploy.
- Rebirth-era worker ids = confidence-rank aliases: public stable ids 1–3 each
  spanned x_range ≈ 0.63 with 31–49% physically impossible steps (real near
  player: 4%). "P2" = "2nd most confident detection this frame" — the juggling.
- 48% of stored boxes have feet outside even the 1.22-expanded quad (staff) —
  stored pre-gate, displayed forever.
- The far player WAS detected: after gating, 177/180 frames hold exactly the
  two players.
- One 73s wall-to-wall rally → 180-frame cap → 2.45 Hz sampling; `audio:
  not_analyzed` (job predates TASK-039) so the audio veto could not split it.

## Shipped

- `_ids_from_worker(worker_ids, frames=None)`: same-id steps checked against
  the `_stable_ids` motion gate; >15% implausible (min 10 steps) → return None
  → heuristic ids. Legacy call shape (no frames) unchanged.
- Court gate retro-applied at the public samplers (`corners` threaded from
  `result.court` via `_public_result`, `job_analysis`, `_movement_stats`):
  pre-TASK-042 jobs stop showing staff without a reprocess; idempotent for
  jobs gated at storage; fail-open preserved.
- `track.court_player_gate`: pose gating by bbox bottom (`_person_gate_foot`)
  — hallucinated ankles of board-cut spectators landed inside the quad; and
  pose-only calls now get min_keep_frac fail-open (basis = pose counts when
  no boxes are passed).
- Real-job fixture `tests/fixtures/job713_tracks.json` + 9 regressions.

## Not fixed here (by design)

- The stored reel/render of the job is baked; full repair = **Reprocess**
  (`POST /api/jobs/713a86e5db5a/retry?reprocess=1`): re-runs Gemini
  segmentation with audio (splits the 73s window), current worker (real
  BoT-SORT ids), evaluator, gates, camera. Requires the original upload still
  on the server.
- Far-player recall + singles cardinality remain TASK-036/037 + plan Slice B.
- 2.45 Hz cadence on long rallies → TASK-044 (worker rebuild pending).

## Verification

- `./scripts/check.sh` → 201 passed.
- `.venv/bin/python -m pytest tests/unit/test_retro_track_hygiene.py -q` → 9.
- Real-data replay: 690 boxes → 359; 44/45 frames exactly 2 players; pose and
  box gates agree; max per-id x-span 0.2 (was 0.63).

## Rollback

Revert the branch merge; no data migrations (display-layer only — stored
results untouched).
