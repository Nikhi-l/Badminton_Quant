"""Virtual-camera rendering.

Reads the ORIGINAL (full-res) frames for each selected rally, applies a smoothly
animated crop window centered on the tracked action (the 'fake zoom' a human editor
does with keyframes), and writes a vertical 1080x1920 clip with the court audio.
"""
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from .. import config
from . import media
from .track import FocusPath

FONT_CANDIDATES = [
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
]


def _font(size: int):
    for p in FONT_CANDIDATES:
        try:
            return ImageFont.truetype(p, size)
        except OSError:
            continue
    return ImageFont.load_default(size)


def _badge(text: str, sub: str) -> np.ndarray:
    """Lower-third rally badge: lime accent bar + glass panel, broadcast style."""
    f1, f2 = _font(52), _font(29)
    meas = ImageDraw.Draw(Image.new("RGBA", (8, 8)))
    w = int(max(meas.textlength(text, font=f1), meas.textlength(sub, font=f2))) + 88
    h = 138
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([0, 0, w - 1, h - 1], radius=20, fill=(6, 8, 12, 175))
    d.rounded_rectangle([0, 0, 10, h - 1], radius=5, fill=(183, 245, 66, 235))   # accent bar
    d.text((38, 12), text, font=f1, fill=(255, 255, 255, 245))
    d.text((40, 86), sub, font=f2, fill=(140, 230, 255, 225))
    return np.asarray(img, dtype=np.uint8)


_WORDMARK: np.ndarray | None = None


def _wordmark() -> np.ndarray:
    global _WORDMARK
    if _WORDMARK is None:
        f = _font(34)
        text = "BADDY ▸ AI HIGHLIGHTS"
        meas = ImageDraw.Draw(Image.new("RGBA", (8, 8)))
        w = int(meas.textlength(text, font=f)) + 10
        img = Image.new("RGBA", (w, 52), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        d.text((0, 0), text, font=f, fill=(255, 255, 255, 110))
        _WORDMARK = np.asarray(img, dtype=np.uint8)
    return _WORDMARK


def _blend(frame: np.ndarray, overlay: np.ndarray, x: int, y: int):
    h, w = overlay.shape[:2]
    region = frame[y:y + h, x:x + w].astype(np.float32)
    a = overlay[:, :, 3:4].astype(np.float32) / 255.0
    frame[y:y + h, x:x + w] = (region * (1 - a) + overlay[:, :, :3].astype(np.float32) * a).astype(np.uint8)


def _nearest_shuttle(annotations: dict | None, t: float) -> dict | None:
    if not annotations or not annotations.get("mask_enabled"):
        return None
    pts = annotations.get("shuttle") or []
    if not pts:
        return None
    best = min(pts, key=lambda p: abs(float(p.get("t", 0.0)) - t))
    if abs(float(best.get("t", 0.0)) - t) > 0.18:
        return None
    if float(best.get("confidence", 0.0)) < config.SHUTTLE_MASK_MIN_CONF:
        return None
    return best


def _draw_shuttle_mask(img: Image.Image, x: float, y: float, conf: float):
    if x < -20 or y < -20 or x > config.OUT_W + 20 or y > config.OUT_H + 20:
        return
    d = ImageDraw.Draw(img, "RGBA")
    r = int(24 + 18 * min(max(conf, 0.0), 1.0))
    cx, cy = int(round(x)), int(round(y))
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(183, 245, 66, 30),
              outline=(183, 245, 66, 230), width=5)
    d.ellipse([cx - 5, cy - 5, cx + 5, cy + 5], fill=(255, 255, 255, 235))


def _push(progress: float) -> float:
    """Gentle extra push-in over the rally on top of the adaptive zoom."""
    p = min(max(progress, 0.0), 1.0)
    s = p * p * (3 - 2 * p)
    return 1.0 + max(0.0, config.RENDER_ZOOM_PUSH) * s


def _punch(t_in: float) -> float:
    """Optional opening camera punch.

    It used to be a hardcoded 6% push, which made otherwise smooth paths read as
    a zoom pop at rally boundaries. Default is now 0 for smooth camera exports.
    """
    import math
    return 1.0 + max(0.0, config.RENDER_ZOOM_PUNCH) * math.exp(-max(t_in, 0.0) / 0.35)


def render_rally(src: str | Path, info: media.VideoInfo, t0: float, t1: float,
                 focus: FocusPath, out_path: str | Path, label: str, sub: str,
                 mirror: bool = False, annotations: dict | None = None) -> float:
    """Render one rally clip. Returns the clip duration in seconds."""
    W, H = info.width, info.height
    A = config.OUT_W / config.OUT_H
    if W / H > A:
        cw_max, ch_max = H * A, float(H)
    else:
        cw_max, ch_max = float(W), W / A

    badge = _badge(label, sub)
    mark = _wordmark()
    fps = config.OUT_FPS
    dur = t1 - t0
    writer = media.FrameWriter(out_path, config.OUT_W, config.OUT_H, fps, src, t0, t1)
    n_written = 0
    try:
        for i, frame in media.iter_frames(src, t0, t1, fps=fps):
            t = t0 + i / fps
            fx, fy, z = focus.at(t)
            z = min(z * _push((t - t0) / max(dur, 0.001)) * _punch(t - t0), 1.55)
            cw, ch = cw_max / z, ch_max / z
            cx = min(max(fx * W, cw / 2), W - cw / 2)
            cy = min(max(fy * H, ch / 2), H - ch / 2)
            x0, y0 = int(round(cx - cw / 2)), int(round(cy - ch / 2))
            x1, y1 = min(x0 + int(cw), W), min(y0 + int(ch), H)
            x0, y0 = max(0, x0), max(0, y0)
            crop = frame[y0:y1, x0:x1]
            img = Image.fromarray(crop).resize((config.OUT_W, config.OUT_H), Image.BILINEAR)
            shuttle = _nearest_shuttle(annotations, t)
            if shuttle:
                sx = (float(shuttle["x"]) * W - x0) / max(1, x1 - x0) * config.OUT_W
                sy = (float(shuttle["y"]) * H - y0) / max(1, y1 - y0) * config.OUT_H
                _draw_shuttle_mask(img, sx, sy, float(shuttle.get("confidence", 1.0)))
            arr = np.asarray(img, dtype=np.uint8)
            if mirror:   # flip the scene BEFORE overlays so badges stay readable
                arr = arr[:, ::-1]
            out = np.array(arr)  # writable, contiguous copy (asarray view is read-only)
            _blend(out, badge, 56, config.OUT_H - 130 - 72)
            _blend(out, mark, config.OUT_W - mark.shape[1] - 40, 54)
            writer.write(out)
            n_written += 1
    finally:
        writer.close()
    return n_written / fps
