# TASK-012: Interactive / configurable timeline lanes

**Status:** active
**Branch:** `feat/TASK-012-interactive-timeline` (off `main`)
**PRD section:** §16 P1

## Goal
The Captions / Shuttle FX / Pose timeline lanes are display-only today ("what's the
use if they aren't editable?"). Make them do something, and in Source mode show the
shuttle track across the whole video timeline.

## Acceptance criteria
- [ ] Clicking a Shuttle / Pose lane (or a per-rally segment) **toggles** that
      overlay (updates `editorState.overlays.*.enabled`, the preview, and the layer
      rail) — the timeline is a control surface, not just a readout.
- [ ] Source rallies mode: the Shuttle lane shows the **shuttle track across the
      full source timeline** (continuous track, not only per-rally chips), so the
      user sees where the shuttle was tracked over the whole video.
- [ ] Captions lane: clarify its role (seek/label) or make labels editable; at
      minimum clicking a caption seeks the video (already partial).
- [ ] No dead controls remain (honor the "reasoned controls" rule).

## Plan
1. `buildTimeline()` — add click handlers per lane/segment that flip overlay enabled
   state and call `stateChanged()`.
2. Source mode shuttle lane: render the dense `shuttle_track` sampled across
   `source_duration` (a sparkline/heat strip), not just the rally segments.
3. Reflect lane on/off in the segment styling + layer rail.

## Verification commands
- `node --check web/app.js`; `./scripts/check.sh`; baddy-web preview (toggle from lane).

## Risks / rollback
- Dense source-track rendering perf on long videos → sample/bucket.
- rollback: `git restore web/`.
