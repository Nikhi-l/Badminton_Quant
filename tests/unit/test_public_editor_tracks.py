from app.main import _public_rally


def test_public_rally_exposes_bounded_shuttle_track():
    dense_track = [
        {"t": i / 30, "x": 0.2 + i * 0.001, "y": 0.45, "confidence": 0.91, "vendor": "raw"}
        for i in range(360)
    ]

    out = _public_rally({
        "start": 10.0,
        "end": 22.0,
        "dur": 12.0,
        "vision": {
            "status": "ok",
            "shuttle_quality": 0.88,
            "pose_quality": 0.72,
            "shuttle": dense_track,
        },
    })

    track = out["vision"]["shuttle_track"]
    assert 0 < len(track) <= 180
    assert set(track[0]) == {"t", "x", "y", "confidence"}
    assert track[0] == {"t": 0.0, "x": 0.2, "y": 0.45, "confidence": 0.91}


def _box(cx, cy, w=0.12, h=0.28, conf=0.8):
    return {"x1": cx - w / 2, "y1": cy - h / 2, "x2": cx + w / 2, "y2": cy + h / 2, "confidence": conf}


def test_public_rally_exposes_player_track_with_stable_ids():
    # Two players drifting on opposite court halves across many frames.
    frames = []
    for i in range(240):
        a = _box(0.25 + 0.05 * (i % 3) / 3, 0.70 - 0.04 * (i % 5) / 5)
        b = _box(0.74 - 0.05 * (i % 4) / 4, 0.32 + 0.03 * (i % 2))
        frames.append({"t": i / 30, "boxes": [a, b]})

    out = _public_rally({
        "start": 0.0, "end": 8.0, "dur": 8.0,
        "vision": {"status": "ok", "player_quality": 0.7, "players": frames},
    })

    ptrack = out["vision"]["players_track"]
    assert 0 < len(ptrack) <= 120
    box = ptrack[0]["boxes"][0]
    assert set(box) == {"id", "x", "y", "w", "h", "confidence"}
    # Exactly two stable player identities across the whole track (no id churn).
    ids = {b["id"] for f in ptrack for b in f["boxes"]}
    assert ids == {0, 1}
    # The near-bottom player keeps one id; the near-top player keeps the other.
    bottom_ids = {b["id"] for f in ptrack for b in f["boxes"] if b["y"] > 0.5}
    top_ids = {b["id"] for f in ptrack for b in f["boxes"] if b["y"] < 0.5}
    assert len(bottom_ids) == 1 and len(top_ids) == 1 and bottom_ids != top_ids
