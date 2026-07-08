"""TASK-030: the GPU vision pass uses the higher-res vision proxy when present
(far doubles players are undetectable at the 480p analysis proxy)."""
import json

from app import artifacts, config
from app.pipeline import gpu


def test_vision_proxy_is_a_signed_gpu_artifact():
    assert "vision_proxy.mp4" in artifacts.GPU_ARTIFACTS
    assert config.VISION_PROXY_HEIGHT > config.PROXY_HEIGHT


def _capture_payload(monkeypatch):
    captured = {}

    def fake_request(payload, log=print):
        captured.update(payload)
        return {"contract": gpu.CONTRACT, "rallies": []}

    monkeypatch.setattr(gpu, "_runpod_request", fake_request)
    monkeypatch.setattr(config, "RUNPOD_ENDPOINT_ID", "ep")
    monkeypatch.setattr(config, "RUNPOD_API_KEY", "key")
    monkeypatch.setattr(config, "PUBLIC_BASE_URL", "https://baddyai.com")
    monkeypatch.setattr(config, "GPU_ARTIFACT_TOKEN", "tok")
    return captured


def test_gpu_uses_vision_proxy_when_present(monkeypatch, tmp_path):
    captured = _capture_payload(monkeypatch)
    monkeypatch.setattr(config, "OUTPUTS", tmp_path)
    wd = tmp_path / "job1"
    wd.mkdir()
    (wd / "proxy.mp4").write_bytes(b"x")
    (wd / "vision_proxy.mp4").write_bytes(b"x")

    gpu.analyze(wd / "vision_proxy.mp4", wd, "badminton",
                [{"start": 0.0, "end": 4.0, "dur": 4.0}], tasks=["players", "pose"])
    assert "/job1/vision_proxy.mp4?" in captured["proxy_url"]


def test_gpu_falls_back_to_480_proxy_when_vision_proxy_missing(monkeypatch, tmp_path):
    captured = _capture_payload(monkeypatch)
    monkeypatch.setattr(config, "OUTPUTS", tmp_path)
    wd = tmp_path / "job2"
    wd.mkdir()
    (wd / "proxy.mp4").write_bytes(b"x")   # no vision proxy built (short source)

    gpu.analyze(wd / "vision_proxy.mp4", wd, "badminton",
                [{"start": 0.0, "end": 4.0, "dur": 4.0}], tasks=["players", "pose"])
    assert "/job2/proxy.mp4?" in captured["proxy_url"]
