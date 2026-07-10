"""TASK-031: worker court gating + phantom-box removal + payload plumbing."""
import sys
import types
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]

# handler.py imports runpod/requests/cv2 at module scope; runpod isn't a dev
# dependency, so stub it before import (the gate logic under test is pure numpy).
sys.modules.setdefault("runpod", types.SimpleNamespace(serverless=types.SimpleNamespace(start=lambda *_: None)))
sys.modules.setdefault("requests", types.SimpleNamespace())
try:
    import cv2  # noqa: F401
except Exception:  # pragma: no cover - ultralytics brings cv2 in this venv
    sys.modules.setdefault("cv2", types.SimpleNamespace())
sys.path.insert(0, str(ROOT / "runpod_worker"))
import handler  # noqa: E402

CORNERS = [[0.30, 0.35], [0.70, 0.35], [0.85, 0.85], [0.15, 0.85]]


def _entry(cx, foot_y, conf=0.5, w=0.06, h=0.2):
    det = {"box": [cx - w / 2, foot_y - h, cx + w / 2, foot_y], "confidence": conf}
    return (det, None)


def test_court_polygon_expands_quad():
    poly = handler._court_polygon(CORNERS)
    assert poly is not None
    # expanded polygon contains the original corners strictly inside
    for x, y in CORNERS:
        assert handler._inside_polygon(x, y, poly)
    assert handler._court_polygon(None) is None
    assert handler._court_polygon([[0, 0], [1, 0]]) is None


def test_gate_drops_off_court_spectators_keeps_players():
    poly = handler._court_polygon(CORNERS)
    on_court = _entry(0.5, 0.8)
    far_player = _entry(0.5, 0.38)
    spectator = _entry(0.03, 0.5)         # far outside the sideline
    kept = handler._court_gate([on_court, spectator, far_player], poly)
    assert on_court in kept and far_player in kept
    assert spectator not in kept


def test_gate_fails_safe_when_everything_would_drop():
    poly = handler._court_polygon(CORNERS)
    outsiders = [_entry(0.02, 0.1), _entry(0.98, 0.1)]
    assert handler._court_gate(outsiders, poly) == outsiders
    assert handler._court_gate([], poly) == []
    entries = [_entry(0.5, 0.8)]
    assert handler._court_gate(entries, None) == entries


def test_phantom_placeholder_boxes_are_gone():
    # Regression tripwire: the hardcoded conf-0.12 placeholder boxes passed
    # every downstream gate and steered the camera to empty court.
    for rel in ("runpod_worker/handler.py", "app/pipeline/vision_local.py"):
        src = (ROOT / rel).read_text()
        assert "0.18, 0.12, 0.42, 0.95" not in src, rel


def test_payload_carries_court_corners(monkeypatch, tmp_path):
    from app.pipeline import gpu
    from app import config

    monkeypatch.setattr(config, "RUNPOD_ENDPOINT_ID", "ep")
    monkeypatch.setattr(config, "RUNPOD_API_KEY", "key")
    monkeypatch.setattr(config, "PUBLIC_BASE_URL", "https://example.test")
    monkeypatch.setattr(config, "GPU_ARTIFACT_TOKEN", "tok")
    captured = {}

    def fake_request(payload, log=print):
        captured.update(payload)
        return {}

    monkeypatch.setattr(gpu, "_runpod_request", fake_request)
    workdir = tmp_path / "job1"
    workdir.mkdir()
    (workdir / "proxy.mp4").write_bytes(b"x")
    out = gpu.analyze(workdir / "proxy.mp4", workdir, "badminton",
                      [{"start": 0.0, "end": 2.0, "dur": 2.0}],
                      tasks=["players", "pose"], court_corners=CORNERS)
    assert captured.get("court_corners") == CORNERS
    assert out.get("status") == "ok"
