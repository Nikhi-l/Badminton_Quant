"""Annotated analysis preview (TASK-041): shuttle + pose burned into pixels.

The Studio draws overlays live in the browser — subject to layer toggles,
interpolation windows, and paint timing (the "marker lags the shuttle"
review item). This renderer bakes the SAME stored tracks into
``annotated.mp4`` at exact frame times: what you see is precisely what the
models measured, with zero live-render latency. Proxy-resolution and
analysis-styled on purpose — it is a QA/debug artifact, not the product reel
(which stays clean). The drawing primitives are shared with the Gemini frame
evaluator (evaluate.py), so what Gemini judges is what users see.

Only shuttle + players/pose are drawn (owner spec: "only these two
annotations").
"""
from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from .. import config
from . import media

POSE_LIMBS = [(5, 7), (7, 9), (6, 8), (8, 10), (5, 6), (5, 11), (6, 12),
              (11, 12), (11, 13), (13, 15), (12, 14), (14, 16)]
# RGB (frames from media.iter_frames are RGB)
PLAYER_COLORS = [(183, 245, 66), (106, 165, 255), (255, 209, 102), (255, 125, 156)]
SHUTTLE_RGB = (183, 245, 66)
KP_MIN_CONF = 0.15
TRAIL_SEC = 0.6
PAD_SEC = 0.5


def _color(track_id) -> tuple[int, int, int]:
    try:
        return PLAYER_COLORS[int(track_id) % len(PLAYER_COLORS)]
    except (TypeError, ValueError):
        return PLAYER_COLORS[0]


def _nearest(frames: list, t: float, window: float = 0.35) -> dict | None:
    best, delta = None, window
    for f in frames or []:
        d = abs(float(f.get("t", 0.0)) - t)
        if d <= delta:
            best, delta = f, d
    return best


def draw_players(frame: np.ndarray, boxes: list, label_prefix: str = "P") -> None:
    """Boxes + id tags, in place. ``boxes`` are stored-raw {x1..y2, track_id}."""
    h, w = frame.shape[:2]
    for b in boxes or []:
        try:
            x1, y1 = int(float(b["x1"]) * w), int(float(b["y1"]) * h)
            x2, y2 = int(float(b["x2"]) * w), int(float(b["y2"]) * h)
        except (KeyError, TypeError, ValueError):
            continue
        tid = b.get("track_id")
        color = _color(tid)
        cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
        tag = f"{label_prefix}{tid}" if tid is not None else label_prefix
        cv2.rectangle(frame, (x1, max(0, y1 - 18)), (x1 + 14 + 11 * len(tag), y1), color, -1)
        cv2.putText(frame, tag, (x1 + 4, max(12, y1 - 5)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, (10, 12, 8), 1, cv2.LINE_AA)


def draw_pose(frame: np.ndarray, people: list) -> None:
    """COCO-17 skeletons, in place — same limb set and gate the Studio uses."""
    h, w = frame.shape[:2]
    for person in people or []:
        kps = person.get("keypoints") or []
        color = _color(person.get("track_id", 0))
        pts = []
        for kp in kps[:17]:
            try:
                ok = float(kp.get("confidence", 0.0)) >= KP_MIN_CONF
                pts.append((int(float(kp["x"]) * w), int(float(kp["y"]) * h)) if ok else None)
            except (KeyError, TypeError, ValueError):
                pts.append(None)
        for a, b in POSE_LIMBS:
            if a < len(pts) and b < len(pts) and pts[a] and pts[b]:
                cv2.line(frame, pts[a], pts[b], color, 2, cv2.LINE_AA)
        for i, pt in enumerate(pts):
            if pt and i not in (1, 2, 3, 4):
                cv2.circle(frame, pt, 3, color, -1, cv2.LINE_AA)


def draw_shuttle(frame: np.ndarray, track: list, t: float) -> None:
    """Marker + fading trail from the stored (already filtered+gated) track."""
    h, w = frame.shape[:2]
    recent = [p for p in track or []
              if t - TRAIL_SEC <= float(p.get("t", 0.0)) <= t + 1e-3
              and float(p.get("confidence", 0.0)) >= 0.3]
    if not recent:
        return
    recent.sort(key=lambda p: float(p["t"]))
    if float(recent[-1]["t"]) < t - 0.35:
        return                      # real dropout: draw nothing, not a stale marker
    pix = [(int(float(p["x"]) * w), int(float(p["y"]) * h)) for p in recent]
    for i in range(1, len(pix)):
        alpha = i / len(pix)
        cv2.line(frame, pix[i - 1], pix[i], SHUTTLE_RGB, max(1, int(1 + 2 * alpha)), cv2.LINE_AA)
    cv2.circle(frame, pix[-1], 7, SHUTTLE_RGB, 2, cv2.LINE_AA)
    cv2.circle(frame, pix[-1], 2, (255, 255, 255), -1, cv2.LINE_AA)


def annotate_frame(frame: np.ndarray, vision_rally: dict, t: float) -> np.ndarray:
    """Draw shuttle + players + pose for source-time ``t`` on one RGB frame."""
    players = _nearest(vision_rally.get("players") or [], t)
    if players:
        draw_players(frame, players.get("boxes") or [])
    pose = _nearest(vision_rally.get("poses") or [], t)
    if pose:
        draw_pose(frame, pose.get("people") or [])
    draw_shuttle(frame, vision_rally.get("shuttle") or [], t)
    return frame


def render_annotated(workdir: Path, result: dict, log=print) -> Path | None:
    """Bake ``annotated.mp4`` (all reel rallies, chronological, with ambient
    audio) from the analysis proxy + stored tracks. Returns the path or None
    when there is nothing to draw."""
    workdir = Path(workdir)
    proxy = workdir / "proxy.mp4"
    rallies = [rr for rr in (result.get("rallies") or [])
               if isinstance(rr, dict) and isinstance(rr.get("vision"), dict)]
    if not proxy.exists() or not rallies:
        return None
    info = media.probe(proxy)
    fps = max(10, int(round(info.fps)))
    clips: list[Path] = []
    for i, rr in enumerate(sorted(rallies, key=lambda r: float(r.get("start", 0.0)))):
        t0 = max(0.0, float(rr.get("src_start", rr.get("start", 0.0))) - PAD_SEC)
        t1 = min(info.duration, float(rr.get("end", 0.0)) + PAD_SEC)
        if t1 - t0 < 0.5:
            continue
        clip = workdir / f"annotated_{i:02d}.mp4"
        writer = media.FrameWriter(clip, info.width, info.height, fps, proxy, t0, t1)
        try:
            # iter_frames yields (index, frame) pairs — unpack, don't enumerate
            # (a tuple fed to numpy was the inhomogeneous-shape crash).
            for j, frame in media.iter_frames(proxy, t0, t1, fps=fps):
                frame = np.ascontiguousarray(frame)
                annotate_frame(frame, rr["vision"], t0 + j / fps)
                writer.write(frame)
        finally:
            writer.close()
        clips.append(clip)
    if not clips:
        return None
    out = workdir / "annotated.mp4"
    media.normalize_concat(clips, out, log=log) if len(clips) > 1 else clips[0].rename(out)
    for c in clips:
        c.unlink(missing_ok=True)
    log(f"annotated preview: {out.name} ({len(rallies)} rallies)")
    return out


def evaluation_frames(workdir: Path, rally: dict, n: int = 2) -> list[np.ndarray]:
    """Player-annotated RGB frames from a rally for the Gemini evaluator —
    drawn with the exact primitives the annotated preview uses, labels =
    worker track ids (``P<track_id>``)."""
    proxy = Path(workdir) / "proxy.mp4"
    vision = rally.get("vision") or {}
    frames_meta = vision.get("players") or []
    if not proxy.exists() or not frames_meta:
        return []
    # frames with the most boxes → Gemini sees every tracked person at once
    ranked = sorted(frames_meta, key=lambda f: len(f.get("boxes") or []), reverse=True)
    picks = ranked[:n]
    cap = cv2.VideoCapture(str(proxy))
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    out = []
    try:
        for f in picks:
            cap.set(cv2.CAP_PROP_POS_FRAMES, max(0, int(round(float(f.get("t", 0.0)) * fps))))
            ok, bgr = cap.read()
            if not ok:
                continue
            rgb = np.ascontiguousarray(bgr[:, :, ::-1])
            draw_players(rgb, f.get("boxes") or [])
            out.append(rgb)
    finally:
        cap.release()
    return out
