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


def test_court_gate_drops_background_court_segments():
    """TASK-041: a background court's rally is smooth plausible flight — only
    geometry separates it. Segments mostly outside the (expanded) main-court
    quad drop wholesale; a main-court clear whose apex arcs above the far
    line survives on its majority-inside points."""
    from app.pipeline.track import court_shuttle_gate
    corners = [[0.3, 0.3], [0.7, 0.3], [0.9, 0.9], [0.1, 0.9]]

    main = [{"t": i / 30, "x": 0.4 + i * 0.004,
             "y": 0.65 - (0.5 if 12 <= i <= 20 else 0.0) * 0.02 * (i - 12),
             "confidence": 0.9} for i in range(40)]           # inside, apex dips high
    clear_apex = [{"t": 1.5 + i / 30, "x": 0.5, "y": 0.16 + 0.01 * i,
                   "confidence": 0.9} for i in range(8)]      # brief excursion above far line
    background = [{"t": 4.0 + i / 30, "x": 0.45 + i * 0.005, "y": 0.08,
                   "confidence": 0.9} for i in range(30)]     # other court, above ours

    kept = court_shuttle_gate(main + clear_apex + background, corners)
    ts = [p["t"] for p in kept]
    assert any(t < 1.4 for t in ts)                # main rally kept
    assert not any(t >= 4.0 for t in ts)           # background rally gone
    # no corners → no opinion
    assert len(court_shuttle_gate(background, None)) == len(background)
