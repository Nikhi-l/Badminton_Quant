"""TASK-039: ambient-audio energy series + impact-peak detection (pure parts).

Racquet hits are sharp broadband transients well above the hall's median
floor; the extractor must find them, dedupe adjacent windows of the same hit,
and stay silent on flat audio. ffmpeg decoding is a thin wrapper and is not
exercised here — these tests feed PCM directly.
"""
import numpy as np

from app.pipeline.audio import SR, find_peaks, rms_series


def _pcm(dur_s=60.0, bursts=(), noise=0.01, burst_amp=0.6, burst_s=0.03, seed=7):
    rng = np.random.default_rng(seed)
    x = rng.normal(0.0, noise, int(dur_s * SR)).astype(np.float64)
    for t in bursts:
        i = int(t * SR)
        x[i:i + int(burst_s * SR)] += burst_amp
    return np.clip(x, -1, 1)


def test_finds_each_impact_once():
    series = rms_series(_pcm(bursts=(10.0, 25.0, 40.0)))
    peaks = find_peaks(series)
    assert len(peaks) == 3
    for want, got in zip((10.0, 25.0, 40.0), peaks):
        assert abs(got["t"] - want) < 0.25
        assert got["prominence_db"] > 15   # a real hit towers over the floor
    assert [p["t"] for p in peaks] == sorted(p["t"] for p in peaks)


def test_adjacent_windows_of_one_hit_dedupe():
    # Two bursts 0.3 s apart — inside min_gap_s, so they must report once.
    peaks = find_peaks(rms_series(_pcm(bursts=(20.0, 20.3))))
    assert len(peaks) == 1


def test_flat_audio_has_no_peaks():
    assert find_peaks(rms_series(_pcm(bursts=()))) == []
    assert rms_series(np.array([])) == []
    assert find_peaks([]) == []


def test_series_is_dbfs_with_floor():
    series = rms_series(np.zeros(SR))
    assert series and all(db <= -79.9 for _, db in series)   # silence floors, no -inf
