"""TASK-022: court boundary detection + image→court-plane homography."""
import numpy as np
import pytest

cv2 = pytest.importorskip("cv2")

from app.pipeline import court  # noqa: E402

MAT = (52, 84, 24)      # BGR court green
LINE = (235, 235, 235)


def _draw_quad(img, tl, tr, br, bl, thickness=3):
    h, w = img.shape[:2]
    px = lambda p: (int(p[0] * w), int(p[1] * h))
    for a, b in ((tl, tr), (tr, br), (br, bl), (bl, tl)):
        cv2.line(img, px(a), px(b), LINE, thickness)


def _frame(w=960, h=540):
    img = np.zeros((h, w, 3), dtype=np.uint8)
    img[:] = MAT
    return img


def test_detects_axis_aligned_court():
    img = _frame()
    tl, tr, br, bl = (0.2, 0.16), (0.8, 0.16), (0.8, 0.92), (0.2, 0.92)
    _draw_quad(img, tl, tr, br, bl)
    cv2.line(img, (int(0.2 * 960), int(0.54 * 540)), (int(0.8 * 960), int(0.54 * 540)),
             (200, 200, 200), 4)   # net
    det = court.detect_frame(img)
    assert det is not None
    for got, want in zip(det["corners"], (tl, tr, br, bl)):
        assert abs(got[0] - want[0]) < 0.025 and abs(got[1] - want[1]) < 0.025
    assert det["net"] is not None


def test_detects_perspective_court_and_homography_maps_center():
    img = _frame()
    tl, tr, br, bl = (0.34, 0.22), (0.66, 0.22), (0.9, 0.88), (0.1, 0.88)
    _draw_quad(img, tl, tr, br, bl)
    det = court.detect_frame(img)
    assert det is not None
    for got, want in zip(det["corners"], (tl, tr, br, bl)):
        assert abs(got[0] - want[0]) < 0.03 and abs(got[1] - want[1]) < 0.03

    H = court.solve_homography([tuple(c) for c in det["corners"]], court.COURT_PLANE)
    # Corners land on the court-plane rectangle.
    u, v = court.project(H, *det["corners"][0])
    assert abs(u) < 0.15 and abs(v) < 0.15
    u, v = court.project(H, *det["corners"][2])
    assert abs(u - court.COURT_WIDTH_M) < 0.15 and abs(v - court.COURT_LENGTH_M) < 0.3
    # The diagonals' intersection is the court center under any homography.
    def _cross(a, b, c, d):
        seg1 = (a[0], a[1], b[0], b[1])
        seg2 = (c[0], c[1], d[0], d[1])
        return court._intersect(seg1, seg2)
    cx, cy = _cross(tl, br, tr, bl)
    u, v = court.project(H, cx, cy)
    assert abs(u - court.COURT_WIDTH_M / 2) < 0.2
    assert abs(v - court.COURT_LENGTH_M / 2) < 0.4


def test_rejects_frame_without_court():
    rng = np.random.default_rng(7)
    noise = rng.integers(0, 90, size=(540, 960, 3), dtype=np.uint8)
    assert court.detect_frame(noise) is None


def test_homography_roundtrip_identityish():
    src = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)]
    dst = court.COURT_PLANE
    H = court.solve_homography(src, dst)
    u, v = court.project(H, 0.5, 0.5)
    assert abs(u - court.COURT_WIDTH_M / 2) < 1e-6
    assert abs(v - court.COURT_LENGTH_M / 2) < 1e-6
