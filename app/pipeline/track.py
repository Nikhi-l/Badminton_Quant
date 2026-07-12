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
import math
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


def _group_player_tracks(player_frames: list, min_conf: float = 0.10) -> list[dict]:
    """Group per-frame boxes into per-player tracks (TASK-031).

    Prefers the worker's tracker ids (ByteTrack/BoT-SORT ``track_id``); boxes
    without an id are greedily matched to the nearest live track by centroid +
    apparent-height cost. Returns tracks as dicts of parallel numpy arrays
    (ts, cx, cy, hw, hh) sorted by time.
    """
    tracks: dict = {}          # key -> {"ts": [], "cx": [], ...}
    live: dict = {}            # key -> (cx, cy, h, t_last) for greedy matching
    anon = 0
    for f in (player_frames or []):
        try:
            t = float(f.get("t", 0.0))
        except (TypeError, ValueError):
            continue
        dets = []
        for b in f.get("boxes", []):
            if b.get("confidence", 0) < min_conf:
                continue
            try:
                cx = (float(b["x1"]) + float(b["x2"])) / 2
                cy = (float(b["y1"]) + float(b["y2"])) / 2
                hw = (float(b["x2"]) - float(b["x1"])) / 2
                hh = (float(b["y2"]) - float(b["y1"])) / 2
            except (KeyError, TypeError, ValueError):
                continue
            tid = b.get("track_id")
            dets.append((cx, cy, hw, hh, int(tid) if isinstance(tid, (int, float)) else None))
        matched: set = set()
        for cx, cy, hw, hh, tid in dets:
            if tid is not None:
                key = ("w", tid)
            else:
                # Greedy match to the nearest live track; the gate widens with the
                # sample gap (players cover real court between sparse samples).
                best, best_cost = None, None
                for k, (px, py, ph, pt) in live.items():
                    if k in matched:
                        continue
                    dt = max(0.0, t - pt)
                    gate = min(0.5, 0.18 + 0.3 * max(0.0, dt - 0.2))
                    cost = math.hypot(cx - px, cy - py) + 0.5 * abs(2 * hh - ph)
                    if cost <= gate and (best_cost is None or cost < best_cost):
                        best, best_cost = k, cost
                if best is None:
                    key = ("a", anon)
                    anon += 1
                else:
                    key = best
            matched.add(key)
            tr = tracks.setdefault(key, {"ts": [], "cx": [], "cy": [], "hw": [], "hh": []})
            tr["ts"].append(t)
            tr["cx"].append(cx)
            tr["cy"].append(cy)
            tr["hw"].append(hw)
            tr["hh"].append(hh)
            live[key] = (cx, cy, 2 * hh, t)
    out = []
    for tr in tracks.values():
        order = np.argsort(np.asarray(tr["ts"]))
        out.append({k: np.asarray(tr[k], np.float64)[order] for k in tr})
    return out


def _track_at(tr: dict, t: float, hold: float = 0.35, max_gap: float = 1.0) -> list | None:
    """Linearly interpolated [cx, cy, hw, hh] of one track at time t, or None
    when the track has no sample close enough — an expired track constrains
    nothing (the old slot logic held ghost players for the rest of the rally)."""
    ts = tr["ts"]
    j = int(np.searchsorted(ts, t))
    left = j - 1 if j - 1 >= 0 else None
    right = j if j < len(ts) else None
    if left is not None and right is not None and (ts[right] - ts[left]) <= max_gap:
        span = float(ts[right] - ts[left])
        w = 0.0 if span <= 1e-6 else (t - ts[left]) / span
        return [float(tr[k][left] * (1 - w) + tr[k][right] * w) for k in ("cx", "cy", "hw", "hh")]
    if left is not None and (t - ts[left]) <= hold:
        return [float(tr[k][left]) for k in ("cx", "cy", "hw", "hh")]
    if right is not None and (ts[right] - t) <= hold:
        return [float(tr[k][right]) for k in ("cx", "cy", "hw", "hh")]
    return None


def _two_player_tracks(player_frames: list, times) -> list:
    """Per-frame [near, far] player [cx, cy, hw, hh] from continuous tracks
    (TASK-031). 'near' = lower in the frame (closer to a back-court camera).

    Replaces the old 2-slot nearest-sample heuristic, which (a) ignored worker
    tracker ids and re-derived identity from scratch, (b) stair-stepped between
    ~6 Hz samples with no interpolation ('the camera is behind the player'),
    (c) never expired slots — a ghost player constrained pan/zoom for the rest
    of the rally, and (d) hopped the followed anchor between doubles partners.
    near/far selection now carries hysteresis: the anchor only changes when a
    different track is decisively lower/higher in frame, so partners crossing
    in depth don't teleport the camera.
    """
    tracks = _group_player_tracks(player_frames)
    res = []
    near_key = far_key = None
    for t in times:
        t = float(t)
        active = []
        for idx, tr in enumerate(tracks):
            pos = _track_at(tr, t)
            if pos is not None:
                active.append((idx, pos))
        if not active:
            near_key = far_key = None
            res.append((None, None))
            continue
        hi = max(active, key=lambda a: a[1][1])   # largest cy = near court
        cur = {idx: pos for idx, pos in active}
        if len(active) == 1:
            near_key, far_key = hi[0], None
            res.append((list(hi[1]), None))
            continue
        # Hysteresis: keep the previous near/far track unless a challenger is
        # decisively (>0.05 normalized) lower/higher in the frame.
        if near_key in cur and hi[0] != near_key and (hi[1][1] - cur[near_key][1]) < 0.05:
            near = (near_key, cur[near_key])
        else:
            near = hi
        far_cands = [(i, p) for i, p in active if i != near[0]]
        lo = min(far_cands, key=lambda a: a[1][1])
        if far_key in cur and far_key != near[0] and lo[0] != far_key \
                and (cur[far_key][1] - lo[1][1]) < 0.05:
            far = (far_key, cur[far_key])
        else:
            far = lo
        near_key, far_key = near[0], far[0]
        res.append((list(near[1]), list(far[1])))
    return res


# ---- TASK-035: measured shuttle confidence (tracking-by-detection style) ----
# Frame width spans roughly the court diagonal (~14 m) in typical footage, so
# 10 normalized-units/s ≈ 500 km/h — beyond any real smash (the smash-speed
# literature rejects >375 km/h for amateurs; world-record initial ≈ 490).
SHUTTLE_V_MAX_NORM_S = 10.0
_STATIC_RADIUS = 0.012      # a "shuttle" pinned inside ~1% of the frame…
_STATIC_RUN = 8             # …for ≥8 consecutive points is a light / net post
_REFINE_SEG_GAP_S = 0.35    # dt above this starts a new flight segment


def _innovation_scores(seq: list[tuple[float, float, float]]) -> list[float | None]:
    """One directional pass of constant-velocity innovation scoring.

    Each point is compared against the extrapolation of the last ACCEPTED
    points of its flight segment; confidence falls linearly with the miss
    distance normalized by the local median step (resolution- and
    speed-independent, like the smash-speed paper's W/4 normalization).
    ``None`` means "no motion context in this direction" (segment head) — the
    caller merges with the opposite pass, where that same point sits at a
    segment TAIL and gets an informed score.
    """
    out: list[float | None] = [None] * len(seq)
    ref: list[tuple[float, float, float]] = []   # last accepted (t, x, y)
    steps: list[float] = []                      # recent accepted step sizes
    for idx, (t, x, y) in enumerate(seq):
        if ref and t - ref[-1][0] > _REFINE_SEG_GAP_S:
            ref, steps = [], []
        if not ref:
            ref.append((t, x, y))
            continue
        t0, x0, y0 = ref[-1]
        dt = max(t - t0, 1e-3)
        if len(ref) >= 2:
            t1, x1, y1 = ref[-2]
            dt01 = max(t0 - t1, 1e-3)
            px, py = x0 + (x0 - x1) / dt01 * dt, y0 + (y0 - y1) / dt01 * dt
        else:
            px, py = x0, y0
        miss = math.hypot(x - px, y - py)
        scale = max(0.02, 3.0 * (sorted(steps)[len(steps) // 2] if steps else 0.02))
        conf = max(0.05, min(0.95, 0.95 - 0.33 * miss / scale))
        if math.hypot(x - x0, y - y0) / dt > SHUTTLE_V_MAX_NORM_S:
            conf = 0.05   # implied speed no shuttle reaches: hard reject
        out[idx] = conf
        if conf >= 0.3:   # rejected points must not drag the reference
            steps.append(math.hypot(x - x0, y - y0))
            del steps[:-12]
            ref.append((t, x, y))
            del ref[:-3]
    return out


def shuttle_track_quality(points: list, dur: float, fps: float | None = None) -> float:
    """Post-filter shuttle quality: coverage × longest-gap × teleport factors —
    the same formula the worker reports, recomputed on the CLEANED track
    (TASK-041). The worker's number is measured on its raw output, so a rally
    whose track was mostly a background court reads 0.0 even after the court
    gate removed the junk — starving the shuttle-follow camera of a track that
    is now perfectly usable. Consumers gate on ≥0.22 (camera) / ≥0.65 (POV
    follow, mask); this recompute is what those gates should see.
    """
    n = len(points or [])
    if not n or dur <= 0:
        return 0.0
    ts = []
    for p in points:
        try:
            ts.append((float(p["t"]), float(p["x"]), float(p["y"])))
        except (KeyError, TypeError, ValueError):
            continue
    if not ts:
        return 0.0
    ts.sort()
    if fps is None:
        # Self-calibrate to the track's own cadence (TrackNet = source fps,
        # the motion fallback ~6 Hz) so coverage compares like with like.
        dts = sorted(b[0] - a[0] for a, b in zip(ts, ts[1:]) if b[0] > a[0])
        fps = min(30.0, max(4.0, 1.0 / dts[len(dts) // 2])) if dts else 30.0
    expected = max(2, int(dur * max(fps, 1.0) * 0.35))
    coverage = min(1.0, len(ts) / expected)
    longest_gap = 0.0
    teleports = 0
    for (t0, x0, y0), (t1, x1, y1) in zip(ts, ts[1:]):
        dt = t1 - t0
        longest_gap = max(longest_gap, dt)
        if dt <= 2.5 / max(fps, 1.0) and math.hypot(x1 - x0, y1 - y0) > 0.22:
            teleports += 1
    gap_factor = max(0.0, min(1.0, 1.0 - max(0.0, longest_gap - 0.5) / dur))
    jump_factor = max(0.0, min(1.0, 1.0 - 8.0 * teleports / max(len(ts) - 1, 1)))
    return max(0.0, min(1.0, coverage * gap_factor * jump_factor))


def court_shuttle_gate(points: list, corners: list | None, expand: float = 1.35,
                       min_inside_frac: float = 0.5, gap_s: float = 0.35) -> list:
    """Drop shuttle flight SEGMENTS that belong to a background court (TASK-041).

    A neighbouring court's rally is smooth, fast, perfectly plausible flight —
    every kinematic filter passes it; only geometry tells the courts apart.
    Points are split into flight segments (a dt above ``gap_s`` separates
    them) and a segment survives only if ≥ ``min_inside_frac`` of its points
    fall inside the court quad expanded ``expand``× from its centroid.
    Segment-level, not per-point: a main-court clear ARCS above the far line
    (outside any reasonable quad at its apex) and survives on its
    majority-inside points, while a background rally — mostly outside — drops
    wholesale. No corners → no opinion (returns points unchanged).
    """
    if not isinstance(corners, (list, tuple)) or len(corners) != 4 or not points:
        return points
    try:
        quad = [(float(c[0]), float(c[1])) for c in corners]
    except (TypeError, ValueError, IndexError):
        return points
    cx = sum(p[0] for p in quad) / 4.0
    cy = sum(p[1] for p in quad) / 4.0
    poly = [(cx + (px - cx) * expand, cy + (py - cy) * expand) for px, py in quad]

    def _inside(x: float, y: float) -> bool:
        hit = False
        for i in range(4):
            x1, y1 = poly[i]
            x2, y2 = poly[(i + 1) % 4]
            if (y1 > y) != (y2 > y) and x < x1 + (y - y1) / (y2 - y1) * (x2 - x1):
                hit = not hit
        return hit

    ordered = sorted((p for p in points if isinstance(p, dict)),
                     key=lambda p: float(p.get("t", 0.0)))
    out: list = []
    seg: list = []

    def _flush():
        if not seg:
            return
        inside = sum(1 for q in seg if _inside(float(q.get("x", 0)), float(q.get("y", 0))))
        if inside / len(seg) >= min_inside_frac:
            out.extend(seg)

    for p in ordered:
        if seg and float(p.get("t", 0.0)) - float(seg[-1].get("t", 0.0)) > gap_s:
            _flush()
            seg = []
        seg.append(p)
    _flush()
    return out


def refine_shuttle_track(points: list) -> list:
    """Replace placeholder shuttle confidence with MEASURED plausibility
    (TASK-035, adapted from smartphone smash-speed tracking pipelines).

    TrackNetV3's CSV exposes binary visibility, so the workers stored a flat
    0.82 on every point — consumers thresholding confidence learned nothing
    from it (audit P0: "82% is a coverage score"). This pass runs at
    canonicalization time for BOTH vision backends and:

    - drops static runs (≥``_STATIC_RUN`` points inside ``_STATIC_RADIUS``):
      a stadium light, a net post, or a floor-resting shuttle is not flight;
    - scores every remaining point by constant-velocity innovation, forward
      AND backward, keeping the better score — a false positive opening a
      segment poisons the forward reference but is exposed by the backward
      pass, while a genuine segment head scores well backward;
    - hard-rejects implied speeds above ``SHUTTLE_V_MAX_NORM_S`` (≈500 km/h);
    - stamps ``provenance: "observed"`` (future inpainted/predicted fills
      must label themselves — consumers may trust them differently).

    Confidence lands in [0.05, 0.95]; consumers keep their ≥0.3 threshold, so
    an implausible point is now actually excluded from the camera, Studio,
    render marker, and 3D — not painted at 82%. Segment heads with no motion
    context in either direction (1–2 point orphans) get a neutral 0.6 and are
    left for the Hampel spatial filter, which stays complementary.
    """
    pts: list[tuple[float, float, float, dict]] = []
    for p in points or []:
        try:
            t, x, y = float(p["t"]), float(p["x"]), float(p["y"])
        except (KeyError, TypeError, ValueError):
            continue
        if 0.0 < x <= 1.0 and 0.0 < y <= 1.0:
            pts.append((t, x, y, p))
    pts.sort(key=lambda r: r[0])
    if not pts:
        return []

    # Static-run rejection (the paper rejects implied speeds < 5 km/h).
    n = len(pts)
    drop: set[int] = set()
    i = 0
    while i < n:
        j = i + 1
        while (j < n and pts[j][0] - pts[j - 1][0] <= _REFINE_SEG_GAP_S
               and math.hypot(pts[j][1] - pts[i][1], pts[j][2] - pts[i][2]) <= _STATIC_RADIUS):
            j += 1
        if j - i >= _STATIC_RUN:
            drop.update(range(i, j))
        i = j if j > i + 1 else i + 1
    kept = [pts[k] for k in range(n) if k not in drop]
    if not kept:
        return []

    xyz = [(t, x, y) for t, x, y, _ in kept]
    fwd = _innovation_scores(xyz)
    bwd = list(reversed(_innovation_scores([(-t, x, y) for t, x, y in reversed(xyz)])))
    out = []
    for (t, x, y, p), f, b in zip(kept, fwd, bwd):
        informed = [v for v in (f, b) if v is not None]
        conf = max(informed) if informed else 0.6
        out.append({**p, "confidence": round(conf, 3), "provenance": "observed"})
    return out


def filter_shuttle_points(shuttle_frames: list, min_conf: float = 0.3,
                          window: int = 3, max_residual: float = 0.16,
                          speed_k: float = 2.5, iterations: int = 2) -> list:
    """Reject false shuttle detections (custom tracking filter).

    TrackNet false positives are usually isolated teleports — a single detection
    far from the local trajectory (a light, a line judge's shirt) that yanks the
    camera. Hampel-style pass: each point is compared to the median of up to
    ``window`` kept neighbours per side; the allowed residual scales with the
    local motion (``speed_k`` × median neighbour step) so genuine fast smashes
    survive while isolated spikes do not. Runs ``iterations`` times so a spike
    inside an endpoint's window can't poison the median and drop real points —
    the second pass re-evaluates everything against spike-free windows.
    Low-confidence and out-of-frame points are dropped. Order is preserved.

    Endpoints (fully one-sided windows) are judged against a LINEAR
    EXTRAPOLATION of the two nearest kept neighbours rather than the one-sided
    median (TASK-034): an arc decelerating in image space always takes its
    biggest step at launch, so the first point after a hit — the contact
    point, the highest-information sample for 3D — read as an outlier against
    the forward median. A genuine teleport at a segment edge still fails the
    extrapolation by the full spike distance.
    """
    cands = []
    for s in (shuttle_frames or []):
        try:
            t, x, y = float(s["t"]), float(s["x"]), float(s["y"])
            conf = float(s.get("confidence", 0.0))
        except (KeyError, TypeError, ValueError):
            continue
        if conf >= min_conf and 0.0 < x <= 1.0 and 0.0 < y <= 1.0:
            cands.append((t, x, y, s))
    if len(cands) < 3:
        return [c[3] for c in cands]
    cands.sort(key=lambda r: r[0])
    n = len(cands)
    ts = np.array([c[0] for c in cands])
    xs = np.array([c[1] for c in cands])
    ys = np.array([c[2] for c in cands])

    def _extrap_residual(i: int, a: int, b: int) -> float:
        """Distance from point i to the line through kept neighbours a (nearest)
        and b, extended to t_i. Works for both track edges."""
        span = float(ts[a] - ts[b])
        k = (float(ts[i] - ts[a]) / span) if abs(span) > 1e-9 else 0.0
        px = float(xs[a] + (xs[a] - xs[b]) * k)
        py = float(ys[a] + (ys[a] - ys[b]) * k)
        return float(np.hypot(xs[i] - px, ys[i] - py))

    keep = np.ones(n, dtype=bool)
    for _ in range(max(1, iterations)):
        kept_idx = np.where(keep)[0]
        if len(kept_idx) < 2:
            break
        new_keep = np.ones(n, dtype=bool)
        for i in range(n):
            pos = int(np.searchsorted(kept_idx, i))
            left = [int(j) for j in kept_idx[max(0, pos - window):pos] if j != i]
            right = [int(j) for j in kept_idx[pos:pos + window + 1] if j != i][:window]
            nb = left + right
            if not nb:
                continue
            if not left and len(right) >= 2:
                res = _extrap_residual(i, right[0], right[1])
            elif not right and len(left) >= 2:
                res = _extrap_residual(i, left[-1], left[-2])
            else:
                med_x, med_y = float(np.median(xs[nb])), float(np.median(ys[nb]))
                res = float(np.hypot(xs[i] - med_x, ys[i] - med_y))
            if len(nb) > 1:
                steps = np.hypot(np.diff(xs[nb]), np.diff(ys[nb]))
                allowed = max(max_residual, speed_k * float(np.median(steps)))
            else:
                allowed = max_residual
            new_keep[i] = res <= allowed
        keep = new_keep
    return [cands[i][3] for i in range(n) if keep[i]]


def _shuttle_track(shuttle_frames: list, times, max_gap_s: float = 0.5):
    """Per-frame interpolated shuttle (x, y), NaN where there is no confident
    detection within `max_gap_s`. Linear interpolation across short gaps keeps the
    camera following continuously instead of snapping back on every missed frame.
    False detections are filtered out first so a single bad point can't yank the
    interpolated path (and with it the camera)."""
    shuttle_frames = filter_shuttle_points(shuttle_frames)
    pts = sorted(((float(s["t"]), float(s["x"]), float(s["y"]))
                  for s in (shuttle_frames or [])
                  if float(s.get("confidence", 0.0)) >= 0.3
                  and float(s.get("x", 0)) > 0 and float(s.get("y", 0)) > 0),
                 key=lambda r: r[0])
    n = len(times)
    sx = np.full(n, np.nan, np.float32)
    sy = np.full(n, np.nan, np.float32)
    if not pts:
        return sx, sy
    ts = np.array([p[0] for p in pts])
    px = np.array([p[1] for p in pts])
    py = np.array([p[2] for p in pts])
    for i, t in enumerate(times):
        t = float(t)
        j = int(np.searchsorted(ts, t))
        left = j - 1 if j - 1 >= 0 else None
        right = j if j < len(ts) else None
        if left is not None and right is not None and (ts[right] - ts[left]) <= 2 * max_gap_s:
            span = float(ts[right] - ts[left])
            w = 0.0 if span <= 1e-6 else (t - ts[left]) / span
            sx[i] = px[left] * (1 - w) + px[right] * w
            sy[i] = py[left] * (1 - w) + py[right] * w
        elif left is not None and (t - ts[left]) <= max_gap_s:
            sx[i], sy[i] = px[left], py[left]
        elif right is not None and (ts[right] - t) <= max_gap_s:
            sx[i], sy[i] = px[right], py[right]
    return sx, sy


def _contain_targets(xs, ys, zs, cw, ch, shu_x, shu_y, tracks,
                     pad: float = 0.035, smooth_win: int = 9):
    """Post-smoothing guarantee that the crop keeps its subjects in frame.

    The heavy path solver optimises smoothness, which can drag the crop off a
    fast shuttle or the near player ("the highlight loses the player/shuttle").
    Per frame this pass gathers the required extents — the shuttle point and the
    near player's body box — and (a) zooms out when they can't fit at the current
    zoom, (b) shifts the centre minimally to contain them. Runs shift → light
    re-smooth → shift so the final path is both smooth and containing; the last
    pass is unsmoothed, so containment wins at output.
    """
    xs = np.asarray(xs, np.float64).copy()
    ys = np.asarray(ys, np.float64).copy()
    zs = np.asarray(zs, np.float64).copy()
    n = len(xs)

    def required_extent(i):
        rx, ry = [], []
        sx, sy = float(shu_x[i]), float(shu_y[i])
        if not np.isnan(sx):
            rx.append(sx)
            ry.append(sy)
        near = tracks[i][0] if i < len(tracks) else None
        if near is not None:
            bx, by, bhw, bhh = near
            rx += [bx - bhw * 0.6, bx + bhw * 0.6]
            ry += [by - bhh * 0.8, by + bhh * 0.8]
        return rx, ry

    def shift_pass():
        for i in range(n):
            rx, ry = required_extent(i)
            if not rx:
                continue
            hw, hh = cw / (2 * zs[i]), ch / (2 * zs[i])
            need_hw = (max(rx) - min(rx)) / 2 + pad
            need_hh = (max(ry) - min(ry)) / 2 + pad
            if need_hw > hw or need_hh > hh:      # zoom out until they fit
                z_fit = min(cw / (2 * need_hw), ch / (2 * need_hh))
                zs[i] = max(Z_HARD, min(zs[i], z_fit))
                hw, hh = cw / (2 * zs[i]), ch / (2 * zs[i])
            lo = max(rx) + pad - hw
            hi = min(rx) - pad + hw
            xs[i] = min(max(xs[i], lo), hi) if lo <= hi else (min(rx) + max(rx)) / 2
            lo = max(ry) + pad - hh
            hi = min(ry) - pad + hh
            ys[i] = min(max(ys[i], lo), hi) if lo <= hi else (min(ry) + max(ry)) / 2
            xs[i] = float(np.clip(xs[i], hw, 1 - hw))
            ys[i] = float(np.clip(ys[i], hh, 1 - hh))

    win = smooth_win if n >= smooth_win else max(3, n | 1)
    shift_pass()
    xs = _hann_smooth(xs.astype(np.float32), win).astype(np.float64)
    ys = _hann_smooth(ys.astype(np.float32), win).astype(np.float64)
    zs = _hann_smooth(zs.astype(np.float32), win).astype(np.float64)
    shift_pass()                                   # final, unsmoothed → guaranteed
    hw = cw / (2 * zs)
    hh = ch / (2 * zs)
    xs = np.clip(xs, hw, 1 - hw)
    ys = np.clip(ys, hh, 1 - hh)
    return xs, ys, zs.astype(np.float32)


def from_vision(proxy_path, t0: float, t1: float, vision_rally: dict | None,
                fps: int = config.PROXY_FPS) -> FocusPath | None:
    """Camera path that follows the shuttle.

    The shuttle is the primary follow target: when it is tracked, the camera pans
    so the shuttle sits at frame centre and zooms only as wide as needed to keep
    the nearest player contained (and the far player too when it still fits 9:16).
    Falls back to framing the player(s) on frames with no shuttle, and to a
    shuttle-led full-height slice when pose is too weak to trust the boxes.
    """
    if not vision_rally:
        return None
    pq = float(vision_rally.get("player_quality", 0.0) or 0.0)
    sq = float(vision_rally.get("shuttle_quality", 0.0) or 0.0)
    if pq < 0.28 and sq < 0.22:          # neither players nor shuttle trustworthy
        return None
    player_frames = vision_rally.get("players") or []
    shuttle_frames = vision_rally.get("shuttle") or []
    shuttle_ok = sq >= 0.22
    # When pose is too weak to trust the boxes (e.g. a soft proxy) but the shuttle
    # is well tracked, follow the shuttle directly instead of framing noise.
    shuttle_led = shuttle_ok and pq < 0.28
    n = max(2, int(round((t1 - t0) * fps)))
    times = t0 + np.arange(n, dtype=np.float32) / fps
    cw, ch = _crop_norms(proxy_path)
    tracks = _two_player_tracks(player_frames, times)

    PAD_X, PAD_T, PAD_B = 0.05, 0.10, 0.13   # body padding around a player box
    SHUTTLE_LED_Z = Z_HARD                   # widest tall slice when following alone
    SHUTTLE_LED_CY = 0.55                    # bias vertical so both court halves show
    MIN_HW, MIN_HH = 0.085, 0.135            # zoom floor: don't punch onto the shuttle

    if shuttle_ok:
        shu_x, shu_y = _shuttle_track(shuttle_frames, times)
    else:
        shu_x = shu_y = np.full(n, np.nan, np.float32)

    xs = np.full(n, 0.5, np.float32)
    ys = np.full(n, 0.55, np.float32)
    zs = np.full(n, Z_HARD, np.float32)
    seen = np.zeros(n, dtype=bool)

    def extent(p):
        return (p[0] - p[2] - PAD_X, p[0] + p[2] + PAD_X,
                p[1] - p[3] - PAD_T, p[1] + p[3] + PAD_B)

    def zoom_for(a, b, c, d):
        return min(cw / max(b - a, 0.12), ch / max(d - c, 0.18))

    def fit_zoom(half_w, half_h):
        return min(cw / (2 * max(half_w, MIN_HW)), ch / (2 * max(half_h, MIN_HH)))

    for i in range(n):
        sx, sy = float(shu_x[i]), float(shu_y[i])
        has_shuttle = not np.isnan(sx)
        near, far = tracks[i]
        anchor = near or far

        # (a) Follow the shuttle HORIZONTALLY; keep the nearest player contained and
        #     stay anchored to the court vertically (never chase a high shuttle into
        #     the ceiling — the tall 9:16 crop contains the airborne shuttle anyway).
        if has_shuttle and anchor is not None and not shuttle_led:
            nxlo, nxhi, nylo, nyhi = extent(anchor)
            need_w = max(abs(sx - nxlo), abs(nxhi - sx))    # contain near player around shuttle x
            vlo, vhi = min(nylo, sy), max(nyhi, sy)         # vertical span: player + shuttle
            if near and far:                                # include far player if it still fits
                fxlo, fxhi, fylo, fyhi = extent(far)
                fw = max(abs(sx - fxlo), abs(fxhi - sx))
                fvlo, fvhi = min(vlo, fylo), max(vhi, fyhi)
                if fit_zoom(max(need_w, fw), (fvhi - fvlo) / 2) >= Z_HARD:
                    need_w, vlo, vhi = max(need_w, fw), fvlo, fvhi
            z = float(np.clip(fit_zoom(need_w, (vhi - vlo) / 2), Z_HARD, Z_MAX))
            hw, hh = cw / (2 * z), ch / (2 * z)
            # x centres on the shuttle (slides only to keep the player in frame);
            # y centres on the player+shuttle span, so the court stays anchored.
            cx = float(np.clip(sx, nxhi - hw, nxlo + hw)) if (nxhi - nxlo) <= 2 * hw else sx
            cy = (vlo + vhi) / 2
            xs[i], ys[i], zs[i], seen[i] = np.clip(cx, hw, 1 - hw), np.clip(cy, hh, 1 - hh), z, True
            continue

        # (b) Shuttle-led (weak pose) or no player: centre the shuttle in the slice.
        if has_shuttle and (shuttle_led or anchor is None):
            z = float(np.clip(SHUTTLE_LED_Z, Z_HARD, Z_MAX))
            hw, hh = cw / (2 * z), ch / (2 * z)
            xs[i] = np.clip(sx, hw, 1.0 - hw)
            ys[i] = np.clip(0.5 * sy + 0.5 * SHUTTLE_LED_CY, hh, 1.0 - hh)
            zs[i], seen[i] = z, True
            continue

        # (c) No shuttle this frame: frame the player(s).
        if anchor is None:
            continue
        nxlo, nxhi, nylo, nyhi = extent(anchor)
        bxlo, bxhi, bylo, byhi = nxlo, nxhi, nylo, nyhi
        if near and far:
            fxlo, fxhi, fylo, fyhi = extent(far)
            bxlo, bxhi = min(bxlo, fxlo), max(bxhi, fxhi)
            bylo, byhi = min(bylo, fylo), max(byhi, fyhi)
        z_both = zoom_for(bxlo, bxhi, bylo, byhi)
        if z_both >= Z_HARD:
            cx, cy, z = (bxlo + bxhi) / 2, (bylo + byhi) / 2, z_both
        else:
            z = max(zoom_for(nxlo, nxhi, nylo, nyhi), Z_HARD)
            cx, cy = (nxlo + nxhi) / 2, (nylo + nyhi) / 2
        z = float(np.clip(z * 0.97, Z_HARD, Z_MAX))
        hw, hh = cw / (2 * z), ch / (2 * z)
        xs[i], ys[i], zs[i], seen[i] = np.clip(cx, hw, 1 - hw), np.clip(cy, hh, 1 - hh), z, True

    if seen.mean() < 0.15:
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
    # Zoom gets a wider window than pan: zoom "breathing" reads much worse than a
    # slightly lagged pan, so smooth z over ~2x the pan window.
    zwin = min(n | 1, win * 2 + 1)
    zs = _hann_smooth(zs, zwin)
    hw = cw / (2 * zs)
    hh = ch / (2 * zs)
    xs = _solve_smooth_path(xs.astype(np.float64), hw.astype(np.float64),
                            (1.0 - hw).astype(np.float64), beta=5e4, w_bound=600.0)
    ys = _solve_smooth_path(ys.astype(np.float64), hh.astype(np.float64),
                            (1.0 - hh).astype(np.float64), beta=2e4, w_bound=600.0)
    # Keep-in-frame guarantee: never let smoothing drag the crop off the shuttle
    # or the near player (shift + zoom-out where required, lightly re-smoothed).
    # In shuttle-led mode the boxes are untrusted, so only the shuttle is required.
    xs, ys, zs = _contain_targets(xs, ys, zs, cw, ch, shu_x, shu_y,
                                  [] if shuttle_led else tracks)
    return FocusPath(t0=t0, fps=fps, xs=xs, ys=ys, zs=zs.astype(np.float32))


def from_camera_plan(proxy_path, t0: float, t1: float, vision_rally: dict | None,
                     kfs: list, fps: int = config.PROXY_FPS,
                     crop_norms: tuple | None = None) -> "FocusPath | None":
    """Bake a user-authored camera plan (TASK-014) into a FocusPath for one rally.

    ``kfs`` are this rally's keyframes in SOURCE time, sorted-or-not, each a dict
    ``{t, target: shuttle|player|point, target_player, point: {x, y}, zoom}``. The
    follow centre per frame is resolved from the rally vision (shuttle / players)
    for shuttle|player targets or the fixed point; zoom interpolates between
    keyframes. Centres are clamped so the 9:16 crop stays in-frame, then smoothed
    with the same solver as :func:`from_vision` so the manual camera moves as
    cleanly as the auto one. Returns ``None`` when there are no keyframes (caller
    falls back to the auto camera).

    Player identity here uses the near/far ordering (target_player 0 = near court,
    1 = far) — a singles approximation; unifying it with the editor's per-player
    ids is a follow-up.
    """
    if not kfs:
        return None
    kfs = sorted(kfs, key=lambda k: float(k.get("t", 0.0) or 0.0))
    n = max(2, int(round((t1 - t0) * fps)))
    times = t0 + np.arange(n, dtype=np.float32) / fps
    cw, ch = crop_norms if crop_norms is not None else _crop_norms(proxy_path)
    shuttle_frames = (vision_rally or {}).get("shuttle") or []
    player_frames = (vision_rally or {}).get("players") or []
    shu_x, shu_y = _shuttle_track(shuttle_frames, times)
    tracks = _two_player_tracks(player_frames, times)
    Z_PLAN_MAX = 2.5  # manual zoom ceiling (the auto Z_MAX is intentionally gentler)

    def _active(t):
        a, b = kfs[0], None
        for i, k in enumerate(kfs):
            if float(k.get("t", 0.0) or 0.0) <= t:
                a, b = k, (kfs[i + 1] if i + 1 < len(kfs) else None)
        return a, b

    xs = np.full(n, 0.5, np.float32)
    ys = np.full(n, 0.55, np.float32)
    zs = np.full(n, Z_HARD, np.float32)
    last_cx, last_cy = 0.5, 0.55
    for i in range(n):
        t = float(times[i])
        a, b = _active(t)
        # zoom interpolation between the active keyframe and the next
        za = float(a.get("zoom", 1.4) or 1.4)
        if b is not None:
            ta, tb = float(a.get("t", 0.0) or 0.0), float(b.get("t", 0.0) or 0.0)
            if tb > ta:
                f = min(1.0, max(0.0, (t - ta) / (tb - ta)))
                za += (float(b.get("zoom", za) or za) - za) * f
        z = float(np.clip(za, Z_HARD, Z_PLAN_MAX))
        # resolve the follow centre for the active target
        tgt = a.get("target", "shuttle")
        cx = cy = None
        if tgt == "point":
            pt = a.get("point") or {}
            cx, cy = float(pt.get("x", 0.5)), float(pt.get("y", 0.45))
        elif tgt == "player":
            near, far = tracks[i]
            box = (far if int(a.get("target_player", 0) or 0) == 1 else near) or near or far
            if box is not None:
                cx, cy = float(box[0]), float(box[1])
        else:  # shuttle
            if not np.isnan(shu_x[i]):
                cx, cy = float(shu_x[i]), float(shu_y[i])
        if cx is None:
            cx, cy = last_cx, last_cy   # hold last good centre on a momentary loss
        last_cx, last_cy = cx, cy
        hw, hh = cw / (2 * z), ch / (2 * z)
        xs[i], ys[i], zs[i] = np.clip(cx, hw, 1 - hw), np.clip(cy, hh, 1 - hh), z

    # Lighter smoothing than the auto camera (a ~0.5s Hann window, no heavy path
    # solver): the user authored these targets explicitly, so follow them faithfully
    # while still de-jittering. Clamp again so the crop stays in-frame after smoothing.
    win = max(3, (fps // 2) | 1)
    xs = _hann_smooth(xs, win)
    ys = _hann_smooth(ys, win)
    zs = _hann_smooth(zs, win)
    hw = cw / (2 * zs)
    hh = ch / (2 * zs)
    xs = np.clip(xs, hw, 1 - hw).astype(np.float32)
    ys = np.clip(ys, hh, 1 - hh).astype(np.float32)
    return FocusPath(t0=t0, fps=fps, xs=xs, ys=ys, zs=zs.astype(np.float32))


def camera_segment_for_rally(camera: dict | None, reel_t0: float, reel_t1: float,
                             source_t0: float) -> list:
    """Slice a reel-global camera plan to one rally's reel span and map its keyframes
    into that rally's SOURCE time, for :func:`from_camera_plan`.

    The editor authors keyframes against reel (stitched) time; the render works per
    rally in source time. ``reel_t0..reel_t1`` is this rally's span in the reel and
    ``source_t0`` its proxy start. The segment is seeded with the keyframe active at
    ``reel_t0`` (so the rally opens with a defined target) plus any keyframes falling
    inside the span, each shifted to source time. Returns [] when the camera is off
    or has no keyframes (caller then uses the auto camera).
    """
    if not camera or not camera.get("enabled"):
        return []
    kfs = sorted(camera.get("keyframes") or [], key=lambda k: float(k.get("t", 0.0) or 0.0))
    if not kfs:
        return []
    active = kfs[0]
    for k in kfs:
        if float(k.get("t", 0.0) or 0.0) <= reel_t0:
            active = k
    seg = [{**active, "t": source_t0}]
    for k in kfs:
        kt = float(k.get("t", 0.0) or 0.0)
        if reel_t0 < kt < reel_t1:
            seg.append({**k, "t": source_t0 + (kt - reel_t0)})
    return seg
