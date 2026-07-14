"""TASK-046: court corners may fall OUTSIDE the visible frame.

A side-angle camera cuts court endpoints off-image; the pickers now let the
user place those corners in an out-of-frame margin (normalized coords past
0..1). The homography and every court gate are plane geometry — they must
accept and use such corners unchanged. Server validation widens to ±0.75
while still rejecting garbage and degenerate quads.
"""
import math

from app import config
from app.pipeline import court
from app.pipeline.track import court_player_gate

# A plausible side-angle court: near-left corner cut off the left edge,
# near-right corner below the bottom edge.
EXTRAPOLATED = [[0.30, 0.35], [0.78, 0.36], [1.15, 0.95], [-0.22, 0.92]]


def test_option_accepts_out_of_frame_corners():
    out = config.court_corners_option(EXTRAPOLATED)
    assert out == [[round(x, 4), round(y, 4)] for x, y in EXTRAPOLATED]


def test_option_still_rejects_garbage_and_degenerate():
    beyond = [[0.3, 0.35], [0.78, 0.36], [1.9, 0.95], [-0.22, 0.92]]
    assert config.court_corners_option(beyond) is None          # > +1.75
    tiny = [[0.4, 0.4], [0.45, 0.4], [0.45, 0.45], [0.4, 0.45]]
    assert config.court_corners_option(tiny) is None            # degenerate
    classic = [[0.33, 0.42], [0.67, 0.42], [0.76, 0.91], [0.24, 0.91]]
    assert config.court_corners_option(classic) == classic      # unchanged


def test_options_roundtrip_keeps_extrapolated_corners():
    opts = config.normalize_options({"court_corners": EXTRAPOLATED})
    assert opts.get("court_corners") == EXTRAPOLATED


def test_manual_result_homography_works_out_of_frame():
    res = court.manual_result(EXTRAPOLATED, (1920, 1080))
    assert res["status"] == "ok" and res["source"] == "manual"
    W, L = res["court_size_m"]
    projected = {tuple(round(v, 1) for v in court.project(res["homography"], x, y))
                 for x, y in res["corners"]}
    # corners land on the court rectangle regardless of handedness relabel
    assert projected == {(0.0, 0.0), (W, 0.0), (W, L), (0.0, L)}


def test_player_gate_uses_extrapolated_quad():
    players = [{"t": 0.0, "boxes": [
        # lunging player near the cut-off left sideline: feet at x=0.03
        {"x1": 0.0, "y1": 0.55, "x2": 0.06, "y2": 0.88, "confidence": 0.9},
        # spectator high above the far baseline
        {"x1": 0.48, "y1": 0.05, "x2": 0.55, "y2": 0.2, "confidence": 0.8},
    ]}]
    # duplicate frames so min_keep_frac has data to judge
    players = [dict(players[0], t=i / 6.0) for i in range(6)]
    gated, _ = court_player_gate(players, [], EXTRAPOLATED)
    kept = [b for f in gated for b in f["boxes"]]
    assert all(b["y2"] > 0.5 for b in kept)      # the lunging player survives
    assert all(b["y1"] > 0.3 for b in kept)      # the spectator is gone
    assert len(kept) == len(gated) == 6


def test_worker_court_polygon_accepts_out_of_frame_corners():
    import sys
    import types
    from pathlib import Path
    sys.modules.setdefault("runpod", types.SimpleNamespace(
        serverless=types.SimpleNamespace(start=lambda *_: None)))
    sys.modules.setdefault("requests", types.SimpleNamespace())
    try:
        import cv2  # noqa: F401
    except Exception:  # pragma: no cover
        sys.modules.setdefault("cv2", types.SimpleNamespace())
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runpod_worker"))
    import handler
    poly = handler._court_polygon(EXTRAPOLATED)
    assert poly is not None
    # on-court foot point inside, spectator foot outside
    assert handler._inside_polygon(0.5, 0.7, poly)
    assert not handler._inside_polygon(0.5, 0.1, poly)


def test_manual_result_stays_exact_for_in_frame_corners():
    classic = [[0.33, 0.42], [0.67, 0.42], [0.76, 0.91], [0.24, 0.91]]
    res = court.manual_result(classic, (1920, 1080))
    assert res["status"] == "ok"
    xs = [c[0] for c in res["corners"]]
    assert min(xs) >= 0.0 and max(xs) <= 1.0
    n = res["net"]
    assert n is None or isinstance(n, (list, dict))


def test_extrapolated_court_projects_sane_meters():
    """A point mid-court in the image projects inside the court rectangle."""
    res = court.manual_result(EXTRAPOLATED, (1920, 1080))
    u, v = court.project(res["homography"], 0.5, 0.65)
    assert -0.5 <= u <= 6.6 and -0.5 <= v <= 13.9
    assert not (math.isnan(u) or math.isnan(v))
