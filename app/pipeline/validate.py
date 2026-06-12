"""Reel quality validation.

Two layers:
1. Heuristics (cheap, every sampled frame): black frames, flat/empty frames,
   frozen stretches — catches encoder/crop bugs.
2. Gemini spot-check (a few frames per clip): is this actually badminton being
   played, are players visible, is anyone badly cut off by the crop — catches
   "camera aimed at nothing" failures heuristics can't see.

Used per-clip after render (failing clips are re-rendered with a safe wide camera,
then dropped if still bad) and once on the final reel.
"""
import base64
import subprocess
from pathlib import Path

import numpy as np

from .. import config
from . import gemini, media

GEMINI_PROMPT = """You are auditing frames sampled from an automatically cropped racket/paddle
sport (badminton, pickleball, tennis...) highlight clip. The virtual camera sometimes fails:
it can point at empty court, a wall, or cut a player in half at the frame edge.

For EACH image, in the order given, report:
- "players_visible": how many players are visible enough to recognize (0, 1 or 2)
- "framing": "ok" | "player_cut" (a player is substantially cut off by the frame edge)
             | "empty" (no player visible / empty court / wall / ceiling) | "other"
- "note": max 6 words

Be strict about "empty", lenient about minor cropping at the very edge."""

GEMINI_PROMPT_POV = """You are auditing frames sampled from a FIRST-PERSON (POV) racket/paddle
sport highlight clip recorded by smart glasses worn by one of the players. The wearer is never
visible — seeing only the opponent, the ball/shuttle, the net or the court is NORMAL and GOOD.

For EACH image, in the order given, report:
- "players_visible": players visible (the opponent counts; 0 is acceptable mid-stroke)
- "framing": "ok" | "player_cut" (use ONLY if an opponent is grossly cut in half)
             | "empty" (ONLY if the view is clearly away from play: sky, floor, walls,
               unrelated surroundings — NOT the court or net)
- "note": max 6 words

Be lenient: POV footage is judged on "does this show the game being played", nothing more."""

GEMINI_SCHEMA = {
    "type": "ARRAY",
    "items": {
        "type": "OBJECT",
        "properties": {
            "players_visible": {"type": "INTEGER"},
            "framing": {"type": "STRING"},
            "note": {"type": "STRING"},
        },
        "required": ["players_visible", "framing"],
    },
}


def path_smoothness(fp, cw_norm: float, ch_norm: float) -> dict:
    """Acceleration audit of the virtual-camera path itself, in crop-relative units.
    Catches jerky pans and zoom pops BEFORE we spend minutes rendering."""
    xs, ys, zs = fp.xs.astype(np.float64), fp.ys.astype(np.float64), fp.zs.astype(np.float64)
    if len(xs) < 5:
        return {"ok": True, "ax99": 0, "ay99": 0, "az99": 0}
    hw = cw_norm / (2 * zs)
    hh = ch_norm / (2 * zs)
    p99 = lambda a: float(np.percentile(np.abs(a), 99))
    m = {
        "ax99": p99(np.diff(xs, 2) / hw[1:-1]),   # pan accel, fractions of crop width
        "ay99": p99(np.diff(ys, 2) / hh[1:-1]),
        "az99": p99(np.diff(zs, 2) / zs[1:-1]),   # zoom accel, relative
    }
    # Calibrated on known-smooth output (ax/ay ~0.016, az ~0.001) with 3x headroom;
    # the pixel-level motion_jerk gate on rendered video is the strict authority.
    m["ok"] = m["ax99"] < 0.05 and m["ay99"] < 0.05 and m["az99"] < 0.006
    return m


def _phase_shift(a: np.ndarray, b: np.ndarray):
    """Translation between two windowed gray frames via phase correlation."""
    A = np.fft.rfft2(a)
    B = np.fft.rfft2(b)
    R = A * np.conj(B)
    R /= np.abs(R) + 1e-9
    r = np.fft.irfft2(R, a.shape)
    dy, dx = np.unravel_index(int(np.argmax(r)), r.shape)
    h, w = a.shape
    if dy > h / 2:
        dy -= h
    if dx > w / 2:
        dx -= w
    return float(dx), float(dy)


def camera_motion_probe(path: str | Path, duration: float) -> float:
    """Median per-frame global motion (px @108p) sampled across the video —
    distinguishes tripod footage (~0.1-0.3) from handheld/POV (>1.0)."""
    shifts = []
    for k in range(3):
        t0 = duration * (0.2 + 0.3 * k)
        win = None
        prev = None
        for _, f in media.iter_frames(path, t0, min(t0 + 8, duration), fps=6,
                                      gray=True, scale_h=108):
            g = f.astype(np.float32)
            if win is None:
                win = np.outer(np.hanning(g.shape[0]), np.hanning(g.shape[1])).astype(np.float32)
            g = (g - g.mean()) * win
            if prev is not None:
                dx, dy = _phase_shift(prev, g)
                shifts.append(max(abs(dx), abs(dy)))
            prev = g
    return float(np.median(shifts)) if shifts else 0.0


def motion_jerk(path: str | Path, sample_fps: int = 15,
                exclude_times: list[float] | None = None,
                limit: float = 3.0) -> dict:
    """Pixel-level camera-motion audit of a rendered clip: estimate global motion
    between consecutive frames, then measure how violently it changes (jerk).
    exclude_times: intended hard cuts (clip joints in the reel) are not jerk."""
    dur = media.probe(path).duration
    win = None
    shifts = []
    prev = None
    for _, f in media.iter_frames(path, 0, dur, fps=sample_fps, gray=True, scale_h=108):
        g = f.astype(np.float32)
        if win is None:
            wy = np.hanning(g.shape[0]).astype(np.float32)
            wx = np.hanning(g.shape[1]).astype(np.float32)
            win = np.outer(wy, wx)
        g = (g - g.mean()) * win
        if prev is not None:
            shifts.append(_phase_shift(prev, g))
        prev = g
    if len(shifts) < 6:
        return {"ok": True, "jerk99": 0.0}
    s = np.array(shifts)
    jerk = np.abs(np.diff(s, axis=0)).max(axis=1)   # px @108p between consecutive motions
    keep = np.ones(len(jerk), bool)
    for j in range(len(jerk)):
        t = (j + 1) / sample_fps
        if any(abs(t - c) < 0.3 for c in (exclude_times or [])):
            keep[j] = False
    jerk = jerk[keep] if keep.any() else jerk
    out = {"jerk99": round(float(np.percentile(jerk, 99)), 2),
           "jerk_max": round(float(jerk.max()), 2)}
    out["ok"] = out["jerk99"] <= limit
    return out


def heuristics(path: str | Path, sample_fps: int = 4) -> dict:
    """Scan downscaled gray frames for black / flat / frozen segments."""
    dur = media.probe(path).duration
    issues = []
    prev = None
    frozen_run = longest_frozen = n = 0
    for i, f in media.iter_frames(path, 0, dur, fps=sample_fps, gray=True, scale_h=180):
        n += 1
        t = round(i / sample_fps, 1)
        if float(f.mean()) < 14:
            issues.append({"t": t, "kind": "black"})
        elif float(f.std()) < 7:
            issues.append({"t": t, "kind": "flat"})
        if prev is not None:
            d = float(np.abs(f.astype(np.int16) - prev.astype(np.int16)).mean())
            frozen_run = frozen_run + 1 if d < 0.22 else 0
            longest_frozen = max(longest_frozen, frozen_run)
        prev = f
    if longest_frozen >= sample_fps:  # >= 1s visually stuck
        issues.append({"t": -1, "kind": f"frozen_{longest_frozen / sample_fps:.1f}s"})
    hard = [i for i in issues if i["kind"] in ("black", "flat") or i["kind"].startswith("frozen")]
    return {"frames_checked": n, "issues": issues, "ok": n > 0 and not hard}


def _grab_jpeg(path: str | Path, t: float) -> bytes:
    out = subprocess.run(
        ["ffmpeg", "-v", "error", "-ss", f"{t:.2f}", "-i", str(path),
         "-frames:v", "1", "-vf", "scale=-2:360,format=yuvj420p", "-q:v", "6",
         "-strict", "unofficial", "-f", "image2pipe", "-c:v", "mjpeg", "-"],
        capture_output=True, check=True)
    return out.stdout


def gemini_review(path: str | Path, n_frames: int = 6, pov: bool = False) -> dict:
    """Ask Gemini to eyeball sampled frames. Returns {'ok': bool, 'frames': [...]}."""
    dur = media.probe(path).duration
    parts: list[dict] = [{"text": GEMINI_PROMPT_POV if pov else GEMINI_PROMPT}]
    ts = []
    for k in range(n_frames):
        t = (k + 0.5) * dur / n_frames
        try:
            jpg = _grab_jpeg(path, t)
        except subprocess.CalledProcessError:
            continue   # one unreadable frame shouldn't sink the audit
        ts.append(t)
        parts.append({"inlineData": {"mimeType": "image/jpeg",
                                     "data": base64.b64encode(jpg).decode()}})
    if not ts:
        return {"ok": True, "skipped": "frame extraction failed", "frames": []}
    try:
        text = gemini.generate(config.SEGMENT_MODEL, parts,
                               json_schema=GEMINI_SCHEMA, temperature=0.1)
        frames = gemini.parse_json(text)
    except gemini.GeminiError as e:
        # Vision audit unavailable shouldn't block delivery; heuristics still gate.
        return {"ok": True, "skipped": str(e)[:200], "frames": []}
    for f, t in zip(frames, ts):
        f["t"] = round(t, 1)
    if pov:   # wearer is never in frame — only true off-court views count as empty
        empties = [f for f in frames if f.get("framing") == "empty"]
        return {"ok": len(empties) <= max(1, len(ts) // 3), "frames": frames}
    empties = [f for f in frames if f.get("framing") == "empty" or f.get("players_visible", 0) == 0]
    cuts = [f for f in frames if f.get("framing") == "player_cut"]
    return {"ok": not empties and len(cuts) <= max(1, n_frames // 3), "frames": frames}


def validate_clip(path: str | Path, motion_limit: float = 3.0, pov: bool = False) -> dict:
    """motion_limit: 3.0 for tripod footage; raised for POV sources whose
    shake is in the recording itself, not a rendering defect. pov also relaxes
    the content audit (the wearer is never visible in first-person footage)."""
    h = heuristics(path)
    if not h["ok"]:
        return {"ok": False, "heuristics": h, "motion": None, "gemini": None}
    mj = motion_jerk(path, limit=motion_limit)
    if not mj["ok"]:
        return {"ok": False, "heuristics": h, "motion": mj, "gemini": None}
    g = gemini_review(path, pov=pov)
    return {"ok": g["ok"], "heuristics": h, "motion": mj, "gemini": g}
