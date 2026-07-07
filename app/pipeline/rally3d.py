"""Monocular 3D rally reconstruction (TASK-025a).

From ONE fixed camera we already know two things: the court homography
(``court.py`` — image plane ↔ court-plane meters) and the shuttle's 2D track
(TrackNetV3). This module turns them into 3D:

1. **Camera pose from the court.** The homography fixes the ground plane; with
   square pixels + a centered principal point, plane-based calibration (Zhang)
   recovers focal length, rotation, and camera center. Every image point then
   defines a world ray.
2. **Shuttle 3D by physics.** The 2D track is split into shots at direction
   reversals (hits). Each shot is a ballistic-with-drag trajectory
   (a = g − k·|v|·v, k≈0.25 m⁻¹ for a shuttlecock) with 6 unknowns (p0, v0),
   fit by Levenberg–Marquardt (numpy-only) so its reprojection matches the
   observed 2D points along the rays.

Output is presentation-only (`result["rallies"][i]["rally_3d"]`): it feeds the
Studio's toggleable low-fps 3D replay and never influences the render/camera.
Sampled at REPLAY_FPS to match the review requirement ("keep it at low fps").
"""
from __future__ import annotations

import math

import numpy as np

from . import court as court_mod

G = 9.81
K_DRAG = 0.25          # shuttle drag: terminal velocity ≈ √(g/k) ≈ 6.3 m/s
REPLAY_FPS = 12        # sim sample rate for the 3D replay layer
MIN_SEG_POINTS = 5
MIN_SEG_DUR = 0.22
MAX_SEGMENTS = 24


# ------------------------------------------------------------- camera recovery

# x → 6.1−x on the court plane: relabels which sideline is "x=0". One camera
# cannot tell true left from right; what matters is a RIGHT-HANDED frame
# (camera above the ground with z up), which one of the two labelings gives.
MIRROR_X = np.array([[-1.0, 0.0, court_mod.COURT_WIDTH_M],
                     [0.0, 1.0, 0.0],
                     [0.0, 0.0, 1.0]])


def _decompose(h_mat: np.ndarray, w: int, h: int) -> dict | None:
    # court → centered PIXELS: x_pix = W·x_norm − W/2, y_pix = H·y_norm − H/2
    try:
        Hn = np.linalg.inv(h_mat)
    except np.linalg.LinAlgError:
        return None
    S = np.array([[w, 0.0, -w / 2.0], [0.0, h, -h / 2.0], [0.0, 0.0, 1.0]])
    Hc = S @ Hn
    h1, h2, h3 = Hc[:, 0], Hc[:, 1], Hc[:, 2]

    f2 = []
    denom = h1[2] * h2[2]
    if abs(denom) > 1e-9:
        cand = -(h1[0] * h2[0] + h1[1] * h2[1]) / denom
        if cand > 1.0:
            f2.append(cand)
    denom = h2[2] ** 2 - h1[2] ** 2
    if abs(denom) > 1e-9:
        cand = (h1[0] ** 2 + h1[1] ** 2 - h2[0] ** 2 - h2[1] ** 2) / denom
        if cand > 1.0:
            f2.append(cand)
    if not f2:
        return None
    f = float(np.sqrt(np.mean(f2)))

    Kinv = np.diag([1.0 / f, 1.0 / f, 1.0])
    r1 = Kinv @ h1
    r2 = Kinv @ h2
    lam = 2.0 / (np.linalg.norm(r1) + np.linalg.norm(r2))
    r1, r2, t = r1 * lam, r2 * lam, (Kinv @ h3) * lam
    # Cheirality: the court center must sit in FRONT of the camera.
    center_cam_z = (r1 * 3.05 + r2 * 6.7 + t)[2]
    if center_cam_z < 0:
        r1, r2, t = -r1, -r2, -t
    r3 = np.cross(r1, r2)
    R = np.column_stack([r1, r2, r3])
    U, _, Vt = np.linalg.svd(R)
    R = U @ Vt
    if np.linalg.det(R) < 0:
        R = U @ np.diag([1.0, 1.0, -1.0]) @ Vt
    C = -R.T @ t
    if not (0.5 <= C[2] <= 60.0):   # implausible camera height → bad geometry
        return None
    return {"f": f, "R": R, "t": t, "C": C, "w": w, "h": h}


def camera_from_homography(h_img2court: list[float], w: int, h: int) -> dict | None:
    """Recover {f, R, C, t} from the image→court homography (normalized coords).

    A detector-ordered corner set can define a LEFT-handed court frame (the
    image mirrors x for half of all camera placements); a proper rotation then
    puts the camera underground. In that case the x-mirrored labeling is the
    right-handed one — the returned cam carries ``mirrored=True`` and
    ``homography`` (the corrected image→court mapping actually used).
    Returns None when the homography is degenerate or has no positive focal
    solution. R maps world→camera; C is the camera center in court meters.
    """
    h_mat = np.asarray(h_img2court, dtype=np.float64).reshape(3, 3)
    cam = _decompose(h_mat, w, h)
    if cam is not None:
        cam["mirrored"] = False
        cam["homography"] = [round(float(v), 8) for v in h_mat.reshape(-1)]
        return cam
    h_mirror = MIRROR_X @ h_mat
    cam = _decompose(h_mirror, w, h)
    if cam is not None:
        cam["mirrored"] = True
        cam["homography"] = [round(float(v), 8) for v in h_mirror.reshape(-1)]
    return cam


def is_right_handed(h_img2court: list[float], w: int, h: int) -> bool | None:
    """Whether this image→court homography defines a right-handed frame
    (camera above the ground). None when undecidable (degenerate geometry)."""
    cam = camera_from_homography(h_img2court, w, h)
    if cam is None:
        return None
    return not cam["mirrored"]


def project(cam: dict, pts: np.ndarray) -> np.ndarray:
    """World meters (N,3) → normalized image coords (N,2)."""
    p = (cam["R"] @ pts.T).T + cam["t"]
    z = np.maximum(p[:, 2], 1e-6)
    u = cam["f"] * p[:, 0] / z
    v = cam["f"] * p[:, 1] / z
    return np.column_stack([u / cam["w"] + 0.5, v / cam["h"] + 0.5])


def ray(cam: dict, x: float, y: float) -> tuple[np.ndarray, np.ndarray]:
    """Normalized image point → (origin, unit direction) in world meters."""
    d_cam = np.array([(x - 0.5) * cam["w"] / cam["f"],
                      (y - 0.5) * cam["h"] / cam["f"], 1.0])
    d = cam["R"].T @ d_cam
    return cam["C"], d / np.linalg.norm(d)


def ray_point_at_height(cam: dict, x: float, y: float, z: float) -> np.ndarray | None:
    o, d = ray(cam, x, y)
    if abs(d[2]) < 1e-6:
        return None
    s = (z - o[2]) / d[2]
    return o + s * d if s > 0 else None


# ----------------------------------------------------------- shuttle segments

def split_shots(points: list[dict]) -> list[list[dict]]:
    """Split the 2D shuttle track into shots at hits (sharp direction changes)
    and detector gaps. Points: [{t, x, y, confidence}] sorted by t."""
    pts = [p for p in points if float(p.get("confidence", 1.0)) >= 0.3]
    pts.sort(key=lambda p: float(p["t"]))
    if len(pts) < MIN_SEG_POINTS:
        return []
    segs: list[list[dict]] = [[pts[0]]]
    prev_v = None
    for a, b in zip(pts, pts[1:]):
        dt = float(b["t"]) - float(a["t"])
        if dt > 0.5:                      # tracking gap → new shot
            segs.append([b])
            prev_v = None
            continue
        v = np.array([float(b["x"]) - float(a["x"]),
                      float(b["y"]) - float(a["y"])]) / max(dt, 1e-3)
        speed = float(np.linalg.norm(v))
        if prev_v is not None and speed > 0.05 and float(np.linalg.norm(prev_v)) > 0.05:
            cosang = float(np.dot(v, prev_v)
                           / (np.linalg.norm(v) * np.linalg.norm(prev_v)))
            if cosang < 0.35:             # >~70° turn = a hit
                segs.append([b])
                prev_v = v
                continue
        segs[-1].append(b)
        prev_v = v
    return [s for s in segs
            if len(s) >= MIN_SEG_POINTS
            and float(s[-1]["t"]) - float(s[0]["t"]) >= MIN_SEG_DUR][:MAX_SEGMENTS]


# ------------------------------------------------------------- ballistic model

def simulate(p0: np.ndarray, v0: np.ndarray, t0: float, ts: np.ndarray,
             k_drag: float = K_DRAG) -> np.ndarray:
    """Positions (N,3) at absolute times ts for a drag-ballistic trajectory."""
    t_end = float(np.max(ts))
    dt = 1.0 / 120.0
    times = [t0]
    pos = [p0.astype(np.float64)]
    p, v = p0.astype(np.float64).copy(), v0.astype(np.float64).copy()
    t = t0
    g = np.array([0.0, 0.0, -G])
    V_CAP = 120.0   # m/s: keeps the drag term finite when the optimizer probes wild params
    while t < t_end + dt:
        sp = np.linalg.norm(v)
        if sp > V_CAP:
            v = v * (V_CAP / sp)
        # RK2 (midpoint)
        a1 = g - k_drag * np.linalg.norm(v) * v
        vm = v + 0.5 * dt * a1
        pm_v = v + 0.5 * dt * a1
        a2 = g - k_drag * np.linalg.norm(vm) * vm
        p = p + dt * pm_v
        v = v + dt * a2
        t += dt
        times.append(t)
        pos.append(p.copy())
    times = np.asarray(times)
    pos = np.asarray(pos)
    out = np.empty((len(ts), 3))
    for i, tq in enumerate(np.asarray(ts, dtype=np.float64)):
        j = int(np.searchsorted(times, tq, side="right")) - 1
        j = min(max(j, 0), len(times) - 2)
        k = (tq - times[j]) / max(times[j + 1] - times[j], 1e-9)
        out[i] = pos[j] * (1 - k) + pos[j + 1] * np.clip(k, 0.0, 1.0)
    return out


def _residuals(cam: dict, obs_t: np.ndarray, obs_xy: np.ndarray,
               p0: np.ndarray, v0: np.ndarray, t0: float) -> np.ndarray:
    pts3 = simulate(p0, v0, t0, obs_t)
    proj = project(cam, pts3)
    d = (proj - obs_xy) * np.array([cam["w"], cam["h"]])   # pixel-scale residuals
    return d.reshape(-1)


_X_LO = np.array([-8.0, -8.0, -0.3, -60.0, -60.0, -60.0])
_X_HI = np.array([14.0, 21.0, 10.0, 60.0, 60.0, 60.0])


def _lm(cam: dict, obs_t: np.ndarray, obs_xy: np.ndarray, x0: np.ndarray,
        t0: float, iters: int = 28) -> tuple[np.ndarray, float]:
    """Box-projected Levenberg–Marquardt over (p0, v0) with a numeric Jacobian.
    Clamping every step to the plausible box kills the mirror minimum behind
    the court AND the NaN blowups an unconstrained step invites (drag ∝ |v|·v).
    Returns the best-cost parameters seen (never worse than the init)."""
    x = np.clip(x0, _X_LO, _X_HI)
    lam = 1.0
    best, best_cost = x.copy(), np.inf
    for _ in range(iters):
        r = _residuals(cam, obs_t, obs_xy, x[:3], x[3:], t0)
        cost = float(r @ r)
        if cost < best_cost:
            best, best_cost = x.copy(), cost
        J = np.empty((r.size, 6))
        for j in range(6):
            step = max(1e-4, 1e-4 * abs(x[j]))
            xp = x.copy()
            xp[j] += step
            J[:, j] = (_residuals(cam, obs_t, obs_xy, xp[:3], xp[3:], t0) - r) / step
        A = J.T @ J + lam * np.eye(6)
        g_vec = J.T @ r
        try:
            dx = np.linalg.solve(A, -g_vec)
        except np.linalg.LinAlgError:
            break
        x_new = np.clip(x + dx, _X_LO, _X_HI)
        r_new = _residuals(cam, obs_t, obs_xy, x_new[:3], x_new[3:], t0)
        if float(r_new @ r_new) < cost:
            x = x_new
            lam = max(lam * 0.5, 1e-4)
            if abs(cost - float(r_new @ r_new)) < 1e-3 * max(cost, 1.0):
                break
        else:
            lam = min(lam * 2.5, 1e5)
    return best, best_cost


def _plausible(p0: np.ndarray, v0: np.ndarray) -> bool:
    """Inside a generous court neighborhood with sane heights/speeds — rejects
    the mirror local minimum monocular depth ambiguity offers (a trajectory
    behind the court falling instead of over the court rising)."""
    return (-8.0 <= p0[0] <= 14.0 and -8.0 <= p0[1] <= 21.0
            and -0.5 <= p0[2] <= 12.0 and float(np.linalg.norm(v0)) <= 150.0)


def fit_shot(cam: dict, seg: list[dict]) -> dict | None:
    """Multi-start LM fit of (p0, v0) for one shot. Several launch/landing
    height inits are tried and the best PLAUSIBLE solution wins — a single
    init can settle in the implausible mirror minimum along the rays."""
    obs_t = np.array([float(p["t"]) for p in seg])
    obs_xy = np.array([[float(p["x"]), float(p["y"])] for p in seg])
    t0 = float(obs_t[0])
    dur = float(obs_t[-1] - t0)

    best = None
    best_cost = np.inf
    for z0, z1 in ((2.0, 1.0), (1.5, 0.3), (0.5, 0.3), (2.6, 1.6), (0.8, 2.2)):
        start = ray_point_at_height(cam, *obs_xy[0], z=z0)
        end = ray_point_at_height(cam, *obs_xy[-1], z=z1)
        if start is None or end is None:
            continue
        v0 = (end - start) / max(dur, 1e-3)
        v0[2] += 0.5 * G * dur        # ballistic prior on the vertical component
        x, cost = _lm(cam, obs_t, obs_xy, np.concatenate([start, v0]), t0)
        if cost < best_cost and _plausible(x[:3], x[3:]):
            best, best_cost = x, cost
    if best is None:
        return None
    p0, v0 = best[:3], best[3:]
    rms = math.sqrt(best_cost / max(len(seg), 1) / 2.0)

    ts = np.arange(t0, obs_t[-1] + 1e-9, 1.0 / REPLAY_FPS)
    samples = simulate(p0, v0, t0, ts)
    peak = float(np.max(samples[:, 2]))
    if peak < 0.15:      # an arc that never rises above the floor is the mirror ghost
        return None
    return {
        "t0": round(t0, 3),
        "t1": round(float(obs_t[-1]), 3),
        "p0": [round(float(v), 3) for v in p0],
        "v0": [round(float(v), 3) for v in v0],
        "speed_kmh": round(float(np.linalg.norm(v0)) * 3.6, 1),
        "peak_z": round(peak, 2),
        "residual_px": round(rms, 2),
        "n_points": len(seg),
        "samples": [{"t": round(float(t), 3),
                     "x": round(float(p[0]), 3),
                     "y": round(float(p[1]), 3),
                     "z": round(float(p[2]), 3)}
                    for t, p in zip(ts, samples)],
    }


def _sharpest_turn(seg: list[dict]) -> int:
    """Index of the strongest direction change strictly inside the segment."""
    best_i, best_cos = 0, 2.0
    for i in range(1, len(seg) - 1):
        a = np.array([seg[i]["x"] - seg[i - 1]["x"], seg[i]["y"] - seg[i - 1]["y"]])
        b = np.array([seg[i + 1]["x"] - seg[i]["x"], seg[i + 1]["y"] - seg[i]["y"]])
        na, nb = np.linalg.norm(a), np.linalg.norm(b)
        if na < 1e-6 or nb < 1e-6:
            continue
        c = float(a @ b / (na * nb))
        if c < best_cos:
            best_cos, best_i = c, i
    return best_i


def _fit_segment(cam: dict, seg: list[dict], depth: int = 2) -> list[dict]:
    """Fit a segment; when the fit is missing or poor, bisect at the sharpest
    turn and fit the halves — a hit the splitter missed fuses two shots into
    one segment no single ballistic arc can explain."""
    fit = fit_shot(cam, seg)
    if fit and fit["residual_px"] <= 25.0:
        return [fit]
    if depth > 0 and len(seg) >= 2 * MIN_SEG_POINTS:
        i = _sharpest_turn(seg)
        if MIN_SEG_POINTS <= i <= len(seg) - MIN_SEG_POINTS:
            # The junction sample sits nearest the hit and belongs to neither
            # arc cleanly — one contaminated endpoint can drag a 13-point fit
            # into the wrong basin, so exclude it from both halves.
            halves = _fit_segment(cam, seg[:i], depth - 1) \
                + _fit_segment(cam, seg[i + 1:], depth - 1)
            if halves and (fit is None
                           or min(h["residual_px"] for h in halves) < fit["residual_px"]):
                return halves
    return [fit] if fit else []


# ------------------------------------------------------------------ entrypoint

def reconstruct_rally(vision_rally: dict | None, court_info: dict | None,
                      source_wh: tuple[int, int]) -> dict:
    """3D shuttle reconstruction for one rally, or a status dict explaining why not."""
    if not court_info or court_info.get("status") != "ok" or not court_info.get("homography"):
        return {"status": "no_court"}
    shuttle = (vision_rally or {}).get("shuttle") or []
    pts = [p for p in shuttle if isinstance(p, dict)]
    if len(pts) < MIN_SEG_POINTS:
        return {"status": "no_track"}
    cam = camera_from_homography(court_info["homography"], *source_wh)
    if cam is None:
        return {"status": "bad_camera"}
    shots = []
    for seg in split_shots(pts):
        for fit in _fit_segment(cam, seg):
            if fit and fit["residual_px"] <= 60.0:
                shots.append(fit)
    if not shots:
        return {"status": "no_fit"}
    return {
        "status": "ok",
        "fps": REPLAY_FPS,
        # True when the stored court homography was left-handed and rally3d had
        # to relabel x internally (only possible on results predating the
        # court.py handedness normalization) — positions are then in the
        # x-mirrored court frame.
        "mirrored_frame": bool(cam["mirrored"]),
        "camera": {"f_px": round(cam["f"], 1),
                   "center": [round(float(v), 2) for v in cam["C"]],
                   "R": [round(float(v), 5) for v in cam["R"].reshape(-1)]},
        "shots": shots,
        "drag_k": K_DRAG,
    }
