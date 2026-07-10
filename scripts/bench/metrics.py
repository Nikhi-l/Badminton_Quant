"""Phase-0 bench metrics (TASK-034): pure functions from predictions + labels.

These encode the audit's release gates so model changes (Phase 1) are judged
against numbers, not vibes. Everything is dependency-light (numpy only) and
unit-tested in tests/unit/test_bench_metrics.py. Label formats are documented
in docs/benchmarks/PHASE0_BENCH.md.

Release gates (from the 2026-07-11 audit):
  Shuttle  — F1 ≥ 0.87 within 10 px at 512×288; teleports ≤ 1 per 1000 visible frames
  Players  — exact count ≥ 90% of frames; overcount < 2%; ≤ 1 id switch/player/rally
  Pose     — PCK@0.05 ≥ 85% near court, ≥ 70% far court
  3D       — zero below-floor accepted samples; landing median ≤ 0.35 m; speed MAPE ≤ 15%
"""
from __future__ import annotations

import math

RELEASE_GATES = {
    "shuttle_f1": 0.87,
    "shuttle_teleports_per_1000": 1.0,
    "player_exact_count_frac": 0.90,
    "player_overcount_frac": 0.02,
    "player_id_switches_per_track": 1.0,
    "pose_pck05_near": 0.85,
    "pose_pck05_far": 0.70,
    "d3_below_floor_accepted": 0.0,
    "d3_landing_median_m": 0.35,
    "d3_speed_mape": 0.15,
}


def _pairs_by_time(pred: list[dict], gt: list[dict], tol_s: float):
    """Greedy 1-1 matching of two time-stamped lists (both sorted by t)."""
    pred = sorted(pred, key=lambda p: float(p["t"]))
    gt = sorted(gt, key=lambda p: float(p["t"]))
    pairs = []
    used: set[int] = set()
    for g in gt:
        best, best_dt = None, tol_s
        for i, p in enumerate(pred):
            if i in used:
                continue
            dt = abs(float(p["t"]) - float(g["t"]))
            if dt <= best_dt:
                best, best_dt = i, dt
            elif float(p["t"]) > float(g["t"]) + tol_s:
                break
        if best is not None:
            used.add(best)
            pairs.append((pred[best], g))
    return pairs, len(pred), len(gt)


def shuttle_f1(pred: list[dict], gt: list[dict], tol_px: float = 10.0,
               wh: tuple[int, int] = (512, 288), fps: float = 30.0) -> dict:
    """Precision/recall/F1 of shuttle localization against labelled points.

    ``gt`` entries with visible=False count as frames the model must NOT
    localize on (a prediction there is a false positive)."""
    visible = [g for g in gt if g.get("visible", True)]
    pairs, n_pred, _ = _pairs_by_time(pred, visible, tol_s=0.5 / max(fps, 1.0))
    tp = 0
    for p, g in pairs:
        dx = (float(p["x"]) - float(g["x"])) * wh[0]
        dy = (float(p["y"]) - float(g["y"])) * wh[1]
        if math.hypot(dx, dy) <= tol_px:
            tp += 1
    precision = tp / n_pred if n_pred else 0.0
    recall = tp / len(visible) if visible else 0.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0
    return {"precision": round(precision, 4), "recall": round(recall, 4),
            "f1": round(f1, 4), "tp": tp, "n_pred": n_pred, "n_visible": len(visible)}


def teleports_per_1000(points: list[dict], fps: float = 30.0,
                       jump_norm: float = 0.22) -> float:
    """Physically impossible jumps per 1000 visible frames (audit gate ≤1)."""
    pts = sorted(points, key=lambda p: float(p["t"]))
    n = len(pts)
    if n < 2:
        return 0.0
    tele = 0
    for a, b in zip(pts, pts[1:]):
        dt = float(b["t"]) - float(a["t"])
        if dt <= 2.5 / max(fps, 1.0):
            if math.hypot(float(b["x"]) - float(a["x"]),
                          float(b["y"]) - float(a["y"])) > jump_norm:
                tele += 1
    return round(1000.0 * tele / n, 3)


def player_count_metrics(pred_frames: list[dict], gt_frames: list[dict],
                         tol_s: float = 0.12) -> dict:
    """Exact-count fraction and overcount fraction over labelled frames.

    Frames are matched by time; a gt frame with no prediction within tol
    counts as wrong-count (the players were there; the model said nothing)."""
    exact = over = 0
    for g in gt_frames:
        gt_n = len(g.get("boxes") or [])
        near = min(pred_frames, key=lambda f: abs(float(f["t"]) - float(g["t"])),
                   default=None)
        pred_n = len(near.get("boxes") or []) if near and abs(
            float(near["t"]) - float(g["t"])) <= tol_s else 0
        if pred_n == gt_n:
            exact += 1
        elif pred_n > gt_n:
            over += 1
    n = max(len(gt_frames), 1)
    return {"exact_count_frac": round(exact / n, 4),
            "overcount_frac": round(over / n, 4), "n_frames": len(gt_frames)}


def id_switches(pred_frames: list[dict], gt_frames: list[dict],
                tol_s: float = 0.12, match_dist: float = 0.12) -> dict:
    """Identity switches per gt track: how often the pred id assigned to a
    labelled player CHANGES over the rally (audit gate ≤1 per player).
    Matching is nearest-center per frame — adequate at badminton densities."""
    assigned: dict[str, object] = {}
    switches: dict[str, int] = {}
    for g in gt_frames:
        near = min(pred_frames, key=lambda f: abs(float(f["t"]) - float(g["t"])),
                   default=None)
        if not near or abs(float(near["t"]) - float(g["t"])) > tol_s:
            continue
        pboxes = list(near.get("boxes") or [])
        for gb in g.get("boxes") or []:
            gid = str(gb.get("id"))
            best, best_d = None, match_dist
            for pb in pboxes:
                d = math.hypot(float(pb["x"]) - float(gb["x"]),
                               float(pb["y"]) - float(gb["y"]))
                if d <= best_d:
                    best, best_d = pb, d
            if best is None:
                continue
            pid = best.get("id")
            if gid in assigned and assigned[gid] != pid:
                switches[gid] = switches.get(gid, 0) + 1
            assigned[gid] = pid
    per_track = (sum(switches.values()) / max(len(assigned), 1)) if assigned else 0.0
    return {"switches": switches, "tracks_matched": len(assigned),
            "switches_per_track": round(per_track, 3)}


def pose_pck(pred_frames: list[dict], gt_frames: list[dict], thr: float = 0.05,
             tol_s: float = 0.12) -> dict:
    """PCK@thr split near/far court by the labelled person's bbox height
    median (near players look tall in a fixed camera)."""
    heights = [float(p.get("bbox", {}).get("h", 0.0))
               for g in gt_frames for p in (g.get("people") or [])]
    med_h = sorted(heights)[len(heights) // 2] if heights else 0.0
    hits = {"near": 0, "far": 0}
    total = {"near": 0, "far": 0}
    for g in gt_frames:
        near_f = min(pred_frames, key=lambda f: abs(float(f["t"]) - float(g["t"])),
                     default=None)
        if not near_f or abs(float(near_f["t"]) - float(g["t"])) > tol_s:
            continue
        for gp in g.get("people") or []:
            side = "near" if float(gp.get("bbox", {}).get("h", 0.0)) >= med_h else "far"
            gc = gp.get("bbox") or {}
            best, best_d = None, 0.2
            for pp in near_f.get("people") or []:
                pc = pp.get("bbox") or {}
                d = math.hypot(float(pc.get("x", 9)) - float(gc.get("x", 0)),
                               float(pc.get("y", 9)) - float(gc.get("y", 0)))
                if d <= best_d:
                    best, best_d = pp, d
            if best is None:
                continue
            scale = max(float(gc.get("h", 0.0)), 1e-6)
            for gk, pk in zip(gp.get("keypoints") or [], best.get("keypoints") or []):
                total[side] += 1
                d = math.hypot(float(pk["x"]) - float(gk["x"]),
                               float(pk["y"]) - float(gk["y"]))
                if d <= thr * scale:   # PCK: within thr × person height
                    hits[side] += 1
    return {s: round(hits[s] / total[s], 4) if total[s] else None for s in ("near", "far")}


def d3_health(rally_3d: dict | None) -> dict:
    """Label-free 3D acceptance health: accepted shots must contain zero
    below-floor samples (the gates should make this structurally true)."""
    shots = (rally_3d or {}).get("shots") or []
    below = sum(1 for s in shots
                if any(float(p.get("z", 0.0)) < -0.05 for p in s.get("samples") or []))
    return {"accepted": len(shots), "below_floor_accepted": below,
            "rejected": dict((rally_3d or {}).get("rejected") or {})}


def d3_against_labels(rally_3d: dict | None, shots_gt: list[dict]) -> dict:
    """Landing error + speed MAPE against labelled shots (matched by hit time)."""
    shots = (rally_3d or {}).get("shots") or []
    land_err, ape = [], []
    for g in shots_gt:
        near = min(shots, key=lambda s: abs(float(s["t0"]) - float(g["t_hit"])),
                   default=None)
        if not near or abs(float(near["t0"]) - float(g["t_hit"])) > 0.4:
            continue
        if g.get("landing_xy_m"):
            last = (near.get("samples") or [{}])[-1]
            land_err.append(math.hypot(float(last.get("x", 9e9)) - float(g["landing_xy_m"][0]),
                                       float(last.get("y", 9e9)) - float(g["landing_xy_m"][1])))
        if g.get("speed_kmh"):
            ape.append(abs(float(near["speed_kmh"]) - float(g["speed_kmh"]))
                       / max(float(g["speed_kmh"]), 1e-6))
    med = sorted(land_err)[len(land_err) // 2] if land_err else None
    mape = sum(ape) / len(ape) if ape else None
    return {"landing_median_m": round(med, 3) if med is not None else None,
            "speed_mape": round(mape, 4) if mape is not None else None,
            "matched": len(ape) or len(land_err)}
