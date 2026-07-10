"""TASK-032: 3D mapping flow — weak-CV acceptance floor, synthetic net,
failure-status surfacing, and per-rally recompute reasons."""
import numpy as np

from app.main import _public_rally
from app.pipeline import court


CORNERS = [[0.34, 0.22], [0.66, 0.22], [0.9, 0.88], [0.1, 0.88]]


def _fake_frames(monkeypatch, score):
    frames = [np.zeros((360, 640, 3), np.uint8)] * 3
    monkeypatch.setattr(court, "_grab_frames", lambda *_: frames)
    monkeypatch.setattr(court, "detect_frame",
                        lambda f: {"corners": CORNERS, "lines": [], "net": None,
                                   "score": score})
    monkeypatch.setattr(court, "_gemini_corners", lambda *a, **k: None)


def test_weak_cv_court_is_marked_low_confidence(monkeypatch):
    # confidence = (found/samples) * score * spread-factor = 1 * 0.3 * 1 = 0.3
    _fake_frames(monkeypatch, score=0.3)
    out = court.detect_from_video("ignored.mp4")
    assert out["status"] == "low_confidence"      # was silently "ok" pre-TASK-032
    assert out["corners"]                          # geometry kept for provisional UI
    assert "draw the corners" in out["message"]


def test_confident_cv_court_stays_ok(monkeypatch):
    _fake_frames(monkeypatch, score=0.8)
    out = court.detect_from_video("ignored.mp4")
    assert out["status"] == "ok"
    assert out["frame_wh"] == [640, 360]


def test_manual_court_gets_synthetic_net():
    out = court.manual_result(CORNERS, (1280, 720))
    net = out["net"]
    assert isinstance(net, list) and len(net) == 4
    # Net endpoints land on the court-plane midline through the homography.
    for x, y, want_u in ((net[0], net[1], None), (net[2], net[3], None)):
        u, v = court.project(out["homography"], x, y)
        assert abs(v - court.COURT_LENGTH_M / 2) < 0.05
        assert -0.1 <= u <= court.COURT_WIDTH_M + 0.1


def test_public_rally_forwards_slim_failure_status():
    out = _public_rally({
        "start": 0.0, "end": 5.0, "dur": 5.0,
        "rally_3d": {"status": "no_track", "message": "no shuttle points"},
    })
    assert out["rally_3d"] == {"status": "no_track", "message": "no shuttle points"}


def test_public_rally_forwards_ok_payload_untouched():
    r3 = {"status": "ok", "fps": 12, "shots": []}
    out = _public_rally({"start": 0.0, "end": 5.0, "dur": 5.0, "rally_3d": r3})
    assert out["rally_3d"] is r3
