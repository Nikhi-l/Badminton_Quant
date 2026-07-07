"""Court geometry: find the badminton court's boundary lines and corners in
source frames, and fit an image→court-plane homography from the known BWF
court dimensions.

Detection is classical CV — court lines are bright, low-saturation strokes on
the mat, so we mask them, pull long Hough segments, split them into
horizontal-ish (baselines, service lines, net) and side candidates by angle,
and intersect the extreme lines to get the outer quad. Cheap enough to run on
the VM for every job. A Gemini corner-refinement pass is queued as TASK-023
for ambiguous frames; this module stands alone so it can be unit-tested.

The homography maps normalized image points to court-plane METERS
(x across the 6.10m width, y along the 13.40m length, far baseline at y=0).
That projection powers court-space player heatmaps and the 3D rally view.

Corners are ordered [far-left, far-right, near-right, near-left] in image
space — i.e. top-left, top-right, bottom-right, bottom-left for a normal
behind-the-baseline camera.
"""
from __future__ import annotations

import numpy as np

COURT_WIDTH_M = 6.10    # doubles court width
COURT_LENGTH_M = 13.40  # full court length
# Court-plane targets for the ordered image corners.
COURT_PLANE = [(0.0, 0.0), (COURT_WIDTH_M, 0.0),
               (COURT_WIDTH_M, COURT_LENGTH_M), (0.0, COURT_LENGTH_M)]

DETECT_HEIGHT = 360     # downscale before detection; lines survive, cost doesn't


def _cv2():
    try:
        import cv2
        return cv2
    except ImportError:
        return None


def solve_homography(src: list[tuple[float, float]],
                     dst: list[tuple[float, float]]) -> list[float]:
    """DLT homography from 4+ point pairs; returns row-major 9 floats with
    H[2][2] == 1 so the JS side can apply it with plain arithmetic."""
    rows = []
    for (x, y), (u, v) in zip(src, dst):
        rows.append([x, y, 1, 0, 0, 0, -u * x, -u * y, -u])
        rows.append([0, 0, 0, x, y, 1, -v * x, -v * y, -v])
    _, _, vt = np.linalg.svd(np.asarray(rows, dtype=np.float64))
    H = vt[-1].reshape(3, 3)
    if abs(H[2, 2]) < 1e-12:
        raise ValueError("degenerate homography")
    H = H / H[2, 2]
    return [round(float(v), 8) for v in H.reshape(-1)]


def project(h: list[float], x: float, y: float) -> tuple[float, float]:
    """Apply a row-major homography to one normalized image point."""
    w = h[6] * x + h[7] * y + h[8]
    if abs(w) < 1e-9:
        return 0.0, 0.0
    return (h[0] * x + h[1] * y + h[2]) / w, (h[3] * x + h[4] * y + h[5]) / w


def _line_mask(frame_bgr: np.ndarray):
    """Bright + low-saturation pixels — court paint against the mat."""
    cv2 = _cv2()
    hsv = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2HSV)
    s, v = hsv[:, :, 1], hsv[:, :, 2]
    mask = ((v > 150) & (s < 90)).astype(np.uint8) * 255
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
    return mask


def _segments(mask: np.ndarray) -> list[tuple[float, float, float, float]]:
    cv2 = _cv2()
    h, w = mask.shape[:2]
    lines = cv2.HoughLinesP(mask, rho=1, theta=np.pi / 180, threshold=40,
                            minLineLength=int(w * 0.22), maxLineGap=10)
    if lines is None:
        return []
    return [tuple(float(v) for v in ln[0]) for ln in lines[:80]]


def _angle_deg(seg) -> float:
    x1, y1, x2, y2 = seg
    return abs(np.degrees(np.arctan2(y2 - y1, x2 - x1))) % 180


def _intersect(a, b) -> tuple[float, float] | None:
    """Intersection of two segments extended to infinite lines."""
    x1, y1, x2, y2 = a
    x3, y3, x4, y4 = b
    d = (x1 - x2) * (y3 - y4) - (y1 - y2) * (x3 - x4)
    if abs(d) < 1e-9:
        return None
    px = ((x1 * y2 - y1 * x2) * (x3 - x4) - (x1 - x2) * (x3 * y4 - y3 * x4)) / d
    py = ((x1 * y2 - y1 * x2) * (y3 - y4) - (y1 - y2) * (x3 * y4 - y3 * x4)) / d
    return px, py


def _quad_area(c: list[tuple[float, float]]) -> float:
    area = 0.0
    for i in range(4):
        x1, y1 = c[i]
        x2, y2 = c[(i + 1) % 4]
        area += x1 * y2 - x2 * y1
    return abs(area) / 2.0


def detect_frame(frame_bgr: np.ndarray) -> dict | None:
    """Detect the outer court quad in one BGR frame.

    Returns {corners, lines, net, score} with all coordinates normalized to the
    frame, or None when no plausible court is found.
    """
    cv2 = _cv2()
    if cv2 is None:
        return None
    H0, W0 = frame_bgr.shape[:2]
    scale = DETECT_HEIGHT / H0
    small = cv2.resize(frame_bgr, (int(W0 * scale), DETECT_HEIGHT))
    h, w = small.shape[:2]
    segs = _segments(_line_mask(small))
    if not segs:
        return None

    horiz = [s for s in segs if _angle_deg(s) < 28 or _angle_deg(s) > 152]
    sides = [s for s in segs if 28 <= _angle_deg(s) <= 152]
    if len(horiz) < 2 or len(sides) < 2:
        return None

    mid_y = lambda s: (s[1] + s[3]) / 2
    mid_x = lambda s: (s[0] + s[2]) / 2
    top = min(horiz, key=mid_y)
    bottom = max(horiz, key=mid_y)
    left = min(sides, key=mid_x)
    right = max(sides, key=mid_x)
    if mid_y(bottom) - mid_y(top) < h * 0.2:
        return None

    quad = []
    for a, b in ((top, left), (top, right), (bottom, right), (bottom, left)):
        p = _intersect(a, b)
        if p is None:
            return None
        quad.append(p)
    tl, tr, br, bl = quad
    corners = [tl, tr, br, bl]
    if _quad_area(corners) < w * h * 0.12:
        return None
    if not all(-0.15 * w <= x <= 1.15 * w and -0.15 * h <= y <= 1.15 * h
               for x, y in corners):
        return None

    # The net reads as a strong horizontal strictly inside the quad.
    inner = [s for s in horiz
             if mid_y(top) + h * 0.08 < mid_y(s) < mid_y(bottom) - h * 0.08]
    net = max(inner, key=lambda s: abs(s[2] - s[0])) if inner else None

    norm_pt = lambda x, y: [round(x / w, 4), round(y / h, 4)]
    norm_seg = lambda s: [round(s[0] / w, 4), round(s[1] / h, 4),
                          round(s[2] / w, 4), round(s[3] / h, 4)]
    boundary = [norm_seg(s) for s in (top, right, bottom, left)]
    score = min(1.0, 0.55 + 0.1 * min(len(horiz), 3) + 0.1 * min(len(sides), 2))
    return {
        "corners": [norm_pt(*p) for p in corners],
        "lines": boundary,
        "net": norm_seg(net) if net else None,
        "score": round(score, 3),
    }


# Below this confidence the classical result is weak enough to ask Gemini for
# a second opinion on the corners (TASK-023).
GEMINI_CONFIDENCE_FLOOR = 0.5

_CORNER_SCHEMA = {
    "type": "object",
    "properties": {
        "court_visible": {"type": "boolean"},
        "corners": {
            "type": "array",
            "minItems": 4,
            "maxItems": 4,
            "items": {
                "type": "object",
                "properties": {"x": {"type": "number"}, "y": {"type": "number"}},
                "required": ["x", "y"],
            },
        },
    },
    "required": ["court_visible"],
}

_CORNER_PROMPT = (
    "This is one frame of a badminton match video. Find the four corners of the "
    "OUTER court boundary (the doubles sidelines meeting the baselines — the "
    "outermost painted rectangle of the court the players are on). Return "
    "normalized image coordinates (0..1, x rightward, y downward), ordered: "
    "far-left corner, far-right corner, near-right corner, near-left corner "
    "(far = the baseline further from the camera). If you cannot confidently "
    "locate all four corners of one court, set court_visible=false."
)


def _grab_frames(video_path, samples: int) -> list:
    cv2 = _cv2()
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        return []
    frames = []
    try:
        n = cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0
        picks = [int(n * f) for f in np.linspace(0.25, 0.75, samples)] if n else [0]
        for idx in picks:
            cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
            ok, frame = cap.read()
            if ok:
                frames.append(frame)
    finally:
        cap.release()
    return frames


def _valid_quad(corners: list) -> bool:
    if len(corners) != 4:
        return False
    if not all(-0.15 <= x <= 1.15 and -0.15 <= y <= 1.15 for x, y in corners):
        return False
    return _quad_area(corners) >= 0.10   # normalized units: >=10% of the frame


def _gemini_corners(frames: list, log=print) -> list | None:
    """Ask Gemini for the outer court corners on each frame; median-merge.

    Returns [[x, y] * 4] (far-left, far-right, near-right, near-left) or None
    when the key is missing, the model can't see a court, or its output fails
    validation. Token usage lands in the job's gemini_usage automatically.
    """
    import base64

    from .. import config
    from . import gemini

    cv2 = _cv2()
    if cv2 is None or not config.GEMINI_API_KEY or not frames:
        return None
    per_frame = []
    for frame in frames:
        ok, jpg = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 85])
        if not ok:
            continue
        parts = [
            {"text": _CORNER_PROMPT},
            {"inlineData": {"mimeType": "image/jpeg",
                            "data": base64.b64encode(jpg.tobytes()).decode()}},
        ]
        try:
            data = gemini.parse_json(gemini.generate(
                config.COACH_MODEL, parts, json_schema=_CORNER_SCHEMA,
                temperature=0.0, max_tokens=1024))
        except Exception as e:  # noqa: BLE001 - fallback must never sink a job
            log(f"court: Gemini corner call failed ({type(e).__name__}: {e})")
            continue
        if not isinstance(data, dict) or not data.get("court_visible"):
            continue
        try:
            corners = [(float(c["x"]), float(c["y"])) for c in data.get("corners") or []]
        except (KeyError, TypeError, ValueError):
            continue
        if _valid_quad(corners):
            per_frame.append(corners)
    if not per_frame:
        return None
    med = np.median(np.asarray(per_frame, dtype=np.float64), axis=0)
    spread = float(np.mean(np.std(np.asarray(per_frame), axis=0))) if len(per_frame) > 1 else 0.0
    if spread > 0.08:   # frames disagree — camera cut or hallucination
        log(f"court: Gemini corners disagree across frames (spread {spread:.3f}) — rejected")
        return None
    corners = [[round(float(x), 4), round(float(y), 4)] for x, y in med]
    return corners if _valid_quad([tuple(c) for c in corners]) else None


def _result_from_corners(corners: list, source: str, confidence: float,
                         frames_used: int, lines=None, net=None) -> dict:
    return {
        "status": "ok",
        "corners": corners,
        "lines": lines or [],
        "net": net,
        "homography": solve_homography([tuple(c) for c in corners], COURT_PLANE),
        "court_size_m": [COURT_WIDTH_M, COURT_LENGTH_M],
        "confidence": round(confidence, 3),
        "frames_used": frames_used,
        "source": source,
    }


def detect_from_video(video_path, samples: int = 3, gemini_fallback: bool = True,
                      log=print) -> dict:
    """Detect the court across a few frames of the (proxy) video and merge.

    The camera is effectively static for court footage, so the per-frame corner
    spread doubles as a confidence signal. When the classical result is missing
    or weak (< GEMINI_CONFIDENCE_FLOOR), Gemini is asked for the four corners on
    the same frames (TASK-023) and the results are merged; ``source`` records
    provenance ("cv" | "gemini" | "cv+gemini"). Returns the canonical dict
    stored on the job result as ``result["court"]``.
    """
    cv2 = _cv2()
    if cv2 is None:
        return {"status": "unavailable", "message": "opencv not installed"}
    frames = _grab_frames(video_path, samples)
    if not frames:
        return {"status": "unavailable", "message": f"cannot read frames from {video_path}"}

    found = [d for d in (detect_frame(f) for f in frames) if d]
    cv_result = None
    if found:
        corners = np.median(np.asarray([d["corners"] for d in found], dtype=np.float64),
                            axis=0)
        spread = float(np.mean(np.std(np.asarray([d["corners"] for d in found]), axis=0))) \
            if len(found) > 1 else 0.0
        corner_list = [[round(float(x), 4), round(float(y), 4)] for x, y in corners]
        best = max(found, key=lambda d: d["score"])
        confidence = round(min(1.0, (len(found) / samples) * best["score"]
                               * max(0.2, 1.0 - spread * 12)), 3)
        cv_result = _result_from_corners(corner_list, "cv", confidence, len(found),
                                         lines=best["lines"], net=best.get("net"))

    if cv_result and cv_result["confidence"] >= GEMINI_CONFIDENCE_FLOOR:
        return cv_result
    if not gemini_fallback:
        return cv_result or {"status": "not_found", "message": "no court boundary detected"}

    g_corners = _gemini_corners(frames, log=log)
    if g_corners and cv_result:
        # Median-merge = midpoint of the two corner sets; both observed the court.
        merged = [[round((a[0] + b[0]) / 2, 4), round((a[1] + b[1]) / 2, 4)]
                  for a, b in zip(cv_result["corners"], g_corners)]
        return _result_from_corners(merged, "cv+gemini",
                                    max(cv_result["confidence"], 0.65),
                                    cv_result["frames_used"],
                                    lines=cv_result["lines"], net=cv_result.get("net"))
    if g_corners:
        return _result_from_corners(g_corners, "gemini", 0.6, len(frames))
    return cv_result or {"status": "not_found", "message": "no court boundary detected"}
