"""Action tracking on the low-res proxy (v4 — smooth-by-construction containment).

Per rally:
1. Frame-difference motion cells, flicker-masked (static camera ⇒ moving pixels are
   players + shuttle; LED boards / lights are masked out).
2. Weighted 2-means with temporal memory ⇒ the two player clusters.
3. Shuttle = coherent motion away from both bodies, temporal continuity gated.
4. Anchors are CONTINUOUS by design — every constraint input fades, nothing snaps:
   - the shuttle constraint ramps in/out with detection (no on/off pops);
   - the "active player" switches only with hysteresis, then BLENDS over ~0.4 s
     with temporary slack (no cross-court teleports).
5. Zoom: per-frame feasibility ceiling → erosion (anticipates tight moments) →
   long hann → asymmetric rate limit (slow push-in, quicker protective widen).
6. Pan: keyframed base path relaxed inside smoothed constraint bounds.
   Result: the shuttle and active player are contained AND the path has bounded
   acceleration — verified by validate.path_smoothness before any rendering.
"""
from dataclasses import dataclass

import numpy as np

from .. import config
from . import media

BLOCK = 8
KEY_INTERVAL = 0.5
EMA_XY = 0.20
SKY_CUT = 0.08
ENERGY_EMA = 0.25
SHUTTLE_DIST = 0.13
PAN_SPEED = 1.10            # max pan, fraction of frame width per second
Z_MIN, Z_MAX = 1.02, 1.40   # preferred zoom range
Z_HARD = 1.00               # constraints may force fully wide

SHUTTLE_MARGIN = 0.40       # shuttle stays within the central 60% of the crop
SHUTTLE_MARGIN_Y = 0.25
PLAYER_MARGIN = 0.06
PAD_PLAYER_X = 0.08
PLAYER_UP, PLAYER_DOWN = 0.10, 0.15

RAMP_STEP = 0.12            # shuttle constraint fade speed (per frame)
SWITCH_RATIO = 1.35         # hysteresis: other player must be this much busier
SWITCH_FRAMES = 6           # ...for this many consecutive frames to take over
SWITCH_BLEND = 12           # frames to blend the anchor across a takeover
ERODE_W = 14                # zoom anticipation window
HANN_Z = 27                 # zoom smoothing (<= 2*ERODE_W+1 keeps ceiling guarantee)
ZOOM_IN_RATE = 0.0035
ZOOM_OUT_RATE = 0.014
HANN_C = 11
BOUND_HANN = 17             # bound smoothing window
BOUND_W = 12                # bound tightening lookahead; must be >= (BOUND_HANN-1)/2
SOFTMIN_K = 80.0            # soft-min sharpness for the zoom safety ceiling


@dataclass
class FocusPath:
    t0: float
    fps: int
    xs: np.ndarray
    ys: np.ndarray
    zs: np.ndarray

    def at(self, t: float) -> tuple[float, float, float]:
        i = (t - self.t0) * self.fps
        i = min(max(i, 0.0), len(self.xs) - 1.000001)
        lo = int(i)
        frac = i - lo
        hi = min(lo + 1, len(self.xs) - 1)
        lerp = lambda a: float(a[lo] * (1 - frac) + a[hi] * frac)
        return lerp(self.xs), lerp(self.ys), lerp(self.zs)


# --------------------------------------------------------------------------- motion

def _motion_grids(proxy_path, t0, t1, fps):
    grids = []
    prev = None
    for _, frame in media.iter_frames(proxy_path, t0, t1, fps=fps, gray=True):
        cur = frame.astype(np.int16)
        if prev is not None:
            diff = np.abs(cur - prev).astype(np.float32)
            gh8, gw8 = diff.shape[0] // BLOCK, diff.shape[1] // BLOCK
            grids.append(diff[: gh8 * BLOCK, : gw8 * BLOCK]
                         .reshape(gh8, BLOCK, gw8, BLOCK).mean(axis=(1, 3)))
        prev = cur
    if not grids:
        return None, None
    G = np.stack(grids)
    G[:, : int(SKY_CUT * G.shape[1])] = 0.0
    thr = np.maximum(6.0, G.mean(axis=(1, 2), keepdims=True) + 2.0 * G.std(axis=(1, 2), keepdims=True))
    active = G > thr
    flicker = active.mean(axis=0) > 0.45
    active &= ~flicker[None, :, :]
    return G, active


def _two_means(pts, w, c0, c1, iters: int = 4):
    c0, c1 = np.array(c0, np.float32), np.array(c1, np.float32)
    e0 = e1 = 0.0
    for _ in range(iters):
        d0 = ((pts - c0) ** 2).sum(1)
        d1 = ((pts - c1) ** 2).sum(1)
        m0 = d0 <= d1
        e0, e1 = float(w[m0].sum()), float(w[~m0].sum())
        if e0 > 0:
            c0 = (pts[m0] * w[m0, None]).sum(0) / w[m0].sum()
        if e1 > 0:
            c1 = (pts[~m0] * w[~m0, None]).sum(0) / w[~m0].sum()
    return (float(c0[0]), float(c0[1])), (float(c1[0]), float(c1[1])), e0, e1


# ----------------------------------------------------------------- geometry helpers

def _interval(act, shuttle, ramp, half, axis, extra: float = 0.0):
    """Feasible crop-center interval on one axis; all constraints fade smoothly."""
    if axis == "x":
        p_lo, p_hi = act[0] - PAD_PLAYER_X, act[0] + PAD_PLAYER_X
        s, s_margin = (shuttle[0] if shuttle else 0.0), SHUTTLE_MARGIN
    else:
        p_lo, p_hi = act[1] - PLAYER_UP, act[1] + PLAYER_DOWN
        s, s_margin = (shuttle[1] if shuttle else 0.0), SHUTTLE_MARGIN_Y
    inner = half * (1.0 - PLAYER_MARGIN) + extra
    c_lo, c_hi = p_hi - inner, p_lo + inner
    if shuttle is not None and ramp > 0:
        allow = half * (1.0 - s_margin) + (1.0 - ramp) * 0.8 + extra
        c_lo = max(c_lo, s - allow)
        c_hi = min(c_hi, s + allow)
    return c_lo, c_hi


def _z_feasible(act, shuttle, ramp, cw_norm, ch_norm, extra: float = 0.0):
    z = Z_MAX
    while z >= Z_HARD - 1e-9:
        xlo, xhi = _interval(act, shuttle, ramp, cw_norm / (2 * z), "x", extra)
        ylo, yhi = _interval(act, shuttle, ramp, ch_norm / (2 * z), "y", extra)
        if xlo <= xhi and ylo <= yhi:
            return z
        z *= 0.96
    return Z_HARD


def _best_fit(act, shuttle, idle, cw_norm, ch_norm):
    """Preferred composition for the base path: both players (+ shuttle) if possible."""
    z = Z_MAX
    while z >= Z_HARD - 1e-9:
        hw, hh = cw_norm / (2 * z), ch_norm / (2 * z)
        xlo, xhi = _interval(act, shuttle, 1.0, hw, "x")
        ylo, yhi = _interval(act, shuttle, 1.0, hh, "y")
        if idle is not None:
            xlo = max(xlo, idle[0] + PAD_PLAYER_X - hw * (1 - PLAYER_MARGIN))
            xhi = min(xhi, idle[0] - PAD_PLAYER_X + hw * (1 - PLAYER_MARGIN))
            ylo = max(ylo, idle[1] + PLAYER_DOWN - hh * (1 - PLAYER_MARGIN))
            yhi = min(yhi, idle[1] - PLAYER_UP + hh * (1 - PLAYER_MARGIN))
        if xlo <= xhi and ylo <= yhi:
            return (xlo + xhi) / 2, (ylo + yhi) / 2, z
        z *= 0.94
    return None


def _solve_smooth_path(base, lo, hi, *, beta=2.5e4, alpha=8.0,
                       w_follow=1.0, w_bound=800.0, iters=4):
    """Optimal smooth path: minimize  β·Σ(accel²) + α·Σ(vel²)
    + w_follow·Σ(x-base)² + w_bound·Σ(violation of [lo,hi])².
    Solved as iteratively-reweighted least squares — globally smooth by
    construction, containment enforced by stiff penalties (no clip corners)."""
    n = len(base)
    base = base.astype(np.float64)
    D2 = np.zeros((n - 2, n))
    idx = np.arange(n - 2)
    D2[idx, idx] = 1.0
    D2[idx, idx + 1] = -2.0
    D2[idx, idx + 2] = 1.0
    D1 = np.zeros((n - 1, n))
    j = np.arange(n - 1)
    D1[j, j] = -1.0
    D1[j, j + 1] = 1.0
    A0 = beta * (D2.T @ D2) + alpha * (D1.T @ D1) + w_follow * np.eye(n)
    x = np.clip(base, lo, hi)
    for _ in range(iters):
        wv = np.zeros(n)
        tgt = np.zeros(n)
        below = x < lo
        above = x > hi
        wv[below | above] = w_bound
        tgt[below] = lo[below]
        tgt[above] = hi[above]
        x = np.linalg.solve(A0 + np.diag(wv), w_follow * base + wv * tgt)
    return x.astype(np.float32)


def _hann_smooth(arr, win=11):
    if win % 2 == 0:
        win += 1
    k = np.hanning(win).astype(np.float32)
    k /= k.sum()
    pad = win // 2
    ext = np.concatenate([np.full(pad, arr[0]), arr, np.full(pad, arr[-1])])
    return np.convolve(ext, k, mode="valid").astype(np.float32)


def _run_min(arr, w):
    out = arr.copy()
    n = len(arr)
    for s in range(1, w + 1):
        out[:-s] = np.minimum(out[:-s], arr[s:])
        out[s:] = np.minimum(out[s:], arr[:-s])
    return out


def _run_max(arr, w):
    return -_run_min(-arr, w)


def _crop_norms(proxy_path):
    pinfo = media.probe(proxy_path)
    aspect = config.OUT_W / config.OUT_H
    if pinfo.width / pinfo.height > aspect:
        return (pinfo.height * aspect) / pinfo.width, 1.0
    return 1.0, (pinfo.width / aspect) / pinfo.height


# ------------------------------------------------------------------------ analysis

def _analyze(proxy_path, t0, t1, fps, cw_norm, ch_norm):
    """Per-frame raw columns:
    0:fx 1:fy 2:z_pref 3:pAx 4:pAy 5:pBx 6:pBy 7:eA 8:eB 9:sx 10:sy 11:s_vis"""
    G, active = _motion_grids(proxy_path, t0, t1, fps)
    if G is None:
        return (np.array([[0.5, 0.55, 1.2, 0.38, 0.62, 0.62, 0.55, 1, 1, 0, 0, 0]],
                         dtype=np.float32), 0.0)
    gh, gw = G.shape[1], G.shape[2]

    pA, pB = (0.38, 0.62), (0.62, 0.55)
    eA = eB = 1e-3
    shuttle_prev = None
    rows = []
    for i in range(len(G)):
        ys_i, xs_i = np.nonzero(active[i])
        shuttle = None
        if len(xs_i) > 0:
            w = G[i][ys_i, xs_i].astype(np.float32)
            pts = np.stack([xs_i / gw, ys_i / gh], axis=1).astype(np.float32)
            pA, pB, rawA, rawB = _two_means(pts, w, pA, pB)
            eA += ENERGY_EMA * (rawA - eA)
            eB += ENERGY_EMA * (rawB - eB)
            dA = np.sqrt(((pts - np.array(pA)) ** 2).sum(1))
            dB = np.sqrt(((pts - np.array(pB)) ** 2).sum(1))
            lone = (dA > SHUTTLE_DIST) & (dB > SHUTTLE_DIST)
            if lone.any() and w[lone].sum() > 0.02 * w.sum():
                sx = float((pts[lone, 0] * w[lone]).sum() / w[lone].sum())
                sy = float((pts[lone, 1] * w[lone]).sum() / w[lone].sum())
                if shuttle_prev is None or (abs(sx - shuttle_prev[0]) < 0.25 and
                                            abs(sy - shuttle_prev[1]) < 0.25):
                    shuttle = (sx, sy)
        shuttle_prev = shuttle

        act, idle = (pA, pB) if eA >= eB else (pB, pA)
        fit = _best_fit(act, shuttle, idle, cw_norm, ch_norm)
        if fit is None or fit[2] < Z_MIN:
            fit2 = _best_fit(act, shuttle, None, cw_norm, ch_norm)
            if fit2 is not None:
                fit = fit2
        if fit is None:
            fit = (act[0], act[1] + 0.04, Z_MIN)
        rows.append((fit[0], fit[1] + 0.02, min(max(fit[2] * 0.97, Z_MIN), Z_MAX),
                     pA[0], pA[1], pB[0], pB[1], eA, eB,
                     shuttle[0] if shuttle else 0.0,
                     shuttle[1] if shuttle else 0.0,
                     1.0 if shuttle else 0.0))
    rows.insert(0, rows[0])  # account for the first (diff-less) frame
    cam_motion = float((active.mean(axis=(1, 2)) > 0.30).mean())
    return np.array(rows, dtype=np.float32), cam_motion


# ------------------------------------------------------------------------- tracking

def track(proxy_path, t0: float, t1: float, fps: int = config.PROXY_FPS,
          extra_smooth: bool = False, force_gentle: bool = False) -> FocusPath:
    cw_norm, ch_norm = _crop_norms(proxy_path)
    raw, cam_motion = _analyze(proxy_path, t0, t1, fps, cw_norm, ch_norm)
    n = len(raw)
    if n < 6:
        return FocusPath(t0=t0, fps=fps, xs=np.full(n, 0.5, np.float32),
                         ys=np.full(n, 0.55, np.float32), zs=np.full(n, Z_HARD, np.float32))
    if force_gentle or cam_motion > 0.35:
        # POV / handheld footage: the camera itself moves, so frame-difference
        # tracking is noise — hold a gentle centered push-in instead.
        u = np.linspace(0, 1, n, dtype=np.float32)
        s = u * u * (3 - 2 * u)
        return FocusPath(t0=t0, fps=fps,
                         xs=np.full(n, 0.5, np.float32),
                         ys=np.full(n, 0.52, np.float32),
                         zs=(1.02 + 0.08 * s).astype(np.float32))
    boost = 2 if extra_smooth else 1

    # Shuttle constraint ramp: detection flicker moves bounds continuously.
    ramp = np.zeros(n, np.float32)
    for i in range(1, n):
        ramp[i] = min(1.0, ramp[i - 1] + RAMP_STEP) if raw[i, 11] > 0.5 \
            else max(0.0, ramp[i - 1] - RAMP_STEP)
    # Shuttles fly smooth arcs — the frame-diff centroid doesn't. Smooth each
    # contiguous detection run so the containment bounds don't inherit jitter.
    sx = raw[:, 9].copy()
    sy = raw[:, 10].copy()
    vis = raw[:, 11] > 0.5
    i = 0
    while i < n:
        if not vis[i]:
            i += 1
            continue
        j = i
        while j < n and vis[j]:
            j += 1
        if j - i >= 5:
            sx[i:j] = _hann_smooth(sx[i:j], 7)
            sy[i:j] = _hann_smooth(sy[i:j], 7)
        i = j
    shuttles = [(float(sx[i]), float(sy[i])) if ramp[i] > 0 else None for i in range(n)]

    # Continuous "active player" anchor: hysteresis + blended takeover with slack.
    act_x = np.empty(n, np.float32)
    act_y = np.empty(n, np.float32)
    extra = np.zeros(n, np.float32)
    cur = 0 if raw[0, 7] >= raw[0, 8] else 1
    cnt, blend, from_xy = 0, 1.0, None
    for i in range(n):
        pA = (float(raw[i, 3]), float(raw[i, 4]))
        pB = (float(raw[i, 5]), float(raw[i, 6]))
        e_cur = float(raw[i, 7] if cur == 0 else raw[i, 8])
        e_oth = float(raw[i, 8] if cur == 0 else raw[i, 7])
        cnt = cnt + 1 if e_oth > SWITCH_RATIO * e_cur else 0
        if cnt >= SWITCH_FRAMES:
            cur ^= 1
            cnt = 0
            blend = 0.0
            from_xy = (float(act_x[i - 1]), float(act_y[i - 1])) if i else pA
        tgt = pA if cur == 0 else pB
        if blend < 1.0:
            blend = min(1.0, blend + 1.0 / SWITCH_BLEND)
            s = blend * blend * (3 - 2 * blend)
            act_x[i] = from_xy[0] * (1 - s) + tgt[0] * s
            act_y[i] = from_xy[1] * (1 - s) + tgt[1] * s
            extra[i] = (1.0 - s) * 0.30
        else:
            act_x[i], act_y[i] = tgt
    acts = [(float(act_x[i]), float(act_y[i])) for i in range(n)]

    # --- Zoom: feasibility ceiling -> anticipate -> smooth -> rate-limit.
    z_feas = np.array([_z_feasible(acts[i], shuttles[i], float(ramp[i]),
                                   cw_norm, ch_norm, float(extra[i])) for i in range(n)],
                      dtype=np.float32)
    # Windowed-span feasibility: when the shuttle sweeps the court quickly, the
    # camera must already be wide enough to cover its path over the next ~0.4 s —
    # otherwise the pan corridor empties and containment becomes impossible.
    m_lo_x = np.empty(n, np.float32); m_hi_x = np.empty(n, np.float32)
    m_lo_y = np.empty(n, np.float32); m_hi_y = np.empty(n, np.float32)
    for i in range(n):
        lo_x, hi_x = acts[i][0] - PAD_PLAYER_X, acts[i][0] + PAD_PLAYER_X
        lo_y, hi_y = acts[i][1] - PLAYER_UP, acts[i][1] + PLAYER_DOWN
        if shuttles[i] is not None and ramp[i] > 0.3:
            lo_x, hi_x = min(lo_x, shuttles[i][0]), max(hi_x, shuttles[i][0])
            lo_y, hi_y = min(lo_y, shuttles[i][1]), max(hi_y, shuttles[i][1])
        m_lo_x[i], m_hi_x[i] = lo_x, hi_x
        m_lo_y[i], m_hi_y[i] = lo_y, hi_y
    span_x = _run_max(m_hi_x, BOUND_W) - _run_min(m_lo_x, BOUND_W)
    span_y = _run_max(m_hi_y, BOUND_W) - _run_min(m_lo_y, BOUND_W)
    z_win = np.minimum(cw_norm * (1 - PLAYER_MARGIN) / np.maximum(span_x, 1e-3),
                       ch_norm * (1 - PLAYER_MARGIN) / np.maximum(span_y, 1e-3))
    z_feas = np.clip(np.minimum(z_feas, z_win), Z_HARD, Z_MAX).astype(np.float32)
    z_pref = np.minimum(np.clip(raw[:, 2], Z_MIN, Z_MAX), z_feas)
    zs = _run_min(z_pref, ERODE_W * boost)
    zs = _hann_smooth(zs, HANN_Z * boost)
    # Optimal smooth zoom: follow the (eroded, smoothed) preference, never exceed
    # the lightly-eroded feasibility ceiling, never dip below fully wide.
    ceiling = _run_min(z_feas, 4).astype(np.float64)
    zs = _solve_smooth_path(zs.astype(np.float64),
                            np.full(n, Z_HARD), ceiling,
                            beta=8e4 * boost, alpha=8.0, w_bound=1500.0)
    zs = np.clip(zs, Z_HARD, Z_MAX)

    # --- Center: keyframed base path relaxed inside smoothed constraint bounds.
    step = max(1, int(KEY_INTERVAL * fps))
    half = step // 2
    key_idx = list(range(0, n, step))
    if key_idx[-1] != n - 1:
        key_idx.append(n - 1)
    kx, ky = [], []
    for ki in key_idx:
        lo, hi = max(0, ki - half), min(n, ki + half + 1)
        kx.append(float(np.median(raw[lo:hi, 0])))
        ky.append(float(np.median(raw[lo:hi, 1])))
    xs = np.empty(n, np.float32)
    ys = np.empty(n, np.float32)
    for a in range(len(key_idx) - 1):
        i0, i1 = key_idx[a], key_idx[a + 1]
        span = max(1, i1 - i0)
        u = (np.arange(i0, i1 + 1) - i0) / span
        wgt = (1 - np.cos(np.pi * u)) / 2
        xs[i0:i1 + 1] = kx[a] * (1 - wgt) + kx[a + 1] * wgt
        ys[i0:i1 + 1] = ky[a] * (1 - wgt) + ky[a + 1] * wgt
    for arr in (xs, ys):
        for i in range(1, n):
            arr[i] = arr[i - 1] + EMA_XY * (arr[i] - arr[i - 1])
    vmax = PAN_SPEED / fps
    for arr, lim in ((xs, vmax), (ys, vmax * 0.7)):
        for i in range(1, n):
            d = arr[i] - arr[i - 1]
            if abs(d) > lim:
                arr[i] = arr[i - 1] + np.sign(d) * lim

    xlo = np.empty(n, np.float32); xhi = np.empty(n, np.float32)
    ylo = np.empty(n, np.float32); yhi = np.empty(n, np.float32)
    fw = 0.0   # smooth weight of the "shuttle wins" fallback — no discrete switches
    for i in range(n):
        hw, hh = cw_norm / (2 * zs[i]), ch_norm / (2 * zs[i])
        s_strong = shuttles[i] is not None and ramp[i] > 0.5
        ax_, bx_ = _interval(acts[i], shuttles[i], float(ramp[i]), hw, "x", float(extra[i]))
        ay_, by_ = _interval(acts[i], shuttles[i], float(ramp[i]), hh, "y", float(extra[i]))
        infeasible = (ax_ > bx_ or ay_ > by_) and s_strong
        fw += 0.15 * ((1.0 if infeasible else 0.0) - fw)
        if ax_ > bx_:
            ax_ = bx_ = (ax_ + bx_) / 2
        if ay_ > by_:
            ay_ = by_ = (ay_ + by_) / 2
        if s_strong and fw > 1e-3:   # blend toward the shuttle-centered window
            sxa, sxb = shuttles[i][0] - hw * 0.88, shuttles[i][0] + hw * 0.88
            sya, syb = shuttles[i][1] - hh * 0.88, shuttles[i][1] + hh * 0.88
            ax_, bx_ = ax_ * (1 - fw) + sxa * fw, bx_ * (1 - fw) + sxb * fw
            ay_, by_ = ay_ * (1 - fw) + sya * fw, by_ * (1 - fw) + syb * fw
        xlo[i], xhi[i] = ax_, bx_
        ylo[i], yhi[i] = ay_, by_

    # Optimal smooth pan inside the raw per-frame bounds — the solver trades
    # acceleration against containment globally, so there are no clip corners.
    xs = _solve_smooth_path(xs.astype(np.float64), xlo.astype(np.float64),
                            xhi.astype(np.float64), beta=8e4 * boost, w_bound=250.0)
    ys = _solve_smooth_path(ys.astype(np.float64), ylo.astype(np.float64),
                            yhi.astype(np.float64), beta=2.5e4 * boost)
    return FocusPath(t0=t0, fps=fps, xs=xs, ys=ys, zs=zs)


def safe_path(proxy_path, t0: float, t1: float, fps: int = config.PROXY_FPS) -> FocusPath:
    """Fallback camera: static wide shot centered on the median action position."""
    fp = track(proxy_path, t0, t1, fps)
    n = len(fp.xs)
    return FocusPath(
        t0=t0, fps=fps,
        xs=np.full(n, float(np.median(fp.xs)), np.float32),
        ys=np.full(n, float(np.median(fp.ys)), np.float32),
        zs=np.full(n, Z_HARD, np.float32),
    )


def _nearest(samples: list[dict], t: float, max_gap: float = 0.8) -> dict | None:
    if not samples:
        return None
    best = min(samples, key=lambda s: abs(float(s.get("t", 0.0)) - t))
    return best if abs(float(best.get("t", 0.0)) - t) <= max_gap else None


def from_vision(proxy_path, t0: float, t1: float, vision_rally: dict | None,
                fps: int = config.PROXY_FPS) -> FocusPath | None:
    """Build a camera path from GPU player boxes + confident shuttle points.

    This is deliberately conservative: if the worker only returns sparse or weak
    tracks, the caller should use the existing CPU motion path.
    """
    if not vision_rally or vision_rally.get("player_quality", 0.0) < 0.35:
        return None
    player_frames = vision_rally.get("players") or []
    shuttle_frames = vision_rally.get("shuttle") or []
    use_shuttle = vision_rally.get("shuttle_quality", 0.0) >= config.SHUTTLE_MASK_MIN_QUALITY
    n = max(2, int(round((t1 - t0) * fps)))
    times = t0 + np.arange(n, dtype=np.float32) / fps
    cw_norm, ch_norm = _crop_norms(proxy_path)

    xs = np.full(n, 0.5, np.float32)
    ys = np.full(n, 0.55, np.float32)
    zs = np.full(n, Z_HARD, np.float32)
    seen = np.zeros(n, dtype=bool)

    for i, t in enumerate(times):
        pf = _nearest(player_frames, float(t))
        boxes = sorted((pf or {}).get("boxes", []), key=lambda b: b.get("confidence", 0), reverse=True)[:2]
        if not boxes:
            continue
        pts_x, pts_y = [], []
        for b in boxes:
            pts_x.extend([float(b["x1"]), float(b["x2"])])
            pts_y.extend([float(b["y1"]), float(b["y2"])])
        sf = _nearest(shuttle_frames, float(t), max_gap=0.35) if use_shuttle else None
        if sf and sf.get("confidence", 0.0) >= config.SHUTTLE_MASK_MIN_CONF:
            pts_x.append(float(sf["x"]))
            pts_y.append(float(sf["y"]))

        lo_x, hi_x = max(0.0, min(pts_x) - 0.08), min(1.0, max(pts_x) + 0.08)
        lo_y, hi_y = max(0.0, min(pts_y) - 0.10), min(1.0, max(pts_y) + 0.13)
        span_x = max(0.18, hi_x - lo_x)
        span_y = max(0.28, hi_y - lo_y)
        z = min(cw_norm / span_x, ch_norm / span_y) * 0.86
        z = float(np.clip(z, Z_HARD, Z_MAX))
        hw, hh = cw_norm / (2 * z), ch_norm / (2 * z)
        xs[i] = np.clip((lo_x + hi_x) / 2, hw, 1.0 - hw)
        ys[i] = np.clip((lo_y + hi_y) / 2, hh, 1.0 - hh)
        zs[i] = z
        seen[i] = True

    if seen.mean() < 0.20:
        return None

    for arr, fill in ((xs, 0.5), (ys, 0.55), (zs, Z_HARD)):
        last = fill
        for i in range(n):
            if seen[i]:
                last = float(arr[i])
            else:
                arr[i] = last
        last = fill
        for i in range(n - 1, -1, -1):
            if seen[i]:
                last = float(arr[i])
            else:
                arr[i] = (arr[i] + last) / 2

    win = 17 if n >= 17 else max(3, n | 1)
    xs = _hann_smooth(xs, win)
    ys = _hann_smooth(ys, win)
    zs = _hann_smooth(zs, win)
    hw = cw_norm / (2 * zs)
    hh = ch_norm / (2 * zs)
    xs = _solve_smooth_path(xs.astype(np.float64), hw.astype(np.float64),
                            (1.0 - hw).astype(np.float64), beta=5e4, w_bound=500.0)
    ys = _solve_smooth_path(ys.astype(np.float64), hh.astype(np.float64),
                            (1.0 - hh).astype(np.float64), beta=2e4, w_bound=500.0)
    return FocusPath(t0=t0, fps=fps, xs=xs, ys=ys, zs=zs.astype(np.float32))
