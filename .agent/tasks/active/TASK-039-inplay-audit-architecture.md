# TASK-039 — Rally-break audit, analysis.json export, architecture board

**Branch:** `feat/TASK-039-inplay-audit-architecture` (base `c8c9136`, atop TASK-035)
**PRD:** §16 remediation — TASK-039 (this), TASK-040 queued (in-play mask v1)
**Source:** user direction 2026-07-12 — audit rally-break detection, export a
machine-readable match report (rally times, markers, explicit no-play), start
audio-based highlight data, movement time series for heatmaps, keep the 2D→3D
interpolation layer iterable, and a baddyai.com/architecture board with a demo
runner that shows each model's output without re-running anything.

## Scope
1. **Audit** — `docs/reviews/2026-07-12-rally-break-inplay-audit.md`: how
   Gemini-only boundaries work today, why long rallies keep dead time, the
   in-play mask v1 design + eval gates (TASK-040).
2. **analysis.json** (`app/pipeline/analysis.py` + `GET /api/jobs/{id}/analysis`):
   play/no-play timeline, per-rally hits (impact + at-net speeds),
   shuttle-flight segments, audio peaks, per-player court-space movement
   series (ankles preferred, box-foot fallback). Built once from stored
   results, cached, invalidated on reprocess/court redraw.
3. **Audio groundwork** (`app/pipeline/audio.py`): RMS energy series +
   impact-like peak detection on the ambient proxy audio, stored per job.
4. **Raw model persistence**: `gemini_rallies_raw.json` + `vision_raw.json`
   written next to `result.json`; /media whitelisted.
5. **Architecture board** (`web/architecture.html`, `/architecture`):
   pipeline boxes with algorithms + top steps + audit gaps; interpolation
   layer marked as the isolated iterate-here module; demo runner (chunked
   upload or existing job id) with per-stage chips and per-model result
   panels (timeline bar, rallies table, vision metrics, shots+speeds, audio
   sparkline, court movement canvas, artifact links).

## Out of scope (queued)
TASK-040 in-play mask v1 + highlight score v2 (design in the audit doc);
box↔pose shared identity map (ankle-accurate movement); reprocess reusing
stored raws as a cache.

## Done means
check.sh green (140), real-artifact sanity recorded, deployed to
baddyai.com, /architecture + analysis endpoint verified live on a prod job.
Rollback: revert TASK-039 commits (no worker change).
