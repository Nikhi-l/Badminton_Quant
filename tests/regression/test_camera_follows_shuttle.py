"""TASK-001 regression: the virtual camera must follow the shuttle.

Before the fix, from_vision centred on the player bounding box and only nudged
toward the shuttle, so the camera tracked players (often the net midpoint), not
the shuttle. These tests assert the shuttle is the primary follow target.
"""
import numpy as np
import pytest

from app.pipeline import render, track
from app.pipeline.run import _can_use_vision_camera

CW, CH = 0.316, 1.0  # 9:16 crop of a 16:9 source (matches _crop_norms output)


@pytest.fixture(autouse=True)
def _no_proxy(monkeypatch):
    # from_vision reads crop dims from the proxy file; stub it so tests need no I/O.
    monkeypatch.setattr(track, "_crop_norms", lambda p: (CW, CH))


def _near_box(cx, conf=0.9):
    return {"x1": cx - 0.06, "y1": 0.55, "x2": cx + 0.06, "y2": 0.92, "confidence": conf}


def _far_box(cx=0.5, conf=0.9):
    return {"x1": cx - 0.06, "y1": 0.08, "x2": cx + 0.06, "y2": 0.40, "confidence": conf}


def _rally(times, shuttle_x, near_x, far_x=0.5, sy=0.5, sq=0.9, pq=0.9):
    return {
        "player_quality": pq,
        "shuttle_quality": sq,
        "shuttle": [{"t": t, "x": shuttle_x(t), "y": sy, "confidence": 0.9} for t in times],
        "players": [{"t": t, "boxes": [_near_box(near_x(t)), _far_box(far_x)]} for t in times],
    }


def test_camera_follows_sweeping_shuttle():
    """Near player rallies with the shuttle as it sweeps across the court; the
    opponent stays put. The camera must pan with the shuttle, not sit on the
    static both-players midpoint."""
    t0, t1, fps = 0.0, 4.0, 30
    times = [t0 + i / fps for i in range(round((t1 - t0) * fps))]
    sweep = lambda t: 0.30 + 0.40 * (t / (t1 - t0))  # 0.30 -> 0.70
    vr = _rally(times, shuttle_x=sweep, near_x=sweep, far_x=0.5)

    path = track.from_vision("proxy.mp4", t0, t1, vr, fps=fps)
    assert path is not None

    cam_x = np.array([path.at(t)[0] for t in times])
    shu_x = np.array([sweep(t) for t in times])

    corr = float(np.corrcoef(cam_x, shu_x)[0, 1])
    assert corr > 0.9, f"camera x should track the shuttle sweep (corr={corr:.2f})"
    # and it must actually pan a meaningful distance, not hover near centre
    assert cam_x.max() - cam_x.min() > 0.25, f"camera barely panned ({cam_x.ptp():.3f})"


def test_shuttle_pulls_camera_past_static_player_midpoint():
    """With both players static and centred, a shuttle held off to one side must
    pull the camera toward it — the discriminator vs the old player-centred camera."""
    t0, t1, fps = 0.0, 3.0, 30
    times = [t0 + i / fps for i in range(round((t1 - t0) * fps))]
    with_shuttle = _rally(times, shuttle_x=lambda t: 0.72, near_x=lambda t: 0.5, far_x=0.5)
    no_shuttle = _rally(times, shuttle_x=lambda t: 0.72, near_x=lambda t: 0.5, far_x=0.5, sq=0.0)
    no_shuttle["shuttle"] = []

    cam_with = np.array([track.from_vision("p.mp4", t0, t1, with_shuttle, fps=fps).at(t)[0] for t in times])
    cam_without = np.array([track.from_vision("p.mp4", t0, t1, no_shuttle, fps=fps).at(t)[0] for t in times])

    assert cam_with.mean() > cam_without.mean() + 0.01, (
        f"shuttle at 0.72 should pull camera right of player centre "
        f"(with={cam_with.mean():.3f} vs without={cam_without.mean():.3f})")


def test_no_shuttle_still_frames_players():
    """No shuttle data → from_vision still returns a player-framing path."""
    t0, t1, fps = 0.0, 3.0, 30
    times = [t0 + i / fps for i in range(round((t1 - t0) * fps))]
    vr = _rally(times, shuttle_x=lambda t: 0.5, near_x=lambda t: 0.5, sq=0.0)
    vr["shuttle"] = []
    path = track.from_vision("p.mp4", t0, t1, vr, fps=fps)
    assert path is not None


def test_high_shuttle_does_not_point_at_ceiling():
    """A high clear (shuttle near the top of frame) must NOT pull the camera up
    off the court — vertical stays anchored to the players' court band."""
    t0, t1, fps = 0.0, 3.0, 30
    times = [t0 + i / fps for i in range(round((t1 - t0) * fps))]
    # players on the court (lower half); shuttle held high in the air the whole time
    vr = _rally(times, shuttle_x=lambda t: 0.5, near_x=lambda t: 0.5, far_x=0.5, sy=0.06)
    path = track.from_vision("p.mp4", t0, t1, vr, fps=fps)
    cam_y = np.array([path.at(t)[1] for t in times])
    assert cam_y.min() > 0.35, f"camera drifted toward the ceiling (min cy={cam_y.min():.2f})"


def test_camera_path_stays_smooth():
    """Following the shuttle must not produce a jerky path (acceleration bounded)."""
    t0, t1, fps = 0.0, 4.0, 30
    times = [t0 + i / fps for i in range(round((t1 - t0) * fps))]
    sweep = lambda t: 0.30 + 0.40 * (t / (t1 - t0))
    vr = _rally(times, shuttle_x=sweep, near_x=sweep)
    path = track.from_vision("p.mp4", t0, t1, vr, fps=fps)
    cam_x = np.array([path.at(t)[0] for t in times])
    accel = np.abs(np.diff(cam_x, 2))
    assert np.percentile(accel, 99) < 0.02, f"camera pan too jerky (a99={np.percentile(accel,99):.4f})"


def test_render_zoom_punch_is_disabled_by_default():
    """The old hardcoded opening punch made smooth paths look like zoom pops."""
    assert render._punch(0.0) == 1.0
    assert render._punch(0.5) == 1.0
    assert render._push(1.0) <= 1.025


def test_pov_can_still_use_strong_tracknet_shuttle_camera():
    assert _can_use_vision_camera(False, {"shuttle_quality": 0.0})
    assert _can_use_vision_camera(True, {"shuttle_quality": 0.7})
    assert not _can_use_vision_camera(True, {"shuttle_quality": 0.2})
