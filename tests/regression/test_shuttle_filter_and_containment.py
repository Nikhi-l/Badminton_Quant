"""Shuttle false-detection filter + keep-in-frame containment.

User report: (a) false TrackNet detections yank the camera — need a custom filter;
(b) generated highlights don't keep the player or shuttle in frame — need a
containment guarantee on top of the smoothed path.
"""
import numpy as np
import pytest

from app.pipeline import track

CW, CH = 0.316, 1.0  # 9:16 crop of a 16:9 source (matches _crop_norms output)


@pytest.fixture(autouse=True)
def _no_proxy(monkeypatch):
    monkeypatch.setattr(track, "_crop_norms", lambda p: (CW, CH))


def _pt(t, x, y, conf=0.9):
    return {"t": t, "x": x, "y": y, "confidence": conf}


def test_filter_drops_teleport_spikes_keeps_real_motion():
    # A smooth left→right sweep with two isolated teleports (a light, a shirt).
    pts = [_pt(i / 10, 0.2 + 0.05 * i, 0.45) for i in range(12)]
    pts[4] = _pt(0.4, 0.95, 0.05)   # teleport spike
    pts[9] = _pt(0.9, 0.02, 0.98)   # teleport spike
    kept = track.filter_shuttle_points(pts)
    xs = [p["x"] for p in kept]
    assert 0.95 not in xs and 0.02 not in xs, "spikes must be rejected"
    assert len(kept) == 10, "all real points survive"


def test_filter_respects_confidence_and_bounds():
    pts = [
        _pt(0.0, 0.4, 0.4), _pt(0.1, 0.42, 0.41), _pt(0.2, 0.44, 0.42),
        _pt(0.3, 0.46, 0.43, conf=0.1),   # low confidence
        _pt(0.4, 0.0, 0.5),               # out of frame (x==0 sentinel)
    ]
    kept = track.filter_shuttle_points(pts)
    assert len(kept) == 3
    assert all(p["confidence"] >= 0.3 for p in kept)


def test_filter_keeps_fast_smash():
    # A genuine smash: consecutive points move fast but coherently — neighbours
    # move with each point, so nothing should be rejected.
    pts = [_pt(i / 30, 0.25 + 0.08 * i, 0.5 - 0.02 * i) for i in range(8)]
    kept = track.filter_shuttle_points(pts)
    assert len(kept) == 8


def test_spike_does_not_yank_camera():
    # Same rally with and without a spike: the spike must not move the camera
    # path meaningfully (the filter removes it before interpolation).
    t0, t1, fps = 0.0, 4.0, 30
    times = [t0 + i / fps for i in range(round((t1 - t0) * fps))]
    sweep = lambda t: 0.35 + 0.30 * (t / (t1 - t0))
    near = lambda t: sweep(t)

    def rally(with_spike):
        shuttle = [_pt(t, sweep(t), 0.5) for t in times]
        if with_spike:
            shuttle[len(shuttle) // 2] = _pt(times[len(times) // 2], 0.98, 0.02)
        return {
            "player_quality": 0.9, "shuttle_quality": 0.9,
            "shuttle": shuttle,
            "players": [{"t": t, "boxes": [
                {"x1": near(t) - 0.06, "y1": 0.55, "x2": near(t) + 0.06, "y2": 0.92, "confidence": 0.9},
                {"x1": 0.44, "y1": 0.08, "x2": 0.56, "y2": 0.40, "confidence": 0.9},
            ]} for t in times],
        }

    clean = track.from_vision("proxy.mp4", t0, t1, rally(False), fps=fps)
    spiked = track.from_vision("proxy.mp4", t0, t1, rally(True), fps=fps)
    assert clean is not None and spiked is not None
    dx = max(abs(clean.at(t)[0] - spiked.at(t)[0]) for t in times)
    assert dx < 0.02, f"a single false detection moved the camera by {dx:.3f}"


def test_camera_keeps_shuttle_and_player_in_frame():
    # Shuttle sweeps to the far right edge while the near player lags behind —
    # the crop must contain the shuttle point AND the player's body every frame.
    t0, t1, fps = 0.0, 4.0, 30
    times = [t0 + i / fps for i in range(round((t1 - t0) * fps))]
    shu = lambda t: 0.30 + 0.62 * (t / (t1 - t0))          # 0.30 -> 0.92 (edge)
    near = lambda t: 0.30 + 0.35 * (t / (t1 - t0))          # lags the shuttle
    vr = {
        "player_quality": 0.9, "shuttle_quality": 0.9,
        "shuttle": [_pt(t, shu(t), 0.5) for t in times],
        "players": [{"t": t, "boxes": [
            {"x1": near(t) - 0.06, "y1": 0.55, "x2": near(t) + 0.06, "y2": 0.92, "confidence": 0.9},
            {"x1": 0.44, "y1": 0.08, "x2": 0.56, "y2": 0.40, "confidence": 0.9},
        ]} for t in times],
    }
    path = track.from_vision("proxy.mp4", t0, t1, vr, fps=fps)
    assert path is not None
    worst_shuttle = worst_player = 0.0
    for t in times:
        cx, cy, z = path.at(t)
        hw, hh = CW / (2 * z), CH / (2 * z)
        worst_shuttle = max(worst_shuttle, abs(shu(t) - cx) - hw, abs(0.5 - cy) - hh)
        worst_player = max(worst_player, abs(near(t) - cx) - hw)
    assert worst_shuttle <= 0.005, f"shuttle escapes the crop by {worst_shuttle:.3f}"
    assert worst_player <= 0.005, f"near player escapes the crop by {worst_player:.3f}"
