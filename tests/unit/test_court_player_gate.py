"""TASK-042: court-polygon player gate.

Owner spec: "if we have the court dimensions, we only track people that are
inside that court". Player FEET live on the floor quad (unlike the airborne
shuttle), so the full expanded quad is a safe deterministic gate — background
courts can't reach the camera, the evaluator, or the Studio. Must fail open
without a court or when the geometry contradicts most detections.
"""
from app.pipeline.track import court_player_gate

# a main court occupying the right-center band (the owner's real corners from
# job 1faaa5e4a02f, rounded)
CORNERS = [[0.72, 0.53], [0.31, 0.56], [0.40, 0.66], [0.99, 0.60]]


def _box(cx, y2, w=0.06, h=0.14, conf=0.8, tid=None):
    b = {"x1": cx - w / 2, "y1": y2 - h, "x2": cx + w / 2, "y2": y2,
         "confidence": conf}
    if tid is not None:
        b["track_id"] = tid
    return b


def _pose(cx, ankle_y, conf=0.7):
    kps = [{"x": cx, "y": ankle_y - 0.1, "confidence": 0.9}] * 15
    kps += [{"x": cx - 0.01, "y": ankle_y, "confidence": 0.9},
            {"x": cx + 0.01, "y": ankle_y, "confidence": 0.9}]
    return {"confidence": conf, "keypoints": kps}


def test_gate_drops_background_court_players():
    # 4 main-court players (feet on the quad) + 2 on a court to the left
    frames = [{"t": i / 6.0, "boxes": [
        _box(0.55, 0.64, tid=1), _box(0.75, 0.62, tid=2),
        _box(0.50, 0.56, tid=3), _box(0.62, 0.555, tid=4),
        _box(0.10, 0.45, tid=7), _box(0.18, 0.40, tid=8),
    ]} for i in range(20)]
    poses = [{"t": f["t"], "people": [
        _pose(0.55, 0.64), _pose(0.75, 0.62), _pose(0.12, 0.44)]} for f in frames]
    gp, gpo = court_player_gate(frames, poses, CORNERS)
    assert all(len(f["boxes"]) == 4 for f in gp)
    assert all(all(b["x1"] > 0.25 for b in f["boxes"]) for f in gp)
    assert all(len(f["people"]) == 2 for f in gpo)


def test_gate_keeps_baseline_lunge_outside_lines():
    # near player lunging past the near baseline: foot slightly below the quad
    frames = [{"t": 0.0, "boxes": [_box(0.70, 0.685)]}]
    gp, _ = court_player_gate(frames, [], CORNERS)
    assert gp and len(gp[0]["boxes"]) == 1


def test_gate_fails_open_without_corners_and_on_bad_geometry():
    frames = [{"t": 0.0, "boxes": [_box(0.1, 0.2), _box(0.15, 0.25)]}]
    poses = [{"t": 0.0, "people": [_pose(0.1, 0.2)]}]
    gp, gpo = court_player_gate(frames, poses, None)
    assert gp is frames and gpo is poses
    # corners drawn on some other framing: everyone is "outside" → distrust quad
    gp, gpo = court_player_gate(frames, poses, CORNERS)
    assert gp is frames and gpo is poses


def test_gate_caps_at_four_and_prefers_confidence():
    boxes = [_box(0.5 + 0.04 * i, 0.60, conf=0.5 + 0.08 * i) for i in range(5)]
    gp, _ = court_player_gate([{"t": 0.0, "boxes": boxes}], [], CORNERS)
    kept = gp[0]["boxes"]
    assert len(kept) == 4
    assert min(b["confidence"] for b in kept) >= 0.58   # weakest one dropped


def test_pose_foot_falls_back_to_bbox_bottom():
    # keypoints all low-confidence → bbox bottom decides
    person = {"confidence": 0.6,
              "keypoints": [{"x": 0.5, "y": 0.3, "confidence": 0.01}] * 17,
              "bbox": {"x1": 0.5, "y1": 0.45, "x2": 0.6, "y2": 0.62,
                       "confidence": 0.6}}
    inside = [{"t": 0.0, "people": [person]}]
    # anchor boxes keep the gate's fail-open stats happy
    frames = [{"t": 0.0, "boxes": [_box(0.55, 0.60)]}]
    _, gpo = court_player_gate(frames, inside, CORNERS)
    assert gpo and len(gpo[0]["people"]) == 1
