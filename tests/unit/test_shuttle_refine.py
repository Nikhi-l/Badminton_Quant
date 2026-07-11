"""TASK-035: measured shuttle confidence (tracking-by-detection scoring).

TrackNet exposes binary visibility, so workers stored a flat 0.82 on every
point — consumers thresholding ≥0.3 learned nothing. refine_shuttle_track
rewrites confidence from constant-velocity innovation (forward+backward),
drops static false-positive runs, and hard-rejects impossible speeds, per the
smartphone smash-speed literature (low-conf detect → kinematic gates → Kalman
proximity scoring).
"""
import math

from app.pipeline.track import refine_shuttle_track


def _flight(n=60, t0=0.0, x0=0.2, y0=0.7, dx=0.012, dy=-0.008, fps=30.0):
    return [{"t": round(t0 + i / fps, 3), "x": round(x0 + dx * i, 5),
             "y": round(y0 + dy * i, 5), "confidence": 0.82,
             "source": "tracknetv3"} for i in range(n)]


def test_smooth_flight_scores_high_with_provenance():
    out = refine_shuttle_track(_flight())
    assert len(out) == 60
    assert all(p["provenance"] == "observed" for p in out)
    assert all(p["confidence"] >= 0.8 for p in out)
    assert all(p["source"] == "tracknetv3" for p in out)   # fields preserved


def test_teleport_point_collapses_below_consumer_threshold():
    pts = _flight()
    pts[30] = {**pts[30], "x": 0.95, "y": 0.05}   # TrackNet re-locks on a light
    out = refine_shuttle_track(pts)
    assert len(out) == 60                          # kept, but distrusted
    assert out[30]["confidence"] < 0.3             # camera/Studio/3D drop it
    assert out[29]["confidence"] >= 0.6 and out[31]["confidence"] >= 0.6


def test_static_run_is_removed_entirely():
    # 30 flight points, then a "shuttle" pinned on a net post for 12 frames
    # (with sub-radius jitter), then flight resumes: the static run is not
    # flight and must not exist in the refined track at any confidence.
    pts = _flight(30)
    t_next = 30 / 30.0
    for i in range(12):
        pts.append({"t": round(t_next + i / 30, 3),
                    "x": 0.88 + 0.003 * (i % 2), "y": 0.12 + 0.002 * (i % 3),
                    "confidence": 0.82})
    pts += _flight(15, t0=t_next + 12 / 30, x0=0.4, y0=0.5)
    out = refine_shuttle_track(pts)
    assert len(out) == 45
    assert not any(abs(p["x"] - 0.88) < 0.02 and abs(p["y"] - 0.12) < 0.02 for p in out)


def test_false_segment_head_is_exposed_by_backward_pass():
    # A false positive OPENS the track; forward scoring has no context there,
    # but backward the genuine successors expose it (and would otherwise have
    # been poisoned by it as the forward reference).
    pts = [{"t": 0.0, "x": 0.9, "y": 0.9, "confidence": 0.82}]
    pts += _flight(20, t0=1 / 30, x0=0.3, y0=0.4)
    out = refine_shuttle_track(pts)
    assert out[0]["confidence"] < 0.3
    assert out[1]["confidence"] >= 0.6


def test_impossible_speed_hard_gate():
    # Two plausible-looking neighbours implying ~20 frame-widths/sec (~1000
    # km/h): the second is physically impossible regardless of smoothness.
    pts = _flight(10)
    pts[5] = {**pts[5], "x": min(0.99, pts[4]["x"] + 0.7)}
    out = refine_shuttle_track(pts)
    assert out[5]["confidence"] <= 0.1


def test_garbage_and_empty_inputs():
    assert refine_shuttle_track([]) == []
    assert refine_shuttle_track([{"x": 0.5}, {"t": 1.0, "x": -2, "y": 0.5}]) == []
