"""TASK-031: One-Euro keypoint smoothing on the public pose_track."""
import math
import random

from app.pipeline.smooth import OneEuro, smooth_pose_track


def _track(points, pid=0, conf=0.9):
    return [{"t": t, "people": [{"id": pid, "confidence": 0.9,
                                 "keypoints": [{"x": x, "y": y, "confidence": conf}]}]}
            for t, x, y in points]


def test_one_euro_reduces_jitter_on_static_signal():
    rng = random.Random(7)
    f = OneEuro()
    raw, smoothed = [], []
    for i in range(60):
        t = i / 6.0
        x = 0.5 + rng.uniform(-0.02, 0.02)
        raw.append(x)
        smoothed.append(f(t, x))
    def jitter(vals):
        return sum(abs(b - a) for a, b in zip(vals, vals[1:]))
    assert jitter(smoothed[10:]) < jitter(raw[10:]) * 0.5


def test_one_euro_tracks_fast_motion_with_low_lag():
    f = OneEuro()
    lag = 0.0
    for i in range(30):
        t = i / 6.0
        x = 0.1 + 0.8 * (i / 29.0)     # fast sweep across the frame
        lag = abs(f(t, x) - x)
    assert lag < 0.05                  # adaptive cutoff keeps up with the sweep


def test_smooth_pose_track_reduces_keypoint_jitter():
    rng = random.Random(3)
    pts = [(i / 6.0, 0.5 + rng.uniform(-0.03, 0.03), 0.4) for i in range(40)]
    raw_xs = [x for _, x, _ in pts]
    track = smooth_pose_track(_track(pts))
    out_xs = [f["people"][0]["keypoints"][0]["x"] for f in track]
    def jitter(vals):
        return sum(abs(b - a) for a, b in zip(vals, vals[1:]))
    assert jitter(out_xs[5:]) < jitter(raw_xs[5:])
    assert all(not math.isnan(x) for x in out_xs)


def test_low_confidence_keypoints_pass_through():
    pts = [(i / 6.0, 0.2 + 0.01 * i, 0.4) for i in range(10)]
    track = smooth_pose_track(_track(pts, conf=0.05))
    out_xs = [f["people"][0]["keypoints"][0]["x"] for f in track]
    assert out_xs == [x for _, x, _ in pts]    # untouched


def test_separate_ids_do_not_share_filter_state():
    frames = []
    for i in range(10):
        t = i / 6.0
        frames.append({"t": t, "people": [
            {"id": 0, "confidence": 0.9, "keypoints": [{"x": 0.1, "y": 0.5, "confidence": 0.9}]},
            {"id": 1, "confidence": 0.9, "keypoints": [{"x": 0.9, "y": 0.5, "confidence": 0.9}]},
        ]})
    out = smooth_pose_track(frames)
    for f in out:
        assert abs(f["people"][0]["keypoints"][0]["x"] - 0.1) < 0.01
        assert abs(f["people"][1]["keypoints"][0]["x"] - 0.9) < 0.01
