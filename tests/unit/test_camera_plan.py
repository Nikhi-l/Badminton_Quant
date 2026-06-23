import numpy as np

from app.pipeline import track


def _vision():
    # Shuttle moves left->right over t=0..2 (right side by t=2). Two static players:
    # a top-left player and a bottom-right player. _two_player_tracks labels the
    # higher (smaller y) one 'far' (id 1) and the lower one 'near' (id 0).
    shuttle = [{"t": t / 10, "x": 0.2 + 0.6 * (t / 20), "y": 0.5, "confidence": 0.9}
               for t in range(0, 21)]
    players = []
    for t in range(0, 41):
        players.append({"t": t / 10, "boxes": [
            {"x1": 0.20, "y1": 0.10, "x2": 0.30, "y2": 0.34, "confidence": 0.8},  # top-left  -> far (id 1)
            {"x1": 0.70, "y1": 0.66, "x2": 0.80, "y2": 0.90, "confidence": 0.8},  # bot-right -> near (id 0)
        ]})
    return {"shuttle_quality": 0.8, "player_quality": 0.7, "shuttle": shuttle, "players": players}


def test_from_camera_plan_follows_and_switches_target():
    kfs = [
        {"t": 0.0, "target": "shuttle", "zoom": 1.2},
        {"t": 2.0, "target": "player", "target_player": 1, "zoom": 1.8},  # far = top-left
    ]
    fp = track.from_camera_plan("proxy.mp4", 0.0, 4.0, _vision(), kfs, fps=10, crop_norms=(0.5, 1.0))
    assert fp is not None
    assert len(fp.xs) == 40 and fp.fps == 10

    # Before the switch the camera follows the shuttle (right side); after it follows
    # the far player (top-left) — proving target resolution + switching.
    x_before = fp.at(1.5)[0]
    x_after = fp.at(3.7)[0]
    assert x_before > 0.55, x_before
    assert x_after < 0.45, x_after

    # Zoom interpolates upward toward the player keyframe and stays in [1.0, 2.5].
    z_early, z_late = fp.at(0.3)[2], fp.at(3.7)[2]
    assert z_late > z_early
    assert 1.0 <= z_early <= 2.5 and 1.0 <= z_late <= 2.5


def test_from_camera_plan_fixed_point_holds_steady():
    kfs = [{"t": 0.0, "target": "point", "point": {"x": 0.3, "y": 0.5}, "zoom": 1.5}]
    fp = track.from_camera_plan("proxy.mp4", 0.0, 2.0, _vision(), kfs, fps=10, crop_norms=(0.5, 1.0))
    assert fp is not None
    # A fixed point stays put: centre x near 0.3 throughout, low variance.
    xs = [fp.at(t / 10)[0] for t in range(0, 20)]
    assert abs(np.mean(xs) - 0.3) < 0.06
    assert np.std(xs) < 0.03


def test_from_camera_plan_empty_returns_none():
    assert track.from_camera_plan("p.mp4", 0, 2, {"shuttle": []}, [], fps=10, crop_norms=(0.5, 1.0)) is None


def test_camera_segment_for_rally_maps_reel_to_source():
    camera = {"enabled": True, "keyframes": [
        {"t": 0.0, "target": "shuttle", "zoom": 1.4},
        {"t": 5.0, "target": "player", "target_player": 1, "zoom": 1.6},
        {"t": 12.0, "target": "point", "point": {"x": 0.5, "y": 0.4}, "zoom": 1.2},
    ]}
    # Rally A: reel 0..8, source starts at 53. The t=5 keyframe falls inside (→ source
    # 58); the t=12 one does not. Seeded with the keyframe active at reel 0 (shuttle).
    seg_a = track.camera_segment_for_rally(camera, 0.0, 8.0, 53.0)
    assert [(round(k["t"], 2), k["target"]) for k in seg_a] == [(53.0, "shuttle"), (58.0, "player")]
    # Rally B: reel 8..13, source starts at 34. Active at reel 8 is the t=5 player kf
    # (seeded at source 34); the t=12 point kf maps to source 34+(12-8)=38.
    seg_b = track.camera_segment_for_rally(camera, 8.0, 13.0, 34.0)
    assert [(round(k["t"], 2), k["target"]) for k in seg_b] == [(34.0, "player"), (38.0, "point")]


def test_camera_segment_disabled_or_empty():
    assert track.camera_segment_for_rally(None, 0, 8, 0) == []
    assert track.camera_segment_for_rally({"enabled": False, "keyframes": [{"t": 0}]}, 0, 8, 0) == []
    assert track.camera_segment_for_rally({"enabled": True, "keyframes": []}, 0, 8, 0) == []


def test_validate_camera_normalizes_editor_plan():
    from app.main import _validate_camera
    assert _validate_camera(None) is None
    assert _validate_camera({"enabled": False, "keyframes": [{"t": 0}]}) is None
    out = _validate_camera({"enabled": True, "keyframes": [
        {"t": 0, "target": "player", "targetPlayer": 1, "zoom": 1.6},
        {"t": 3, "target": "bogus", "point": {"x": 0.2, "y": 0.3}, "zoom": 2.0},
    ]})
    assert out["enabled"] is True
    assert out["keyframes"][0] == {"t": 0.0, "target": "player", "target_player": 1, "zoom": 1.6}
    # unknown target falls back to shuttle; camelCase targetPlayer → snake_case
    assert out["keyframes"][1]["target"] == "shuttle"
    assert out["keyframes"][1]["point"] == {"x": 0.2, "y": 0.3}
