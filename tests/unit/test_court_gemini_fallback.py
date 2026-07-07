"""TASK-023: Gemini corner refinement when classical court detection is weak."""
import json

import numpy as np
import pytest

cv2 = pytest.importorskip("cv2")

from app import config  # noqa: E402
from app.pipeline import court, gemini  # noqa: E402

MAT = (52, 84, 24)
LINE = (235, 235, 235)
QUAD = [(0.3, 0.2), (0.7, 0.2), (0.9, 0.88), (0.1, 0.88)]


def _court_frame(w=960, h=540):
    img = np.zeros((h, w, 3), dtype=np.uint8)
    img[:] = MAT
    px = lambda p: (int(p[0] * w), int(p[1] * h))
    tl, tr, br, bl = QUAD
    for a, b in ((tl, tr), (tr, br), (br, bl), (bl, tl)):
        cv2.line(img, px(a), px(b), LINE, 3)
    return img


def _noise_frame(w=960, h=540, seed=3):
    rng = np.random.default_rng(seed)
    return rng.integers(0, 90, size=(h, w, 3), dtype=np.uint8)


def _gemini_json(corners, visible=True):
    return json.dumps({"court_visible": visible,
                       "corners": [{"x": c[0], "y": c[1]} for c in corners]})


@pytest.fixture
def api_key(monkeypatch):
    monkeypatch.setattr(config, "GEMINI_API_KEY", "test-key")


def test_strong_cv_skips_gemini(monkeypatch, api_key):
    def boom(*a, **k):
        raise AssertionError("Gemini must not be called when CV is confident")
    monkeypatch.setattr(gemini, "generate", boom)
    monkeypatch.setattr(court, "_grab_frames", lambda *a, **k: [_court_frame() for _ in range(3)])

    out = court.detect_from_video("ignored.mp4")
    assert out["status"] == "ok" and out["source"] == "cv"
    assert out["confidence"] >= court.GEMINI_CONFIDENCE_FLOOR


def test_gemini_rescues_undetected_court(monkeypatch, api_key):
    monkeypatch.setattr(gemini, "generate",
                        lambda *a, **k: _gemini_json(QUAD))
    monkeypatch.setattr(court, "_grab_frames", lambda *a, **k: [_noise_frame(seed=s) for s in (1, 2, 3)])

    out = court.detect_from_video("ignored.mp4")
    assert out["status"] == "ok" and out["source"] == "gemini"
    assert len(out["corners"]) == 4 and out["homography"]
    # Homography still maps the quad onto the court plane.
    u, v = court.project(out["homography"], *out["corners"][2])
    assert abs(u - court.COURT_WIDTH_M) < 0.2 and abs(v - court.COURT_LENGTH_M) < 0.3


def test_weak_cv_merges_with_gemini(monkeypatch, api_key):
    # Only 1 of 3 frames has a detectable court → CV confidence ~0.32 (< floor).
    frames = [_court_frame(), _noise_frame(seed=5), _noise_frame(seed=6)]
    monkeypatch.setattr(court, "_grab_frames", lambda *a, **k: frames)
    shifted = [(x + 0.02, y) for x, y in QUAD]   # Gemini sees slightly-off corners
    monkeypatch.setattr(gemini, "generate", lambda *a, **k: _gemini_json(shifted))

    out = court.detect_from_video("ignored.mp4")
    assert out["status"] == "ok" and out["source"] == "cv+gemini"
    # Merged = midpoint → x lands between the CV corner and the shifted one.
    assert abs(out["corners"][0][0] - (QUAD[0][0] + shifted[0][0]) / 2) < 0.02


def test_malformed_and_invisible_gemini_output_rejected(monkeypatch, api_key):
    monkeypatch.setattr(court, "_grab_frames", lambda *a, **k: [_noise_frame()])
    for payload in (
        "not json at all",
        json.dumps({"court_visible": False}),
        json.dumps({"court_visible": True, "corners": [{"x": 9, "y": 9}] * 4}),  # off-frame
        _gemini_json([(0.5, 0.5), (0.52, 0.5), (0.52, 0.52), (0.5, 0.52)]),      # tiny quad
    ):
        monkeypatch.setattr(gemini, "generate",
                            (lambda _p: lambda *a, **k: _p)(payload))
        out = court.detect_from_video("ignored.mp4")
        assert out["status"] == "not_found", payload


def test_no_api_key_keeps_cv_behavior(monkeypatch):
    monkeypatch.setattr(config, "GEMINI_API_KEY", "")
    monkeypatch.setattr(court, "_grab_frames", lambda *a, **k: [_noise_frame()])
    out = court.detect_from_video("ignored.mp4")
    assert out["status"] == "not_found"
