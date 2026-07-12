"""TASK-042: court-aware action zoom for the auto camera.

Owner review (job 1faaa5e4a02f): "There is no camera movement in the render,
and it's not even tracking the shuttle." Root causes: zoom capped at a gentle
1.40x while the court filled a third of the frame, and hard player+shuttle
containment that unzoomed to 1.0x whenever the shuttle crossed the far half.
The action camera picks ONE court-aware zoom per rally from the vertical
action band and pans a blend of shuttle and near player.
"""
import numpy as np
import pytest

from app.pipeline import track, validate

CW, CH = 0.316, 1.0


@pytest.fixture(autouse=True)
def _no_proxy(monkeypatch):
    monkeypatch.setattr(track, "_crop_norms", lambda p: (CW, CH))


def _far_court_rally(t0=0.0, t1=20.0, fps=12):
    """Tripod-far footage: the whole match lives in a y 0.45..0.68 band —
    exactly the owner's video where the reel rendered fully wide and static."""
    times = [t0 + i / fps for i in range(int((t1 - t0) * fps))]
    shu = lambda t: 0.5 + 0.3 * np.sin(t * 1.1)
    near = lambda t: 0.62 + 0.18 * np.sin(t * 0.5)
    return {
        "player_quality": 0.7, "shuttle_quality": 0.9,
        "shuttle": [{"t": t, "x": float(shu(t)), "y": 0.47 + 0.06 * np.sin(t * 2.3),
                     "confidence": 0.9} for t in times],
        "players": [{"t": t, "boxes": [
            {"x1": float(near(t)) - 0.05, "y1": 0.50, "x2": float(near(t)) + 0.05,
             "y2": 0.64, "confidence": 0.9},
            {"x1": 0.45, "y1": 0.46, "x2": 0.52, "y2": 0.56, "confidence": 0.7},
        ]} for t in times],
    }


def test_far_court_footage_gets_action_zoom():
    vr = _far_court_rally()
    path = track.from_vision("proxy.mp4", 0.0, 20.0, vr)
    assert path is not None
    # punchy: well past the old 1.40 cap, stable (no breathing), and panning
    assert float(np.median(path.zs)) >= 1.7
    assert float(path.zs.max() - path.zs.min()) <= 0.15
    assert float(path.xs.max() - path.xs.min()) >= 0.2
    ps = validate.path_smoothness(path, CW, CH)
    assert ps["ok"], f"action camera must stay smooth: {ps}"


def test_full_frame_footage_keeps_gentle_zoom():
    # broadcast-style: players span most of the frame height — the action
    # band is tall, so the zoom stays in the old gentle range
    times = [i / 12 for i in range(120)]
    vr = {
        "player_quality": 0.9, "shuttle_quality": 0.9,
        "shuttle": [{"t": t, "x": 0.5 + 0.2 * np.sin(t), "y": 0.35,
                     "confidence": 0.9} for t in times],
        "players": [{"t": t, "boxes": [
            {"x1": 0.35, "y1": 0.55, "x2": 0.55, "y2": 0.95, "confidence": 0.9},
            {"x1": 0.45, "y1": 0.12, "x2": 0.58, "y2": 0.38, "confidence": 0.9},
        ]} for t in times],
    }
    path = track.from_vision("proxy.mp4", 0.0, 10.0, vr)
    assert path is not None
    assert float(path.zs.max()) <= track.Z_MAX + 1e-6


def test_action_zoom_bounds():
    z, band_lo = track._action_zoom([], [], CH, 0.10, 0.13)
    assert z == track.Z_MAX and band_lo == 0.0      # no data → old gentle cap
    players = [{"boxes": [{"y1": 0.50, "y2": 0.64}]} for _ in range(30)]
    z, band_lo = track._action_zoom(players, [], CH, 0.10, 0.13)
    assert track.Z_MAX <= z <= track.Z_ACTION_MAX
    assert z > 1.8                                   # small band → real punch
    assert 0.3 <= band_lo <= 0.5
