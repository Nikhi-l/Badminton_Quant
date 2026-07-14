"""Identity and kinematic pose sanitation (TASK-044, plan 2026-07-14 §4).

Runs on the PUBLIC pose track after player ids are assigned and BEFORE the
One-Euro smoother: rejection first, smoothing second. One-Euro is a jitter
filter, not an outlier detector — a same-id, high-confidence joint teleport
``x=0.10 → 0.90 → 0.12`` came out ``0.10 → 0.7645 → 0.317``: softened, never
rejected, and it contaminated the next frame's filter state.

Three checks, all body-scale-relative (a far player and a near player occupy
very different pixel scales):

1. **Whole-person displacement gate.** A same-id person whose center moves
   further than a body can move in the elapsed time is an IDENTITY TRANSITION
   (the tracker or slot fallback attached the id to a different person). The
   detection itself is fine — a real player stands there — so nothing is
   rejected; instead the person starts a new segment (``seg`` increments),
   every joint state re-seeds, and downstream consumers (One-Euro, Studio
   interpolation) must never bridge the break. Long dropouts (> the smoother's
   reset gap) also start a new segment: honest re-entry, no false glide.

2. **Per-joint displacement gate.** Within a segment, a joint that jumps
   further than its group's speed cap allows is a false measurement: its
   confidence is zeroed (every consumer — smoother, Studio, analytics — gates
   at ≥0.15, so it becomes missing data) and it carries ``rejected: true`` —
   provenance, not deletion. Rejected measurements never update the reference
   state; after MAX_CONSEC_REJECT consecutive rejections the joint re-seeds
   (the world really changed — accept it rather than reject forever).

   Gates use zero-velocity prediction (displacement over elapsed time), not a
   constant-velocity extrapolation: at the 6 Hz cadence a smash wrist
   legitimately reverses direction between adjacent samples, and CV prediction
   overshoots exactly there (see the plan §4.2 implementation note). Speed
   caps are per joint group — wrists genuinely cover ~2 frame-widths/s in a
   smash; hips do not.

3. **Bone-surge gate.** 2D projection can only SHORTEN a bone
   (foreshortening); it can never lengthen one past the player's true reach.
   A limb bone suddenly exceeding its rolling maximum observed length is a
   wrong attachment (typically a wrist grabbed from the opponent), so the
   child joint is rejected. Re-extension after foreshortening never trips
   this, and enforcement waits for BONE_MIN_OBS accepted observations.
"""
from __future__ import annotations

import math

MIN_CONF = 0.15            # matches the smoother/render/analytics gates
SEG_RESET_GAP_SEC = 1.5    # matches smooth.RESET_GAP_SEC — honest re-entry
DT_CAP_SEC = 0.7           # gate growth stops here; longer is a reacquisition
CENTER_SPEED_CAP = 2.6     # body-heights/s — sprint + lunge headroom
CENTER_NOISE = 0.18        # body-heights — box/center detector jitter floor
JOINT_NOISE = 0.14         # body-heights — keypoint jitter floor
MAX_CONSEC_REJECT = 3
BONE_SURGE_RATIO = 1.75
BONE_MIN_OBS = 3

# COCO-17 joint groups: the torso tracks the body; distal joints whip.
_TORSO = (0, 1, 2, 3, 4, 5, 6, 11, 12)
_MID = (7, 8, 13, 14)          # elbows, knees
_DISTAL = (9, 10, 15, 16)      # wrists, ankles
JOINT_SPEED_CAP = {**{i: 3.0 for i in _TORSO},
                   **{i: 4.5 for i in _MID},
                   **{i: 7.0 for i in _DISTAL}}   # body-heights/s

# child joint -> parent joint for the limb bones (parent index < child index,
# so the parent's accept/reject verdict for this frame is already known).
_PARENT = {7: 5, 8: 6, 9: 7, 10: 8, 13: 11, 14: 12, 15: 13, 16: 14}


def _center_scale(person: dict, kps: list[dict]) -> tuple[float, float, float] | None:
    """(cx, cy, body_scale) — bbox when present, else confident keypoints."""
    bbox = person.get("bbox")
    if isinstance(bbox, dict):
        try:
            cx, cy, h = float(bbox["x"]), float(bbox["y"]), float(bbox["h"])
            if h > 0.02:
                return cx, cy, h
        except (KeyError, TypeError, ValueError):
            pass
    xs, ys = [], []
    for kp in kps:
        try:
            if float(kp.get("confidence", 0.0)) >= MIN_CONF:
                xs.append(float(kp["x"]))
                ys.append(float(kp["y"]))
        except (KeyError, TypeError, ValueError):
            continue
    if not xs:
        return None
    scale = max(max(ys) - min(ys), 0.05) if len(ys) >= 2 else 0.25
    return sum(xs) / len(xs), sum(ys) / len(ys), scale


def _reject(kp: dict) -> None:
    kp["confidence"] = 0.0     # every consumer gates at >=0.15: missing data
    kp["rejected"] = True      # provenance — the observation existed


def sanitize_pose_track(track: list[dict], stats: dict | None = None) -> list[dict]:
    """Sanitize the public pose track in place; returns it for chaining.

    ``track`` is the public shape [{t, people: [{id, keypoints: [...]}]}] with
    ids already assigned. Emits ``seg`` on a person only when > 0 (payload
    thrift; absent means segment 0). ``stats`` (optional dict) receives
    counters for tests/telemetry: person_breaks, joint_rejects, bone_rejects.
    """
    persons: dict[int, dict] = {}          # pid -> {t, cx, cy, scale, seg}
    joints: dict[tuple, dict] = {}         # (pid, seg, ki) -> {t, x, y, rej}
    bones: dict[tuple, dict] = {}          # (pid, seg, child_ki) -> {max, n}
    counters = {"person_breaks": 0, "joint_rejects": 0, "bone_rejects": 0}
    for frame in track or []:
        try:
            t = float(frame.get("t", 0.0))
        except (TypeError, ValueError):
            continue
        for person in frame.get("people") or []:
            pid = person.get("id")
            if pid is None:
                continue
            kps = person.get("keypoints") or []
            cs = _center_scale(person, kps)
            if cs is None:
                continue
            cx, cy, scale = cs
            st = persons.get(pid)
            seg = st["seg"] if st else 0
            if st is not None:
                dt = max(t - st["t"], 1e-3)
                avg_scale = (scale + st["scale"]) / 2.0
                gate = (CENTER_SPEED_CAP * min(dt, DT_CAP_SEC) + CENTER_NOISE) * avg_scale
                if dt > SEG_RESET_GAP_SEC:
                    seg += 1               # long dropout: honest re-entry
                elif math.hypot(cx - st["cx"], cy - st["cy"]) > gate:
                    seg += 1               # identity transition, not motion
                    counters["person_breaks"] += 1
            persons[pid] = {"t": t, "cx": cx, "cy": cy, "scale": scale, "seg": seg}
            if seg:
                person["seg"] = seg

            for ki, kp in enumerate(kps[:17]):
                try:
                    conf = float(kp.get("confidence", 0.0))
                    x, y = float(kp["x"]), float(kp["y"])
                except (KeyError, TypeError, ValueError):
                    continue
                if conf < MIN_CONF:
                    continue               # passthrough; never feeds state
                key = (pid, seg, ki)
                jst = joints.get(key)
                if jst is not None and t - jst["t"] <= SEG_RESET_GAP_SEC:
                    dt = max(t - jst["t"], 1e-3)
                    gate = (JOINT_SPEED_CAP[ki] * min(dt, DT_CAP_SEC)
                            + JOINT_NOISE) * scale
                    if math.hypot(x - jst["x"], y - jst["y"]) > gate:
                        jst["rej"] += 1
                        if jst["rej"] <= MAX_CONSEC_REJECT:
                            _reject(kp)
                            counters["joint_rejects"] += 1
                            continue       # state untouched: no contamination
                        jst = None         # world really changed: re-seed below
                elif jst is not None:
                    jst = None             # stale within-segment state

                parent = _PARENT.get(ki)
                if parent is not None and parent < len(kps):
                    pkp = kps[parent]
                    try:
                        p_ok = (not pkp.get("rejected")
                                and float(pkp.get("confidence", 0.0)) >= MIN_CONF)
                        px, py = float(pkp["x"]), float(pkp["y"])
                    except (KeyError, TypeError, ValueError):
                        p_ok = False
                    if p_ok:
                        blen = math.hypot(x - px, y - py) / max(scale, 1e-6)
                        bst = bones.setdefault((pid, seg, ki), {"max": 0.0, "n": 0})
                        if (bst["n"] >= BONE_MIN_OBS
                                and blen > bst["max"] * BONE_SURGE_RATIO):
                            _reject(kp)
                            counters["bone_rejects"] += 1
                            if jst is not None:
                                jst["rej"] += 1   # persistent surges re-seed too
                            continue
                        bst["max"] = max(bst["max"], blen)
                        bst["n"] += 1

                joints[key] = {"t": t, "x": x, "y": y, "rej": 0}
    if stats is not None:
        stats.update(counters)
    return track
