"""Procedural soundtrack: a copyright-free 120 BPM electronic bed with a strong
accent every 2 seconds (one bar), synthesized with numpy and written as WAV."""
import wave
from pathlib import Path

import numpy as np

SR = 44100


def _place(buf: np.ndarray, idx: int, wav: np.ndarray, gain: float = 1.0):
    if idx >= len(buf):
        return
    end = min(len(buf), idx + len(wav))
    buf[idx:end] += wav[: end - idx] * gain


def _kick() -> np.ndarray:
    t = np.arange(int(SR * 0.28)) / SR
    freq = 48 + 110 * np.exp(-t / 0.028)
    phase = 2 * np.pi * np.cumsum(freq) / SR
    return (np.sin(phase) * np.exp(-t / 0.16)).astype(np.float32)


def _hat(open_: bool = False) -> np.ndarray:
    n = int(SR * (0.14 if open_ else 0.05))
    rng = np.random.default_rng(7 if open_ else 3)
    noise = rng.standard_normal(n).astype(np.float32)
    noise = np.diff(noise, prepend=0.0)  # cheap high-pass
    env = np.exp(-np.arange(n) / (SR * (0.045 if open_ else 0.014)))
    return noise * env * 0.32

def _clap() -> np.ndarray:
    n = int(SR * 0.22)
    rng = np.random.default_rng(11)
    noise = rng.standard_normal(n).astype(np.float32)
    k = np.hanning(64).astype(np.float32)
    noise = np.convolve(np.diff(noise, prepend=0.0), k, mode="same")
    env = np.exp(-np.arange(n) / (SR * 0.055))
    return noise * env * 0.30


def _crash() -> np.ndarray:
    n = int(SR * 0.9)
    rng = np.random.default_rng(23)
    noise = rng.standard_normal(n).astype(np.float32)
    noise = np.diff(noise, prepend=0.0)
    env = np.exp(-np.arange(n) / (SR * 0.30))
    return noise * env * 0.25


def _bass_note(freq: float, dur: float) -> np.ndarray:
    n = int(SR * dur)
    t = np.arange(n) / SR
    saw = 2.0 * ((freq * t) % 1.0) - 1.0
    sub = np.sin(2 * np.pi * freq * 0.5 * t) * 0.6
    k = np.hanning(48).astype(np.float32)
    k /= k.sum()
    tone = np.convolve(saw.astype(np.float32), k, mode="same") + sub.astype(np.float32)
    env = np.minimum(1.0, np.arange(n) / (SR * 0.01)) * np.exp(-t / (dur * 0.9))
    return (tone * env * 0.5).astype(np.float32)


def build_track(duration: float, bpm: int = 120) -> np.ndarray:
    """Returns float32 stereo (n, 2) in -1..1."""
    beat = 60.0 / bpm                  # 0.5 s
    bar = beat * 4                     # 2.0 s — the accent grid
    n = int(SR * (duration + 0.6))
    kick_t, clap_t, hat_t, hat_o, crash_t, bass_t = (np.zeros(n, np.float32) for _ in range(6))

    kick, clap, hatc, hato, crash = _kick(), _clap(), _hat(), _hat(True), _crash()
    # A-minor loop: Am F C G — roots for each 2 s bar.
    roots = [55.0, 43.65, 65.41, 49.0]

    nbars = int(np.ceil(duration / bar)) + 1
    for b in range(nbars):
        t_bar = b * bar
        if b % 4 == 0:
            _place(crash_t, int(t_bar * SR), crash)
        note = roots[b % 4]
        for q in range(4):  # beats in bar
            t_beat = t_bar + q * beat
            _place(kick_t, int(t_beat * SR), kick)
            _place(hat_t, int((t_beat + beat / 2) * SR), hatc)
            if q in (1, 3):
                _place(clap_t, int(t_beat * SR), clap)
            if q == 3:
                _place(hat_o, int((t_beat + beat / 2) * SR), hato)
            for e in range(2):  # 8th-note bass pulses
                _place(bass_t, int((t_beat + e * beat / 2) * SR), _bass_note(note, 0.22))

    # Sidechain pump: duck bass after every kick.
    tt = np.arange(n) / SR
    duck = 1.0 - 0.55 * np.exp(-((tt % beat) / 0.09))
    bass_t *= duck.astype(np.float32)

    left = kick_t + clap_t + bass_t + hat_t * 0.7 + hat_o * 0.5 + crash_t * 1.0
    right = kick_t + clap_t + bass_t + hat_t * 1.0 + hat_o * 0.8 + crash_t * 0.7

    out = np.stack([left, right], axis=1)
    out = np.tanh(out * 1.4) * 0.85
    fade_in = int(SR * 0.15)
    out[:fade_in] *= np.linspace(0, 1, fade_in)[:, None]
    fade = int(SR * 2.5)
    if n > fade:
        out[-fade:] *= np.linspace(1, 0, fade)[:, None]
    return out[: int(SR * duration)].astype(np.float32)


def write_wav(path: str | Path, data: np.ndarray):
    pcm = (np.clip(data, -1, 1) * 32767).astype("<i2")
    with wave.open(str(path), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm.tobytes())
