"""TASK-025a: monocular 3D shuttle reconstruction against a known ground truth.

A synthetic camera films a known drag-ballistic trajectory over the court; the
test hands rally3d only what production gets (2D track + court homography) and
checks the recovered 3D against the truth. Positions on the ground are compared
in the DETECTOR's court frame (via the homography), which sidesteps the left/
right mirror ambiguity every single-camera setup has.
"""
import numpy as np

from app.pipeline import court, rally3d

W, H, F = 1280, 720, 1400.0
CORNERS_WORLD = [(0.0, 0.0, 0.0), (6.1, 0.0, 0.0), (6.1, 13.4, 0.0), (0.0, 13.4, 0.0)]


def _gt_camera(C=(3.05, 19.0, 3.2)):
    C = np.array(C, dtype=float)
    target = np.array([3.05, 6.7, 1.0])
    fwd = target - C
    fwd = fwd / np.linalg.norm(fwd)
    up = np.array([0.0, 0.0, 1.0])
    x_cam = np.cross(fwd, up)
    x_cam = x_cam / np.linalg.norm(x_cam)
    y_cam = np.cross(fwd, x_cam)
    R = np.stack([x_cam, y_cam, fwd])   # rows: camera axes (world→cam)
    t = -R @ C
    return R, t, C


def _project(R, t, pts):
    p = (R @ np.asarray(pts, dtype=float).T).T + t
    return np.column_stack([F * p[:, 0] / p[:, 2] / W + 0.5,
                            F * p[:, 1] / p[:, 2] / H + 0.5])


def _detector_ordered_corners(img):
    """Order projected corners the way court.py labels them: far (top) pair
    first, left before right, then near-right, near-left."""
    idx = np.argsort(img[:, 1])
    top = sorted(idx[:2], key=lambda i: img[i, 0])
    bot = sorted(idx[2:], key=lambda i: img[i, 0])
    return [img[top[0]], img[top[1]], img[bot[1]], img[bot[0]]]


def _court_info(R, t):
    img = _project(R, t, CORNERS_WORLD)
    ordered = _detector_ordered_corners(img)
    hgr = court.solve_homography([tuple(c) for c in ordered], court.COURT_PLANE)
    return {"status": "ok", "homography": hgr, "corners": [list(c) for c in ordered]}


def _ground_frame(hgr, R, t, world_pt):
    """A world point ON THE GROUND expressed in the detector's court frame."""
    img = _project(R, t, [world_pt])[0]
    return court.project(hgr, img[0], img[1])


def test_camera_recovery_reprojects_court_corners():
    R, t, _ = _gt_camera()
    info = _court_info(R, t)
    cam = rally3d.camera_from_homography(info["homography"], W, H)
    assert cam is not None
    assert abs(cam["f"] - F) / F < 0.03
    assert float(cam["C"][2]) > 0.5          # camera above the ground: right-handed
    # Reproject the plane corners in the frame the camera actually uses (the
    # raw test homography is left-handed, so rally3d relabels x internally).
    plane = np.array([[x, y, 0.0] for x, y in court.COURT_PLANE])
    if cam["mirrored"]:
        plane[:, 0] = court.COURT_WIDTH_M - plane[:, 0]
    reproj = rally3d.project(cam, plane)
    err_px = np.abs(reproj - np.asarray(info["corners"])) * [W, H]
    assert float(err_px.max()) < 1.0


def test_court_py_normalizes_handedness(monkeypatch):
    # detect_from_video must store a RIGHT-handed homography, so downstream
    # consumers (heatmaps, marionettes, rally3d) share one frame.
    import cv2

    R, t, _ = _gt_camera(C=(3.05, 27.0, 8.0))   # far enough back to frame the court
    img = np.zeros((540, 960, 3), dtype=np.uint8)
    img[:] = (52, 84, 24)
    pts = _project(R, t, CORNERS_WORLD)
    quad = _detector_ordered_corners(pts)
    px = lambda p: (int(p[0] * 960), int(p[1] * 540))
    for a, b in zip(quad, quad[1:] + quad[:1]):
        cv2.line(img, px(a), px(b), (235, 235, 235), 3)
    monkeypatch.setattr(court, "_grab_frames", lambda *a, **k: [img, img, img])

    out = court.detect_from_video("ignored.mp4", gemini_fallback=False)
    assert out["status"] == "ok"
    assert rally3d.is_right_handed(out["homography"], 960, 540) is True


def test_reconstructs_known_shot_apex_speed_landing():
    R, t, _ = _gt_camera()
    info = _court_info(R, t)

    p0 = np.array([1.6, 11.2, 2.4])
    v0 = np.array([1.2, -9.5, 5.0])          # ~39 km/h clear toward the far court
    t0 = 10.0
    ts = np.arange(t0, t0 + 1.0, 0.1)
    gt = rally3d.simulate(p0, v0, t0, ts)
    assert gt[-1, 2] > 0.2                    # still airborne at the last sample

    rng = np.random.default_rng(11)
    img = _project(R, t, gt) + rng.normal(0, 0.3 / W, size=(len(gt), 2))
    shuttle = [{"t": float(tt), "x": float(x), "y": float(y), "confidence": 0.9}
               for tt, (x, y) in zip(ts, img)]

    out = rally3d.reconstruct_rally({"shuttle": shuttle}, info, (W, H))
    assert out["status"] == "ok" and len(out["shots"]) == 1
    shot = out["shots"][0]
    assert shot["residual_px"] < 5.0

    # Apex within 10% of truth (height is mirror-invariant).
    gt_apex = float(np.max(gt[:, 2]))
    assert abs(shot["peak_z"] - gt_apex) / gt_apex < 0.10
    # Launch speed within 12%.
    assert abs(shot["speed_kmh"] - float(np.linalg.norm(v0)) * 3.6) \
        / (float(np.linalg.norm(v0)) * 3.6) < 0.12

    # Landing: run both trajectories to the ground, compare in the frame the
    # reconstruction actually used (x mirrors when the raw homography was
    # left-handed — expected here, since the test bypasses court.py's
    # handedness normalization).
    long_ts = np.arange(t0, t0 + 4.0, 1 / 120)
    gt_long = rally3d.simulate(p0, v0, t0, long_ts)
    gt_land_w = gt_long[np.argmax(gt_long[:, 2] < 0.0)]
    gt_land = list(_ground_frame(info["homography"], R, t, gt_land_w))
    if out["mirrored_frame"]:
        gt_land[0] = court.COURT_WIDTH_M - gt_land[0]

    fit_long = rally3d.simulate(np.array(shot["p0"]), np.array(shot["v0"]), shot["t0"], long_ts)
    fit_land = fit_long[np.argmax(fit_long[:, 2] < 0.0)][:2]
    err = float(np.hypot(fit_land[0] - gt_land[0], fit_land[1] - gt_land[1]))
    assert err < 0.3, f"landing error {err:.2f}m"


def test_two_shots_split_and_fit():
    R, t, _ = _gt_camera()
    info = _court_info(R, t)
    ts1 = np.arange(5.0, 6.0, 0.1)
    ts2 = np.arange(6.05, 7.0, 0.1)
    a = rally3d.simulate(np.array([1.5, 11.0, 2.0]), np.array([0.8, -8.0, 4.0]), 5.0, ts1)
    b = rally3d.simulate(a[-1], np.array([-0.5, 8.5, 5.5]), float(ts1[-1]) + 0.05, ts2)
    pts = []
    for tt, p in list(zip(ts1, a)) + list(zip(ts2, b)):
        x, y = _project(R, t, [p])[0]
        pts.append({"t": float(tt), "x": float(x), "y": float(y), "confidence": 0.9})
    out = rally3d.reconstruct_rally({"shuttle": pts}, info, (W, H))
    assert out["status"] == "ok"
    assert len(out["shots"]) == 2
    assert out["fps"] == rally3d.REPLAY_FPS


def test_reconstruction_ignores_raw_teleports():
    """TASK-034 P0: 3D consumes the same filtered track as camera/Studio/export.
    A raw TrackNet teleport (a stadium light) used to reach the solver directly
    — splitting shots at a phantom 'hit' — while every display path hid it."""
    R, t, _ = _gt_camera()
    info = _court_info(R, t)
    p0 = np.array([1.6, 11.2, 2.4])
    v0 = np.array([1.2, -9.5, 5.0])
    t0 = 10.0
    ts = np.arange(t0, t0 + 1.0, 0.1)
    gt = rally3d.simulate(p0, v0, t0, ts)
    img = _project(R, t, gt)
    shuttle = [{"t": float(tt), "x": float(x), "y": float(y), "confidence": 0.9}
               for tt, (x, y) in zip(ts, img)]

    clean = rally3d.reconstruct_rally({"shuttle": shuttle}, info, (W, H))
    spiked = [dict(s) for s in shuttle]
    spiked.insert(5, {"t": float(ts[4]) + 0.05, "x": 0.97, "y": 0.03, "confidence": 0.9})
    out = rally3d.reconstruct_rally({"shuttle": spiked}, info, (W, H))

    assert clean["status"] == out["status"] == "ok"
    assert len(out["shots"]) == len(clean["shots"]) == 1
    assert abs(out["shots"][0]["residual_px"] - clean["shots"][0]["residual_px"]) < 0.5


def test_reconstruction_degrades_gracefully():
    assert rally3d.reconstruct_rally({"shuttle": []}, {"status": "not_found"}, (W, H))["status"] == "no_court"
    R, t, _ = _gt_camera()
    info = _court_info(R, t)
    assert rally3d.reconstruct_rally({"shuttle": []}, info, (W, H))["status"] == "no_track"
