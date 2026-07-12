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
| Player court-space movement series (ankle/foot → meters) | `analysis.rallies[].players_court_m` | in-play players hold court halves and move fast; pickups drift to corners/net — this is the top-down 2D court mapping |
| Per-player wrist series (COCO 9/10, image coords) | `analysis.rallies[].wrists` | the raw signal for stroke/hit detection: wrist-speed spike + shuttle turn + audio impact = a hit |
| Shuttle in-play index (speed-gated flight segments) | `analysis.rallies[].in_play` + `markers.shuttle_flight[].{median_speed,in_play}` | the owner-spec index: airborne AND fast = play; carried/slow = not play |
| Camera-motion probe, rally intensity/notes | `result` | context/priors |

Full pose data was already persisted (`result` rallies keep per-frame
keypoints; `pose_track` is the id-stable public form) — what was missing was
wrists and the in-play index as first-class exported signals; both now are.

Known limitation: ankle-derived positions need the box↔pose shared identity
map (queued with match_type work) — today pose ids and box ids are labeled
independently, so movement falls back to box-foot (`src` field says which).

## 4. Design: in-play index + mask (TASK-040) — revised per owner review

Owner review (2026-07-12) reshaped the priority order: the **shuttle's own
kinematics ARE the in-play index** — "the shuttle should be moving fast, and
it should not touch the court". Audio and player kinetics are corroborators,
not peers. And Gemini must not grade its own homework: extract the
time-series first, then hand it to Gemini WITH the video to confirm and
reason — signals first, model second.

**v0 — shipped with this revision (data only).** `analysis.json` flight
segments now carry `median_speed`/`max_speed` (normalized-frame units/s) and
an `in_play` verdict: airborne AND median speed ≥ 0.15/s (≈2 m/s — above
carried-in-hand drift, below any stroke) AND ≥ 0.4s long (a blip is not an
exchange). Stationary shuttles never reach here (the tracking layer's
static-run gate removes floor-resting/light false positives). Each rally
exposes the resulting `in_play` spans. Known limit: normalized speed is a
2D image quantity — accurate m/s lives in the 3D layer; the threshold is
deliberately far from both classes so the unit choice doesn't matter.

**v1 — corroborated mask.** Per 0.25s bin: shuttle in-play index (primary)
OR-gated with audio impact within 0.5s and both-players court-speed above a
walk threshold (~1.2 m/s) to bridge TrackNet dropouts mid-exchange;
hysteresis (~1.5s) so a hit's brief occlusion doesn't flap the mask.
Boundary refinement: snap rally start to first serve impact (audio peak +
flight start), end to last landing; split a "rally" where the mask closes
≥3s (that was two exchanges + a pickup).

**v2 — signals→Gemini verification (owner direction).** Instead of asking
Gemini to find rallies cold, pass the video PLUS a compact digest (in-play
spans, audio peak times, hit markers with speeds, per-player movement) and
ask it to confirm/adjust boundaries and REASON about which rallies are the
top highlights from all signals. Gemini becomes the cross-checking judge of
measured data, not the sole eyewitness.

- Highlight score v2 (alongside v2): `dur_in_play × (hit_density +
  max_shot_speed_z + audio_prominence_z + intensity_prior)` replacing raw
  duration.
- Eval: label `play_spans` on the Phase-0 bench clips; gate mask IoU ≥ 0.85,
  boundary MAE ≤ 0.5s before anything is trimmed from a render. The index
  ships as analysis data first (done), drives rendering only after the gate.

## 4b. Canonical camera assumption (owner, 2026-07-12)

Deployment rig: one camera **behind the players, ~10 ft high, whole court
visible** (possibly tilted). That is close to TrackNetV3's broadcast training
domain (good), and it is exactly the geometry our interpolation layer is
built for: mark/detect the court once, homography + plane calibration give
the top-down 2D court mapping (`players_court_m` already plots it) and the
3D shuttle solver. Multi-view and per-segment calibration stay future work
(`docs/roadmap/FUTURE_VISION.md`).

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
