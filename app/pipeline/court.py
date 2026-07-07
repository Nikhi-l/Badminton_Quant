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


def detect_from_video(video_path, samples: int = 3) -> dict:
    """Detect the court across a few frames of the (proxy) video and merge.

    The camera is effectively static for court footage, so the per-frame corner
    spread doubles as a confidence signal. Returns a canonical dict that is
    stored on the job result as ``result["court"]``.
    """
    cv2 = _cv2()
    if cv2 is None:
        return {"status": "unavailable", "message": "opencv not installed"}
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        return {"status": "unavailable", "message": f"cannot open {video_path}"}
    try:
        n = cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0
        picks = [int(n * f) for f in np.linspace(0.25, 0.75, samples)] if n else [0]
        found = []
        for idx in picks:
            cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
            ok, frame = cap.read()
            if not ok:
                continue
            det = detect_frame(frame)
            if det:
                found.append(det)
    finally:
        cap.release()
    if not found:
        return {"status": "not_found", "message": "no court boundary detected"}

    corners = np.median(np.asarray([d["corners"] for d in found], dtype=np.float64),
                        axis=0)
    spread = float(np.mean(np.std(np.asarray([d["corners"] for d in found]), axis=0))) \
        if len(found) > 1 else 0.0
    corner_list = [[round(float(x), 4), round(float(y), 4)] for x, y in corners]
    best = max(found, key=lambda d: d["score"])
    confidence = round(min(1.0, (len(found) / samples) * best["score"]
                           * max(0.2, 1.0 - spread * 12)), 3)
    return {
        "status": "ok",
        "corners": corner_list,
        "lines": best["lines"],
        "net": best.get("net"),
        "homography": solve_homography([tuple(c) for c in corner_list], COURT_PLANE),
        "court_size_m": [COURT_WIDTH_M, COURT_LENGTH_M],
        "confidence": confidence,
        "frames_used": len(found),
    }
