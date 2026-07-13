"""TASK-044 Slice 0: per-rally sampling telemetry + per-track health vectors
at canonicalization.

Aggregate player/pose qualities can't say WHICH track went unhealthy or when;
`track_health` records per worker track id: samples, span, longest gap,
coverage against the sampling cadence, and mean confidence. `sampling` carries
the worker's requested/effective cadence and is augmented with a cadence
MEASURED from the raw frame timestamps, so pre-TASK-044 stored raws still gain
visibility on reprocess (fail-open: absent data -> nulls, never an error).
"""
from app.pipeline.gpu import _canonicalize

FPS = 6.0


def _worker_frame(t: float, tids=(1, 2), drop=()):
    players, poses = [], []
    for i, tid in enumerate(tids):
        if tid in drop:
            continue
        cx = 0.3 + 0.4 * i
        players.append({"box": [cx - 0.05, 0.5, cx + 0.05, 0.8],
                        "confidence": 0.9, "track_id": tid})
        poses.append({"keypoints": [{"x": cx, "y": 0.6, "confidence": 0.8}] * 17,
                      "confidence": 0.8, "track_id": tid})
    return {"t": round(t, 3), "players": players, "poses": poses}


def _raw(frames, sampling=None):
    rally = {"rally_index": 1, "frames": frames}
    if sampling is not None:
        rally["sampling"] = sampling
    return {"rallies": [rally]}


RALLIES = [{"start": 0.0, "end": 5.0, "dur": 5.0}]


def test_sampling_prefers_worker_block_and_adds_measured_fps():
    frames = [_worker_frame(i / FPS) for i in range(31)]
    worker_meta = {"requested_sample_fps": 6.0, "effective_sample_fps": 6.0,
                   "requested_frames": 31, "sample_count": 31,
                   "frame_cap": 1080, "degraded": ""}
    out = _canonicalize(_raw(frames, worker_meta), RALLIES)
    s = out["rallies"][0]["sampling"]
    assert s["requested_sample_fps"] == 6.0
    assert s["effective_sample_fps"] == 6.0
    assert s["sample_count"] == 31
    assert s["degraded"] == ""
    assert s["frame_cap"] == 1080
    assert abs(s["measured_sample_fps"] - 6.0) < 0.2   # median frame spacing


def test_sampling_fail_open_for_old_workers():
    """Pre-TASK-044 raws have no sampling block: measured cadence only."""
    frames = [_worker_frame(i / FPS) for i in range(31)]
    out = _canonicalize(_raw(frames), RALLIES)
    s = out["rallies"][0]["sampling"]
    assert s["requested_sample_fps"] is None
    assert s["effective_sample_fps"] is None
    assert abs(s["measured_sample_fps"] - 6.0) < 0.2
    assert s["sample_count"] == 31


def test_track_health_per_worker_id():
    # track 2 vanishes for 8 consecutive samples mid-rally (occlusion).
    frames = []
    for i in range(31):
        drop = (2,) if 10 <= i < 18 else ()
        frames.append(_worker_frame(i / FPS, drop=drop))
    out = _canonicalize(_raw(frames), RALLIES)
    health = out["rallies"][0]["track_health"]
    assert set(health) == {"players", "poses"}
    p1, p2 = health["players"]["1"], health["players"]["2"]
    assert p1["samples"] == 31 and p1["coverage"] >= 0.95
    assert p1["longest_gap_sec"] < 0.2
    assert p2["samples"] == 23
    # the 8-sample dropout is visible as a gap and a coverage deficit
    assert p2["longest_gap_sec"] > 1.2
    assert p2["coverage"] < 0.85
    assert 0.85 <= p1["mean_conf"] <= 0.95
    # pose health mirrors the same ids
    assert set(health["poses"]) == {"1", "2"}


def test_track_health_absent_without_worker_ids():
    frames = []
    for i in range(10):
        f = _worker_frame(i / FPS)
        for b in f["players"]:
            b.pop("track_id")
        for p in f["poses"]:
            p.pop("track_id")
        frames.append(f)
    out = _canonicalize(_raw(frames), RALLIES)
    assert "track_health" not in out["rallies"][0]
    assert out["rallies"][0]["sampling"]["measured_sample_fps"] is not None
