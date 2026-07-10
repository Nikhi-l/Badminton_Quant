"""TASK-034 P0: shuttle quality must reflect track health, not just coverage.

The old worker score was mean(constant 0.82) × coverage — a track that
teleported between a light and a shirt every few frames scored exactly the
same "82%" as a clean one. `_track_metrics` keeps the coverage term and adds
longest-gap and teleport penalties measurable without labels.
"""
import math
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

sys.modules.setdefault("runpod", types.SimpleNamespace(serverless=types.SimpleNamespace(start=lambda *_: None)))
sys.modules.setdefault("requests", types.SimpleNamespace())
try:
    import cv2  # noqa: F401
except Exception:  # pragma: no cover
    sys.modules.setdefault("cv2", types.SimpleNamespace())
sys.path.insert(0, str(ROOT / "runpod_worker"))
import handler  # noqa: E402

FPS = 10.0
DUR = 70.0


def _smooth_track():
    # 70 s at 10 Hz, a plausible slow arc — full expected coverage at fps=10.
    return [{"t": round(i / FPS, 3),
             "x": 0.3 + 0.25 * math.sin(i / FPS * 0.8),
             "y": 0.35 + 0.1 * math.cos(i / FPS * 0.5)}
            for i in range(int(DUR * FPS))]


def test_smooth_full_coverage_scores_high():
    m = handler._track_metrics(_smooth_track(), DUR, FPS)
    assert m["teleports"] == 0
    assert m["coverage"] == 1.0
    assert m["quality"] >= 0.9


def test_teleporting_track_scores_much_lower_despite_full_coverage():
    pts = _smooth_track()
    # Every 10th point re-locks on a stadium light: same coverage, garbage track.
    for i in range(0, len(pts), 10):
        pts[i] = {**pts[i], "x": 0.95, "y": 0.05}
    jerky = handler._track_metrics(pts, DUR, FPS)
    smooth = handler._track_metrics(_smooth_track(), DUR, FPS)
    assert jerky["coverage"] == smooth["coverage"] == 1.0   # the old score's only input
    assert jerky["teleports"] > 50
    assert jerky["quality"] < 0.25 < smooth["quality"]


def test_long_gap_penalizes():
    pts = [p for p in _smooth_track() if not (20.0 <= p["t"] < 32.0)]
    m = handler._track_metrics(pts, DUR, FPS)
    smooth = handler._track_metrics(_smooth_track(), DUR, FPS)
    assert m["longest_gap_sec"] >= 11.9
    # The gap penalty is proportional to the blind share of the rally: a 12 s
    # hole in 70 s costs ~16%, even though the remaining points still fill the
    # expected-coverage budget (the old score would have been unchanged).
    assert m["quality"] <= 0.85 < smooth["quality"]


def test_empty_track_scores_zero():
    m = handler._track_metrics([], DUR, FPS)
    assert m["quality"] == 0.0 and m["coverage"] == 0.0
