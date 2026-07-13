"""TASK-044 Slice 0: cadence-preserving worker sampling.

The old 180-frame cap silently spread long rallies to ever-lower sampling
rates (60s → 3 Hz, 180s → 1 Hz) while BoT-SORT stayed tuned for 6 Hz. The cap
is now a safety ceiling (default 1080 ≈ 3 min at 6 Hz) and every rally reports
requested vs effective cadence plus an explicit degradation reason.
"""
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

sys.modules.setdefault("runpod", types.SimpleNamespace(serverless=types.SimpleNamespace(start=lambda *_: None)))
sys.modules.setdefault("requests", types.SimpleNamespace())
try:
    import cv2  # noqa: F401
except Exception:  # pragma: no cover
    sys.modules.setdefault("cv2", types.SimpleNamespace())
sys.path.insert(0, str(ROOT / "runpod_worker"))
import handler  # noqa: E402


def test_short_rally_keeps_requested_cadence():
    times, meta = handler._sample_times(10.0, 30.0)
    assert meta["sample_count"] == len(times) == 120
    assert meta["degraded"] == ""
    assert abs(meta["effective_sample_fps"] - handler.SAMPLE_FPS) < 0.1
    assert times[0] == 10.0 and abs(times[-1] - 30.0) < 1e-9


def test_sixty_second_rally_no_longer_degrades_to_3hz():
    """The regression the ceiling change exists for: 60s used to cap at 180
    samples (~3 Hz); it must now keep ~6 Hz."""
    times, meta = handler._sample_times(0.0, 60.0)
    assert meta["sample_count"] == 360
    assert meta["degraded"] == ""
    assert meta["effective_sample_fps"] > 5.5
    spacing = times[1] - times[0]
    assert abs(spacing - 1.0 / handler.SAMPLE_FPS) < 0.01


def test_pathological_rally_degrades_explicitly_at_ceiling():
    times, meta = handler._sample_times(0.0, 300.0)
    assert meta["sample_count"] == len(times) == handler.MAX_FRAMES_PER_RALLY
    assert meta["requested_frames"] == 1800
    assert meta["degraded"] == "frame_cap"
    assert meta["effective_sample_fps"] < handler.SAMPLE_FPS
    # endpoints preserved even when degraded
    assert times[0] == 0.0 and abs(times[-1] - 300.0) < 1e-9


def test_sampling_meta_contract_keys():
    _, meta = handler._sample_times(0.0, 5.0)
    assert set(meta) == {"requested_sample_fps", "effective_sample_fps",
                         "requested_frames", "sample_count", "frame_cap",
                         "degraded"}
    assert meta["requested_sample_fps"] == handler.SAMPLE_FPS
    assert meta["frame_cap"] == handler.MAX_FRAMES_PER_RALLY


def test_ceiling_default_covers_three_minutes_at_6hz():
    # 1080 frames at 6 Hz = 180 s of true-cadence rally; the audio-impact veto
    # (TASK-042) makes longer windows a segmentation bug, not a real rally.
    assert handler.MAX_FRAMES_PER_RALLY >= 1080
