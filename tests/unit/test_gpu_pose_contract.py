from app.pipeline import gpu


def _keypoints(conf=0.9):
    return [
        {"x": 0.4 + (i % 3) * 0.01, "y": 0.3 + (i // 3) * 0.02, "confidence": conf}
        for i in range(17)
    ]


def test_canonicalize_preserves_pose_keypoints():
    raw = {
        "contract": "baddy.vision.v1",
        "model_status": {
            "pose_model": "yolo26m-pose.pt",
            "pose_requested_model": "yolo26m-pose.pt",
            "pose_backend": "runpod",
            "pose_device": "0",
            "pose_load_status": "loaded",
        },
        "rallies": [{
            "rally_index": 1,
            "pose_quality": 0.82,
            "frames": [{
                "t": 10.1,
                "players": [{"box": [0.2, 0.1, 0.4, 0.8], "confidence": 0.88}],
                "poses": [{"confidence": 0.91, "keypoints": _keypoints()}],
            }],
        }],
    }

    out = gpu._canonicalize(raw, [{"start": 10.0, "end": 14.0, "dur": 4.0}])

    rally = out["rallies"][0]
    assert rally["pose_samples"] == 1
    assert rally["pose_quality"] == 0.82
    person = rally["poses"][0]["people"][0]
    assert person["confidence"] == 0.91
    assert len(person["keypoints"]) == 17
    assert person["bbox"] == {"x1": 0.2, "y1": 0.1, "x2": 0.4, "y2": 0.8, "confidence": 0.88}
    assert out["models"]["pose"]["model"] == "yolo26m-pose.pt"
    assert out["models"]["pose"]["backend"] == "runpod"


def test_canonicalize_accepts_bare_keypoint_list_as_one_person():
    raw = {
        "rallies": [{
            "rally_index": 1,
            "frames": [{"t": 0.5, "keypoints": _keypoints(conf=0.75)}],
        }],
    }

    out = gpu._canonicalize(raw, [{"start": 0.0, "end": 2.0, "dur": 2.0}])

    people = out["rallies"][0]["poses"][0]["people"]
    assert len(people) == 1
    assert len(people[0]["keypoints"]) == 17
