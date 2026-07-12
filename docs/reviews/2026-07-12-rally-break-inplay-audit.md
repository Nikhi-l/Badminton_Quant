# Rally breaks & in-play detection — audit (2026-07-12, TASK-039)

User observation driving this: long "rallies" include dead time (shuttle
pickup, walking back, serve prep), and "longest rally = best highlight" is
an unvalidated assumption. This audits how boundaries are made today, what
signals we now store, and the design for our own in-play triggers.

## 1. How rally boundaries are decided today

One signal, one pass — Gemini watches the proxy video:

1. `rally.segment()` ([rally.py](../../app/pipeline/rally.py)) uploads the
   480p/12fps proxy to the Gemini Files API and asks for structured JSON:
   a rally STARTS at the serve strike, ENDS when the point is clearly over;
   "strictly exclude all dead time"; per-rally `intensity` 1–5 + 8-word note.
   Model ladder: `SEGMENT_MODEL` → `PRO_MODEL`.
2. `_clean()`: clamp to video, drop < `MIN_RALLY_SEC`, merge overlaps.
3. `select_for_reel()`: rank by `(dur, intensity)` desc, cap `TOP_RALLIES`
   and `MAX_REEL_SEC`. **This is the "longest = highlight" logic.**
4. Render pads each pick ±`PAD_BEFORE/PAD_AFTER`; a failed validation can
   TRIM a clip, but nothing ever splits play from no-play *inside* a rally.

## 2. What's solid / what's brittle

Solid: the prompt's rally definition is right; overlap-merge and min-length
are sane; intensity+note give a usable prior; model fallback works.

Brittle:
- **Whole-second, single-judge boundaries.** The prompt rounds to seconds
  and says "if unsure, widen by one second" — so boundaries are soft by
  design, and nothing cross-checks them against measured signals.
- **No in-rally dead-time removal.** If Gemini spans a stoppage (common on
  long "rallies" that are really two exchanges + a pickup), every second of
  it ships. Nothing downstream can currently disagree.
- **Highlight ranking is length+intensity only.** No hit density, no shot
  speed, no crowd/impact audio, no player effort.
- **Audio was discarded** (analysis-side): clips cut for vision are `-an`;
  the proxy kept AAC but nothing ever looked at it. Fixed in TASK-039 —
  see §3.

## 3. Signals we now store per job (TASK-034/035/039)

All of these live in `result.json` / `analysis.json` — no re-runs needed:

| Signal | Where | In-play meaning |
|---|---|---|
| Shuttle flight segments (gap-split, measured confidence) | `analysis.rallies[].markers.shuttle_flight` | a flying shuttle IS play — strongest single trigger |
| Audio energy series (0.25s) + impact peaks | `result.audio`, `analysis.audio` | hits/smashes are sharp transients; rest is quiet — works when vision can't see |
| Hit markers + speeds (impact & at-net) | `analysis.rallies[].markers.hits` | hit density ≈ exchange rate; speed ≈ spectacle |
| Player court-space movement series (ankle/foot → meters) | `analysis.rallies[].players_court_m` | in-play players hold court halves and move fast; pickups drift to corners/net |
| Camera-motion probe, rally intensity/notes | `result` | context/priors |

Known limitation: ankle-derived positions need the box↔pose shared identity
map (queued with match_type work) — today pose ids and box ids are labeled
independently, so movement falls back to box-foot (`src` field says which).

## 4. Design: in-play mask v1 (queued as TASK-040)

Deterministic fusion, evaluated before any model swap:

- Per 0.25s bin over each Gemini rally window (±2s margin), score:
  `S = w_f·flight + w_a·audio + w_k·kinetics` where
  `flight` = shuttle observed in bin (0/1, from flight segments),
  `audio` = impact peak within 0.5s (0/1) or normalized energy,
  `kinetics` = both players' court-speed above a walk threshold (~1.2 m/s).
- Hysteresis: play turns ON at S ≥ on-threshold, OFF after ~1.5s below the
  off-threshold (a hit's flight gap must not flap the mask).
- Outputs per rally: `in_play` sub-segments; boundary refinement = snap
  Gemini's start to the first serve impact (audio peak + flight start),
  end to last landing; long-rally splitting when the mask opens ≥3s.
- Consumers: render trims to the mask (keep the ±pad); highlight score v2:
  `dur_in_play × (hit_density + max_shot_speed_z + audio_prominence_z +
  intensity_prior)` replacing raw duration.
- Eval: label play/no-play spans on the Phase-0 bench clips
  (`docs/benchmarks/PHASE0_BENCH.md` gains a `play_spans` label);
  gate: mask IoU ≥ 0.85 vs labels, boundary MAE ≤ 0.5s before it can trim
  anything users see. The mask ships as analysis.json data FIRST, drives
  rendering only after passing the gate.

## 5. Shipped in TASK-039 (this audit's groundwork)

- `analysis.json` per job (built once, cached; `?refresh=1`): full
  play/no-play timeline (dead time is labelled, not implied), per-rally
  markers, movement series, audio block. `GET /api/jobs/{id}/analysis`.
- Ambient-audio energy + impact peaks stored for every new job
  ([audio.py](../../app/pipeline/audio.py)).
- Verbatim model outputs persisted: `gemini_rallies_raw.json`,
  `vision_raw.json` — model spend is never repeated to answer questions.
- `baddyai.com/architecture`: the live board (boxes, algorithms, gaps) with
  a demo runner that shows each stage's output for any job.

uservid3 ground truth for the numbers above: 336s source → 14 rallies,
56s play / 280s labelled no-play, 33 audio impact peaks, 3 hits + 3 flight
segments on the first reel rally.
