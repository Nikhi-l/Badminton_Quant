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
