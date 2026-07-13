import json
import math

from app.main import _public_rally, _public_result, _sample_shuttle_track


def test_gallery_light_result_omits_heavy_tracking():
    # A reel with dense per-rally tracking. The gallery list (light) must NOT embed it
    # — that ballooned /api/gallery to 225KB/8s and broke the "past reels" view.
    dense_shuttle = [{"t": i / 30, "x": 0.5, "y": 0.4, "confidence": 0.9} for i in range(300)]
    players = [{"t": i / 30, "boxes": [{"x1": 0.2, "y1": 0.1, "x2": 0.3, "y2": 0.34, "confidence": 0.8}]}
               for i in range(300)]
    rally = {"start": 1.0, "end": 9.0, "dur": 8.0,
             "vision": {"status": "ok", "shuttle_quality": 0.8, "player_quality": 0.7,
                        "shuttle": dense_shuttle, "players": players}}
    result = {"duration": 8.0, "n_rallies_used": 1, "n_rallies_found": 3,
              "rallies": [rally], "rally_pool": [rally], "all_rallies": [rally],
              "vision": {"status": "ok", "summary": {"shuttle_quality": 0.8}}}
    job = {"id": "abc123", "filename": "x.mp4", "result": json.dumps(result)}

    light = _public_result(job, light=True)
    full = _public_result(job, light=False)

    # Light: aggregate fields kept, heavy per-rally arrays dropped entirely.
    assert light["duration"] == 8.0 and light["n_rallies_used"] == 1
    assert light["thumb"].endswith("thumb.jpg") and light["vision"]["status"] == "ok"
    assert "rallies" not in light and "rally_pool" not in light and "all_rallies" not in light

    # Full: rallies present with the bounded tracking the Studio needs.
    assert full["rallies"][0]["vision"]["shuttle_track"]
    assert full["rallies"][0]["vision"]["players_track"]

    # Light is dramatically smaller (the whole point).
    assert len(json.dumps(light)) * 5 < len(json.dumps(full))


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


def test_long_rally_shuttle_track_keeps_studio_continuity():
    """TASK-034 P0 repro: a perfectly smooth 70 s 10 Hz track was uniformly
    decimated to 175 points spaced 0.4 s — EVERY pair above Studio's 0.35 s
    dropout cutoff (TRAIL_MAX_STEP_SEC), so the trail was always empty and the
    marker flickered. Contract now: in-segment spacing stays ≤ 0.33 s
    regardless of rally length; continuity is never destroyed by decimation."""
    dense = [{"t": round(i * 0.1, 3),
              "x": 0.5 + 0.3 * math.sin(i * 0.02),
              "y": 0.4 + 0.2 * math.cos(i * 0.03),
              "confidence": 0.82} for i in range(700)]

    track = _sample_shuttle_track(dense)

    assert len(track) >= 600            # no whole-rally 180-point cap
    gaps = [b["t"] - a["t"] for a, b in zip(track, track[1:])]
    assert max(gaps) <= 0.35 - 1e-9     # every pair below the Studio threshold


def test_shuttle_track_preserves_real_dropouts_as_gaps():
    """A real detector dropout must SURVIVE sampling (Studio hides the marker
    there on purpose) — not be papered over, and not poison nearby spacing."""
    def seg(t0, x0, dx):
        return [{"t": round(t0 + i / 30, 3), "x": round(x0 + i * dx, 5),
                 "y": 0.5, "confidence": 0.82} for i in range(150)]

    dense = seg(0.0, 0.3, 0.004) + seg(7.0, 0.9, -0.004)   # 2 s blind hole

    track = _sample_shuttle_track(dense)

    gaps = [round(b["t"] - a["t"], 3) for a, b in zip(track, track[1:])]
    big = [g for g in gaps if g > 0.35]
    assert len(big) == 1 and 1.9 < big[0] < 2.2   # exactly the real hole
    assert all(g <= 0.35 for g in gaps if g != big[0])   # in-segment spacing ok
    # Segment endpoints are kept: the marker's last-seen position is exact.
    assert track[0]["t"] == 0.0
    assert any(abs(f["t"] - 4.967) < 1e-6 for f in track)   # end of flight 1
    assert any(abs(f["t"] - 7.0) < 1e-6 for f in track)     # start of flight 2


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
    # TASK-044: below the 1080-frame ceiling the public track passes through
    # undecimated — public sampling never drops below the worker cadence.
    assert len(ptrack) == 240
    box = ptrack[0]["boxes"][0]
    assert set(box) == {"id", "x", "y", "w", "h", "confidence"}
    # Exactly two stable player identities across the whole track (no id churn).
    ids = {b["id"] for f in ptrack for b in f["boxes"]}
    assert ids == {0, 1}
    # The near-bottom player keeps one id; the near-top player keeps the other.
    bottom_ids = {b["id"] for f in ptrack for b in f["boxes"] if b["y"] > 0.5}
    top_ids = {b["id"] for f in ptrack for b in f["boxes"] if b["y"] < 0.5}
    assert len(bottom_ids) == 1 and len(top_ids) == 1 and bottom_ids != top_ids


def test_player_ids_survive_fast_motion_and_dropouts():
    """TASK-021 regression: a fast lunge between sparse samples must not mint a new
    id (the old 0.22 gate churned P1→P3→P5…), and frames where the far player is
    missed must not steal the near player's identity."""
    frames = []
    for i in range(240):
        near_x = 0.25 if (i // 40) % 2 == 0 else 0.62   # jumps 0.37 across a sample gap
        near = _box(near_x, 0.72, w=0.16, h=0.34)
        boxes = [near]
        if i % 3 != 0:   # far player intermittently missed by the detector
            boxes.append(_box(0.5, 0.30, w=0.06, h=0.13))
        frames.append({"t": i / 30, "boxes": boxes})

    out = _public_rally({
        "start": 0.0, "end": 8.0, "dur": 8.0,
        "vision": {"status": "ok", "player_quality": 0.7, "players": frames},
    })

    ptrack = out["vision"]["players_track"]
    ids = {b["id"] for f in ptrack for b in f["boxes"]}
    assert ids == {0, 1}, f"id churn: {sorted(ids)}"
    # Identity never swaps: the tall near-court player is one id on every frame,
    # and relabeling makes that id 0 (P1 = near player, every rally).
    near_ids = {b["id"] for f in ptrack for b in f["boxes"] if b["h"] > 0.2}
    far_ids = {b["id"] for f in ptrack for b in f["boxes"] if b["h"] <= 0.2}
    assert near_ids == {0} and far_ids == {1}


def _pose_person(cx, cy, conf=0.85):
    keypoints = []
    for i in range(17):
        keypoints.append({
            "x": cx + (i % 3 - 1) * 0.01,
            "y": cy + (i // 3) * 0.008,
            "confidence": conf,
        })
    return {
        "confidence": conf,
        "bbox": {"x1": cx - 0.06, "y1": cy - 0.14, "x2": cx + 0.06, "y2": cy + 0.14,
                 "confidence": conf},
        "keypoints": keypoints,
    }


def test_public_rally_exposes_bounded_pose_track_with_stable_ids():
    frames = []
    for i in range(240):
        frames.append({"t": i / 30, "people": [
            _pose_person(0.24 + 0.02 * (i % 4) / 4, 0.70),
            _pose_person(0.72 - 0.02 * (i % 5) / 5, 0.34),
        ]})

    out = _public_rally({
        "start": 0.0, "end": 8.0, "dur": 8.0,
        "vision": {"status": "ok", "pose_quality": 0.8, "poses": frames},
    })

    track = out["vision"]["pose_track"]
    # TASK-044: undecimated below the 1080-frame ceiling (matches the worker).
    assert len(track) == 240
    person = track[0]["people"][0]
    assert set(person) == {"id", "confidence", "keypoints", "bbox"}
    assert len(person["keypoints"]) == 17
    assert set(person["bbox"]) == {"x", "y", "w", "h", "confidence"}
    ids = {p["id"] for f in track for p in f["people"]}
    assert ids == {0, 1}


def test_gallery_light_result_omits_pose_track_with_other_heavy_tracks():
    pose_frames = [{"t": i / 30, "people": [_pose_person(0.4, 0.6)]} for i in range(180)]
    rally = {"start": 0.0, "end": 6.0, "dur": 6.0,
             "vision": {"status": "ok", "pose_quality": 0.8, "poses": pose_frames}}
    result = {"duration": 6.0, "n_rallies_used": 1, "n_rallies_found": 1,
              "rallies": [rally], "rally_pool": [rally], "vision": {"status": "ok"}}
    job = {"id": "abc123", "filename": "x.mp4", "result": json.dumps(result)}

    light = _public_result(job, light=True)
    full = _public_result(job, light=False)

    assert "rallies" not in light
    assert full["rallies"][0]["vision"]["pose_track"]
