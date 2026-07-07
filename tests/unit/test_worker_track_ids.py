"""TASK-024: worker-supplied ByteTrack ids flow through to the public tracks."""
from app.main import _public_rally
from app.pipeline import gpu


def _wbox(cx, cy, w=0.1, h=0.3, conf=0.8, track_id=None):
    b = {"box": [cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2], "confidence": conf}
    if track_id is not None:
        b["track_id"] = track_id
    return b


def test_canonicalize_carries_track_ids():
    raw = {
        "rallies": [{
            "rally_index": 1,
            "frames": [{
                "t": 0.5,
                "players": [_wbox(0.3, 0.7, track_id=7), _wbox(0.7, 0.3, h=0.14, track_id=3)],
                "poses": [
                    {"track_id": 7, "keypoints": [{"x": 0.3, "y": 0.6, "confidence": 0.9}]},
                    {"track_id": 3, "keypoints": [{"x": 0.7, "y": 0.25, "confidence": 0.9}]},
                ],
            }],
        }],
    }
    out = gpu._canonicalize(raw, [{"start": 0.0, "end": 2.0, "dur": 2.0}])
    rally = out["rallies"][0]
    assert [b.get("track_id") for b in rally["players"][0]["boxes"]] == [7, 3]
    assert [p.get("track_id") for p in rally["poses"][0]["people"]] == [7, 3]


def test_sampler_prefers_worker_ids_over_heuristic():
    # Two SAME-height players crossing paths — the centroid+size heuristic has
    # no way to keep them apart at the crossover, but ByteTrack ids do.
    frames = []
    for i in range(120):
        k = i / 119.0
        a = {"x1": 0.1 + 0.6 * k, "y1": 0.55, "x2": 0.22 + 0.6 * k, "y2": 0.85,
             "confidence": 0.9, "track_id": 11}
        b = {"x1": 0.7 - 0.6 * k, "y1": 0.55, "x2": 0.82 - 0.6 * k, "y2": 0.85,
             "confidence": 0.9, "track_id": 12}
        frames.append({"t": i / 15.0, "boxes": [a, b]})

    out = _public_rally({
        "start": 0.0, "end": 8.0, "dur": 8.0,
        "vision": {"status": "ok", "player_quality": 0.8, "players": frames},
    })
    ptrack = out["vision"]["players_track"]
    ids = {b["id"] for f in ptrack for b in f["boxes"]}
    assert ids == {0, 1}
    # Every box that carried worker id 11 maps to ONE output id across the whole
    # rally (no swap at the crossover), and 12 maps to the other.
    first_by_frame = [f["boxes"][0]["id"] for f in ptrack]
    second_by_frame = [f["boxes"][1]["id"] for f in ptrack]
    assert len(set(first_by_frame)) == 1 and len(set(second_by_frame)) == 1
    assert first_by_frame[0] != second_by_frame[0]


def test_sampler_falls_back_when_worker_ids_sparse():
    # <90% coverage → heuristic path; the classic near/far scenario still
    # resolves to exactly two stable ids with the near player as P1 (id 0).
    frames = []
    for i in range(120):
        near = {"x1": 0.3, "y1": 0.5, "x2": 0.46, "y2": 0.84, "confidence": 0.9}
        far = {"x1": 0.55, "y1": 0.24, "x2": 0.62, "y2": 0.38, "confidence": 0.7}
        if i % 3 == 0:   # only a third of boxes carry ids
            near["track_id"] = 5
        frames.append({"t": i / 15.0, "boxes": [near, far]})

    out = _public_rally({
        "start": 0.0, "end": 8.0, "dur": 8.0,
        "vision": {"status": "ok", "player_quality": 0.8, "players": frames},
    })
    ptrack = out["vision"]["players_track"]
    ids = {b["id"] for f in ptrack for b in f["boxes"]}
    assert ids == {0, 1}
    near_ids = {b["id"] for f in ptrack for b in f["boxes"] if b["h"] > 0.2}
    assert near_ids == {0}


def test_pose_sampler_uses_worker_ids():
    def person(cx, cy, tid):
        return {"confidence": 0.8, "track_id": tid,
                "bbox": {"x1": cx - 0.05, "y1": cy - 0.15, "x2": cx + 0.05,
                         "y2": cy + 0.15, "confidence": 0.8},
                "keypoints": [{"x": cx, "y": cy, "confidence": 0.9} for _ in range(17)]}

    frames = [{"t": i / 15.0, "people": [person(0.3, 0.7, 21), person(0.7, 0.3, 22)]}
              for i in range(90)]
    out = _public_rally({
        "start": 0.0, "end": 6.0, "dur": 6.0,
        "vision": {"status": "ok", "pose_quality": 0.8, "poses": frames},
    })
    track = out["vision"]["pose_track"]
    ids = {p["id"] for f in track for p in f["people"]}
    assert ids == {0, 1}
    # track_id is internal plumbing — the public payload must not leak it.
    assert all("track_id" not in p for f in track for p in f["people"])
    assert all("track_id" not in b
               for f in out["vision"]["players_track"] for b in f["boxes"]) if out["vision"].get("players_track") else True
