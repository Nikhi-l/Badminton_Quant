"""Ambient-audio energy analysis (TASK-039): the soundtrack knows when play happens.

Racquet impacts are sharp broadband transients over a diffuse hall floor;
rest periods (walking, shuttle pickup, chatter) are quiet and smooth. This
module extracts a mono RMS energy series from the court audio and finds
impact-like peaks — candidate hit/smash markers that cost no GPU and survive
camera angles that defeat vision.

Nothing here drives highlight selection or rally boundaries yet: the pipeline
STORES the series + peaks (result["audio"], surfaced in analysis.json) so the
data exists for every processed job and the in-play/highlight fusion work
(see docs/reviews/2026-07-12-rally-break-inplay-audit.md) starts from real
measurements, not re-runs.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import numpy as np

SR = 16000            # analysis sample rate (mono)
WIN_S = 0.10          # RMS window
HOP_S = 0.05          # RMS hop — 20 values/s keeps transients visible
STORE_HOP_S = 0.25    # stored-series resolution (max-pooled from the fine hop)
FFMPEG = "ffmpeg"


def rms_series(pcm: np.ndarray, sr: int = SR, win_s: float = WIN_S,
               hop_s: float = HOP_S) -> list[tuple[float, float]]:
    """Windowed RMS energy in dBFS: [(t_center, db)], t in seconds.

    db is 20·log10(rms) of float samples in [-1, 1]; digital silence floors at
    -80 dB so downstream math never sees -inf.
    """
    if pcm.size == 0 or sr <= 0:
        return []
    x = pcm.astype(np.float64)
    win = max(1, int(win_s * sr))
    hop = max(1, int(hop_s * sr))
    out = []
    for start in range(0, max(1, len(x) - win + 1), hop):
        seg = x[start:start + win]
        rms = float(np.sqrt(np.mean(seg * seg)))
        db = 20.0 * np.log10(max(rms, 1e-4))   # -80 dB floor
        out.append((round((start + win / 2) / sr, 3), round(db, 2)))
    return out


def find_peaks(series: list[tuple[float, float]], min_prominence_db: float = 8.0,
               min_gap_s: float = 0.6, top_n: int = 60) -> list[dict]:
    """Impact-like peaks: local maxima ≥ min_prominence_db above the median
    floor, deduplicated so two windows of the same hit don't double-report.

    Returns [{t, db, prominence_db}] sorted by time. The median (not mean)
    floor makes the threshold robust to how loud the hall is overall — the
    same reason the tracking filters normalize by median step.
    """
    if len(series) < 3:
        return []
    ts = np.array([s[0] for s in series])
    db = np.array([s[1] for s in series])
    floor = float(np.median(db))
    cand = []
    for i in range(1, len(db) - 1):
        if db[i] >= db[i - 1] and db[i] > db[i + 1] and db[i] - floor >= min_prominence_db:
            cand.append((float(db[i] - floor), float(ts[i]), float(db[i])))
    cand.sort(reverse=True)              # strongest first for dedupe priority
    picked: list[tuple[float, float, float]] = []
    for prom, t, level in cand:
        if any(abs(t - p[1]) < min_gap_s for p in picked):
            continue
        picked.append((prom, t, level))
        if len(picked) >= top_n:
            break
    picked.sort(key=lambda p: p[1])
    return [{"t": round(t, 2), "db": round(level, 1), "prominence_db": round(prom, 1)}
            for prom, t, level in picked]


def _extract_pcm(video: str | Path) -> np.ndarray | None:
    """Decode the first audio stream to mono 16 kHz float32, or None if the
    file has no (decodable) audio."""
    try:
        proc = subprocess.run(
            [FFMPEG, "-v", "error", "-i", str(video), "-map", "0:a:0?", "-vn",
             "-ac", "1", "-ar", str(SR), "-f", "s16le", "-"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=600, check=True)
    except (subprocess.SubprocessError, OSError):
        return None
    if not proc.stdout:
        return None
    return np.frombuffer(proc.stdout, dtype=np.int16).astype(np.float32) / 32768.0


def analyze_file(video: str | Path, log=print) -> dict:
    """Energy series + impact peaks for a video's ambient audio.

    Stored shape: {"status": "ok"|"no_audio"|"failed", "hop_s", "series":
    [[t, db], ...] (max-pooled to STORE_HOP_S so a 10-min game is ~2400
    entries), "peaks": [{t, db, prominence_db}]}. Max pooling (not averaging)
    preserves the transient the coarser series exists to show.
    """
    pcm = _extract_pcm(video)
    if pcm is None or pcm.size < SR // 2:
        return {"status": "no_audio", "hop_s": STORE_HOP_S, "series": [], "peaks": []}
    try:
        fine = rms_series(pcm)
        # 160: the default 60 visibly truncated a 4.5-min game (TASK-042) and
        # the peaks now feed rally-boundary refinement, not just display
        peaks = find_peaks(fine, top_n=160)
        stride = max(1, int(round(STORE_HOP_S / HOP_S)))
        pooled = []
        for i in range(0, len(fine), stride):
            chunk = fine[i:i + stride]
            t = chunk[len(chunk) // 2][0]
            pooled.append([round(t, 2), round(max(c[1] for c in chunk), 1)])
        log(f"audio: {len(peaks)} impact-like peaks over {len(pooled) * STORE_HOP_S:.0f}s")
        return {"status": "ok", "hop_s": STORE_HOP_S, "series": pooled, "peaks": peaks}
    except Exception as e:  # noqa: BLE001 - audio analytics must never sink a job
        return {"status": "failed", "message": f"{type(e).__name__}: {e}",
                "hop_s": STORE_HOP_S, "series": [], "peaks": []}
