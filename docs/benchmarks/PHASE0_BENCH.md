# Phase-0 bench: labelled clips + release gates (TASK-034)

Model changes (Phase 1: player detector fine-tune, crop-based pose, TrackNet
overlap/InpaintNet A/B) are accepted against **numbers on frozen labelled
clips**, not eyeballing. This doc freezes the clip list shape, the label
formats, and the gates.

## 1. Clip set (to freeze — owner action)

Pick 6–10 clips covering: singles AND doubles, near AND far court emphasis,
tripod AND handheld, clean AND compressed uploads, at least one rally >45 s.
Process each through the normal pipeline once and keep the job's
`data/outputs/<job>/result.json` immutable (copy it into `bench/results/`).

`bench/manifest.json`:

```json
{"clips": [
  {"name": "clip01-singles-tripod",
   "result": "bench/results/clip01/result.json",
   "labels": "bench/labels/clip01.json"}
]}
```

## 2. Label formats (`bench/labels/<clip>.json`)

```json
{
  "fps": 30,
  "match_type": "singles",
  "rallies": [
    {
      "rally": 0,
      "shuttle":  [{"t": 12.633, "x": 0.512, "y": 0.401, "visible": true}],
      "players":  [{"t": 12.6, "boxes": [{"id": "near", "x": 0.31, "y": 0.72},
                                          {"id": "far",  "x": 0.55, "y": 0.33}]}],
      "pose":     [{"t": 12.6, "people": [{"bbox": {"x": 0.31, "y": 0.72, "h": 0.3},
                                            "keypoints": [{"x": 0.3, "y": 0.6}]}]}],
      "shots3d":  [{"t_hit": 13.2, "landing_xy_m": [2.1, 12.4], "speed_kmh": 95}]
    }
  ]
}
```

- Coordinates are source-frame normalized (same convention as the pipeline).
- `shuttle`: label every ~5th frame plus every frame around hits; frames where
  the shuttle is genuinely invisible get `"visible": false`.
- `players`: box centers are enough (matching is nearest-center); ids are any
  stable strings.
- `shots3d`: from tape measure / court lines on landings; speeds only where a
  radar or frame-count estimate exists — leave out otherwise.
- Every section is optional; missing sections report "no labels" instead of
  failing the gate.

## 3. Run

```
.venv/bin/python scripts/bench/run_bench.py --manifest bench/manifest.json
```

Exit code 1 when any gate fails — wire it into a model-upgrade checklist.

## 4. Release gates (2026-07-11 audit)

| Signal  | Gate |
|---------|------|
| Shuttle | F1 ≥ 0.87 within 10 px at 512×288; teleports ≤ 1 / 1000 visible frames |
| Players | exact count ≥ 90% of frames; overcount < 2%; ≤ 1 id switch / player / rally |
| Pose    | PCK@0.05 ≥ 85% near court; ≥ 70% far court |
| 3D      | zero below-floor accepted samples; landing median ≤ 0.35 m; speed MAPE ≤ 15% |

Metric definitions live in `scripts/bench/metrics.py` (unit-tested); gates in
`metrics.RELEASE_GATES`.
