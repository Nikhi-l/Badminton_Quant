#!/usr/bin/env python
"""Phase-0 bench runner (TASK-034): score stored results against labels.

Usage:
    .venv/bin/python scripts/bench/run_bench.py --manifest bench/manifest.json

Manifest format (see docs/benchmarks/PHASE0_BENCH.md):
    {"clips": [{"name": "clip01", "result": "data/outputs/<job>/result.json",
                "labels": "bench/labels/clip01.json"}]}

Per clip it scores every labelled rally and prints a release-gate table.
Exit code 1 when any gate fails — usable as a model-upgrade acceptance check.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from scripts.bench import metrics  # noqa: E402


def _rally_vision(result: dict, idx: int) -> dict:
    rallies = result.get("rallies") or []
    return (rallies[idx].get("vision") or {}) if idx < len(rallies) else {}


def score_clip(result: dict, labels: dict) -> dict:
    out: dict = {}
    fps = float(labels.get("fps", 30.0))
    for rl in labels.get("rallies") or []:
        idx = int(rl.get("rally", 0))
        vis = _rally_vision(result, idx)
        rally = (result.get("rallies") or [{}] * (idx + 1))[idx]
        row: dict = {}
        if rl.get("shuttle"):
            pred = vis.get("shuttle") or []
            row["shuttle"] = metrics.shuttle_f1(pred, rl["shuttle"], fps=fps)
            row["shuttle"]["teleports_per_1000"] = metrics.teleports_per_1000(pred, fps=fps)
        if rl.get("players"):
            pf = [{"t": f.get("t"), "boxes": [
                {"id": b.get("id"),
                 "x": (float(b["x1"]) + float(b["x2"])) / 2,
                 "y": (float(b["y1"]) + float(b["y2"])) / 2}
                for b in (f.get("boxes") or []) if "x1" in b]}
                for f in (vis.get("players") or []) if isinstance(f, dict)]
            row["players"] = metrics.player_count_metrics(pf, rl["players"])
            row["players"].update(metrics.id_switches(pf, rl["players"]))
        if rl.get("pose"):
            row["pose"] = metrics.pose_pck(vis.get("pose_track") or [], rl["pose"])
        r3 = rally.get("rally_3d")
        row["d3"] = metrics.d3_health(r3)
        if rl.get("shots3d"):
            row["d3"].update(metrics.d3_against_labels(r3, rl["shots3d"]))
        out[f"rally{idx}"] = row
    return out


def gate_report(scores: dict) -> tuple[list[str], bool]:
    g = metrics.RELEASE_GATES
    lines, ok = [], True

    def check(name: str, val, gate: float, higher_is_better: bool):
        nonlocal ok
        if val is None:
            lines.append(f"  {name:34s} —        (no labels)")
            return
        passed = (val >= gate) if higher_is_better else (val <= gate)
        ok = ok and passed
        lines.append(f"  {name:34s} {val:<8} gate {'≥' if higher_is_better else '≤'}{gate}"
                     f"  {'PASS' if passed else 'FAIL'}")

    for clip, rallies in scores.items():
        lines.append(f"{clip}:")
        for rname, row in rallies.items():
            lines.append(f" {rname}:")
            sh = row.get("shuttle") or {}
            check("shuttle_f1", sh.get("f1"), g["shuttle_f1"], True)
            check("shuttle_teleports_per_1000", sh.get("teleports_per_1000"),
                  g["shuttle_teleports_per_1000"], False)
            pl = row.get("players") or {}
            check("player_exact_count_frac", pl.get("exact_count_frac"),
                  g["player_exact_count_frac"], True)
            check("player_overcount_frac", pl.get("overcount_frac"),
                  g["player_overcount_frac"], False)
            check("player_id_switches_per_track", pl.get("switches_per_track"),
                  g["player_id_switches_per_track"], False)
            po = row.get("pose") or {}
            check("pose_pck05_near", po.get("near"), g["pose_pck05_near"], True)
            check("pose_pck05_far", po.get("far"), g["pose_pck05_far"], True)
            d3 = row.get("d3") or {}
            check("d3_below_floor_accepted", d3.get("below_floor_accepted"),
                  g["d3_below_floor_accepted"], False)
            check("d3_landing_median_m", d3.get("landing_median_m"),
                  g["d3_landing_median_m"], False)
            check("d3_speed_mape", d3.get("speed_mape"), g["d3_speed_mape"], False)
    return lines, ok


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", required=True)
    ap.add_argument("--json", action="store_true", help="emit raw scores as JSON")
    args = ap.parse_args()
    manifest = json.loads(Path(args.manifest).read_text())
    scores = {}
    for clip in manifest.get("clips") or []:
        result = json.loads(Path(clip["result"]).read_text())
        labels = json.loads(Path(clip["labels"]).read_text())
        scores[clip.get("name") or clip["labels"]] = score_clip(result, labels)
    if args.json:
        print(json.dumps(scores, indent=2))
        return 0
    lines, ok = gate_report(scores)
    print("\n".join(lines))
    print("\nRELEASE GATES:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
