"""Temporal signal smoothing for vision tracks (TASK-031).

One-Euro filter (Casiez et al., CHI 2012): an adaptive low-pass whose cutoff
rises with signal speed — near-static keypoints stop jittering while fast
racquet-arm swings pass through with minimal lag. This is the standard online
choice for pose streams; keypoints arrive at ~6 Hz with real timestamps, so the
filter integrates dt directly instead of assuming a frame rate.
"""
from __future__ import annotations

import math

# Tuned for normalized coordinates sampled at ~6 Hz: a smash wrist travels
# ~1-2 frame-widths/second, idle joints under 0.05/s. min_cutoff kills the
# sub-Hz jitter; beta opens the filter up as speed rises.
MIN_CUTOFF = 1.0
BETA = 1.5
D_CUTOFF = 1.0
# A person id that vanishes for longer than this gets a fresh filter — carrying
# state across a long dropout would smear the re-entry position.
RESET_GAP_SEC = 1.5


def _alpha(dt: float, cutoff: float) -> float:
    tau = 1.0 / (2.0 * math.pi * max(cutoff, 1e-6))
    return 1.0 / (1.0 + tau / max(dt, 1e-6))


class OneEuro:
    """Scalar one-euro filter fed (t, value) pairs with monotonic t."""

    def __init__(self, min_cutoff: float = MIN_CUTOFF, beta: float = BETA,
                 d_cutoff: float = D_CUTOFF):
        self.min_cutoff = min_cutoff
        self.beta = beta
        self.d_cutoff = d_cutoff
        self._t: float | None = None
        self._x: float = 0.0
        self._dx: float = 0.0

    def __call__(self, t: float, x: float) -> float:
        if self._t is None or t <= self._t:
            self._t, self._x, self._dx = t, x, 0.0
            return x
        dt = t - self._t
        dx = (x - self._x) / dt
        self._dx = self._dx + _alpha(dt, self.d_cutoff) * (dx - self._dx)
        cutoff = self.min_cutoff + self.beta * abs(self._dx)
        self._x = self._x + _alpha(dt, cutoff) * (x - self._x)
        self._t = t
        return self._x


def smooth_pose_track(track: list[dict]) -> list[dict]:
    """Smooth pose_track keypoints in place, per (person id, keypoint, axis).

    ``track`` is the public shape [{t, people: [{id, keypoints: [{x, y,
    confidence}]}]}]. Low-confidence keypoints (<0.15) pass through untouched
    and don't feed the filter — a garbage detection must not drag the smoothed
    joint. Ids without a filter yet (or returning after RESET_GAP_SEC) start
    fresh at the observed position.
    """
    filters: dict[tuple, tuple[float, list]] = {}   # (id, kp_idx) -> (t_last, [fx, fy])
    for frame in track or []:
        try:
            t = float(frame.get("t", 0.0))
        except (TypeError, ValueError):
            continue
        for person in frame.get("people") or []:
            pid = person.get("id")
            if pid is None:
                continue
            for ki, kp in enumerate(person.get("keypoints") or []):
                try:
                    x, y, conf = float(kp["x"]), float(kp["y"]), float(kp.get("confidence", 0.0))
                except (KeyError, TypeError, ValueError):
                    continue
                if conf < 0.15:
                    continue
                key = (pid, ki)
                state = filters.get(key)
                if state is None or t - state[0] > RESET_GAP_SEC:
                    state = (t, [OneEuro(), OneEuro()])
                    state[1][0](t, x)
                    state[1][1](t, y)
                    filters[key] = (t, state[1])
                    continue
                fx, fy = state[1]
                kp["x"] = round(fx(t, x), 5)
                kp["y"] = round(fy(t, y), 5)
                filters[key] = (t, state[1])
    return track
