"""Runpod Serverless worker for Baddy vision enrichment.

The worker consumes the app's `baddy.vision.v1` input contract and returns
normalized player, pose, racquet, and shuttle signals. It is intentionally
model-pluggable: set YOLO_POSE_MODEL and RACQUET_MODEL to local model paths in
the container, or let the worker run with motion-only fallbacks while models are
being tuned.
"""
from __future__ import annotations

import json
import math
import os
import subprocess
import tempfile
import time
import csv
from pathlib import Path
from typing import Any

import cv2
import numpy as np
import requests
import runpod

CONTRACT = "baddy.vision.v1"
WORKER_VERSION = os.environ.get("BADDY_WORKER_VERSION", "bytetrack-20260707")
SAMPLE_FPS = float(os.environ.get("BADDY_SAMPLE_FPS", "6"))
MAX_FRAMES_PER_RALLY = int(os.environ.get("BADDY_MAX_FRAMES_PER_RALLY", "180"))
YOLO_POSE_MODEL = os.environ.get("YOLO_POSE_MODEL",
                                 os.environ.get("POSE_MODEL_GPU", "yolo26m-pose.pt"))
YOLO_POSE_FALLBACK = os.environ.get("YOLO_POSE_FALLBACK",
                                    os.environ.get("POSE_MODEL_FALLBACK", "yolo11n-pose.pt"))
RACQUET_MODEL = os.environ.get("RACQUET_MODEL", "")
YOLO_CONF = float(os.environ.get("YOLO_CONF", "0.25"))
YOLO_IMGSZ = int(os.environ.get("YOLO_IMGSZ", "640"))
DEVICE = os.environ.get("YOLO_DEVICE", "0")
TRACKNET_REPO = os.environ.get("TRACKNET_REPO", "")
TRACKNET_TRACKNET_FILE = os.environ.get("TRACKNET_TRACKNET_FILE", "")
TRACKNET_INPAINTNET_FILE = os.environ.get("TRACKNET_INPAINTNET_FILE", "")
TRACKNET_TIMEOUT_SEC = int(os.environ.get("TRACKNET_TIMEOUT_SEC", "900"))
TRACKNET_BATCH_SIZE = int(os.environ.get("TRACKNET_BATCH_SIZE", "8"))
# 'nonoverlap' samples each frame once (~8x fewer windows than 'weight'); far
# cheaper GPU time per reel, plenty for camera framing. Matches the local engine.
TRACKNET_EVAL_MODE = os.environ.get("TRACKNET_EVAL_MODE", "nonoverlap")

_pose_model = None
_pose_model_path = ""
_racquet_model = None
_model_error = ""
_tracknet_error = ""
_track_error = ""   # ByteTrack unavailable -> plain predict + downstream id heuristic


def _load_models(pose_model: str | None = None) -> None:
    """Load heavy models once per worker process."""
    global _pose_model, _pose_model_path, _racquet_model, _model_error
    desired_pose = str(pose_model or YOLO_POSE_MODEL or "").strip()
    if _pose_model is not None and (_pose_model_path == desired_pose or not desired_pose):
        return
    try:
        from ultralytics import YOLO
    except Exception as exc:  # noqa: BLE001 - fallbacks still produce a valid contract.
        _model_error = f"{type(exc).__name__}: {exc}"
        return

    errors = []
    _pose_model = None
    _pose_model_path = ""
    candidates = []
    for candidate in (desired_pose, YOLO_POSE_FALLBACK):
        candidate = str(candidate or "").strip()
        if candidate and candidate not in candidates:
            candidates.append(candidate)
    for candidate in candidates:
        try:
            _pose_model = YOLO(candidate)
            _pose_model_path = candidate
            break
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{Path(candidate).name}: {type(exc).__name__}: {exc}")
    if not _pose_model and candidates:
        _model_error = "; ".join(errors)
    try:
        if RACQUET_MODEL and _racquet_model is None:
            _racquet_model = YOLO(RACQUET_MODEL)
    except Exception as exc:  # noqa: BLE001 - fallbacks still produce a valid contract.
        _model_error = f"{type(exc).__name__}: {exc}"


def _num(v: Any, default: float = 0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _clamp01(v: Any, default: float = 0.0) -> float:
    return min(max(_num(v, default), 0.0), 1.0)


def _download(url: str, dst: Path) -> None:
    with requests.get(url, stream=True, timeout=(30, 600)) as resp:
        resp.raise_for_status()
        with dst.open("wb") as f:
            for chunk in resp.iter_content(1024 * 1024):
                if chunk:
                    f.write(chunk)


def _video_meta(path: Path) -> dict:
    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        raise RuntimeError(f"cannot open video: {path}")
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    frames = cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
    cap.release()
    return {"fps": fps, "frames": frames, "width": width, "height": height,
            "duration": frames / fps if fps else 0.0}


def _tracknet_ready() -> bool:
    return bool(
        TRACKNET_REPO
        and TRACKNET_TRACKNET_FILE
        and Path(TRACKNET_REPO, "predict.py").exists()
        and Path(TRACKNET_TRACKNET_FILE).exists()
    )


def _seek_frame(cap, t: float, fps: float) -> tuple[bool, np.ndarray | None]:
    cap.set(cv2.CAP_PROP_POS_FRAMES, max(0, int(round(t * fps))))
    ok, frame = cap.read()
    return bool(ok), frame if ok else None


def _norm_box(x1: float, y1: float, x2: float, y2: float, w: int, h: int, conf: float) -> dict:
    return {
        "box": [
            _clamp01(x1 / max(w, 1)),
            _clamp01(y1 / max(h, 1)),
            _clamp01(x2 / max(w, 1)),
            _clamp01(y2 / max(h, 1)),
        ],
        "confidence": _clamp01(conf, 1.0),
    }


def _box_area(box: dict) -> float:
    x1, y1, x2, y2 = box["box"]
    return max(0.0, x2 - x1) * max(0.0, y2 - y1)


def _detect_pose(frame: np.ndarray, reset_tracker: bool = False) -> tuple[list[dict], list[dict], float]:
    """Detect players + poses; identity comes from ultralytics ByteTrack.

    TASK-024: model.track(persist=True) carries a track id across the sampled
    frames of a rally (the tracker motion-models occlusions the app's serve-time
    centroid heuristic cannot), emitted as ``track_id`` on each box AND its
    paired pose. ``reset_tracker=True`` on a rally's first frame starts a fresh
    id space per rally. Falls back to plain predict when tracking is
    unavailable (missing lap dependency etc.) — downstream keeps its heuristic.
    """
    global _track_error
    if _pose_model is None:
        return [], [], 0.0
    h, w = frame.shape[:2]
    result = None
    if not _track_error:
        try:
            result = _pose_model.track(frame, imgsz=YOLO_IMGSZ, conf=YOLO_CONF,
                                       device=DEVICE, verbose=False,
                                       persist=not reset_tracker,
                                       tracker="bytetrack.yaml")[0]
        except Exception as exc:  # noqa: BLE001 - tracking is an enhancement
            _track_error = f"{type(exc).__name__}: {exc}"
    if result is None:
        result = _pose_model.predict(frame, imgsz=YOLO_IMGSZ, conf=YOLO_CONF,
                                     device=DEVICE, verbose=False)[0]
    players: list[dict] = []
    poses: list[dict] = []
    boxes = getattr(result, "boxes", None)
    keypoints = getattr(result, "keypoints", None)
    if boxes is None:
        return players, poses, 0.0
    xyxy = boxes.xyxy.cpu().numpy() if boxes.xyxy is not None else []
    confs = boxes.conf.cpu().numpy() if boxes.conf is not None else np.ones(len(xyxy))
    ids = boxes.id.cpu().numpy() if getattr(boxes, "id", None) is not None else None
    kxy = keypoints.xy.cpu().numpy() if keypoints is not None and keypoints.xy is not None else []
    kconf = keypoints.conf.cpu().numpy() if keypoints is not None and keypoints.conf is not None else []
    # Keep each box paired with ITS keypoints while sorting — sorting the players
    # list alone desynced poses[i] from players[i], so the app attached player A's
    # bbox to player B's skeleton (and truncation could drop the wrong pose).
    entries: list[tuple[dict, dict | None]] = []
    for i, box in enumerate(xyxy):
        det = _norm_box(box[0], box[1], box[2], box[3], w, h, confs[i])
        if ids is not None and i < len(ids):
            det["track_id"] = int(ids[i])
        pose = None
        if i < len(kxy):
            pts = []
            for j, pt in enumerate(kxy[i]):
                score = float(kconf[i][j]) if i < len(kconf) and j < len(kconf[i]) else 1.0
                pts.append({"x": _clamp01(pt[0] / max(w, 1)),
                            "y": _clamp01(pt[1] / max(h, 1)),
                            "confidence": _clamp01(score, 1.0)})
            pose = {"keypoints": pts,
                    "confidence": float(np.mean([p["confidence"] for p in pts])) if pts else 0.0}
            if "track_id" in det:
                pose["track_id"] = det["track_id"]
        entries.append((det, pose))
    entries.sort(key=lambda e: (e[0]["confidence"], _box_area(e[0])), reverse=True)
    entries = entries[:2]
    players = [e[0] for e in entries]
    # Placeholder keeps poses index-aligned with players when keypoints are missing.
    poses = [e[1] or {"keypoints": [], "confidence": 0.0} for e in entries]
    pose_quality = float(np.mean([p["confidence"] for p in poses])) if poses else 0.0
    return players, poses, _clamp01(pose_quality)


def _detect_racquet(frame: np.ndarray) -> tuple[list[dict], float]:
    if _racquet_model is None:
        return [], 0.0
    h, w = frame.shape[:2]
    result = _racquet_model.predict(frame, imgsz=YOLO_IMGSZ, conf=YOLO_CONF,
                                    device=DEVICE, verbose=False)[0]
    boxes = getattr(result, "boxes", None)
    if boxes is None:
        return [], 0.0
    names = getattr(result, "names", {}) or {}
    xyxy = boxes.xyxy.cpu().numpy() if boxes.xyxy is not None else []
    confs = boxes.conf.cpu().numpy() if boxes.conf is not None else np.ones(len(xyxy))
    classes = boxes.cls.cpu().numpy() if boxes.cls is not None else np.zeros(len(xyxy))
    detections = []
    for box, conf, cls in zip(xyxy, confs, classes):
        label = str(names.get(int(cls), "")).lower()
        if RACQUET_MODEL and label and "racquet" not in label and "racket" not in label:
            continue
        detections.append(_norm_box(box[0], box[1], box[2], box[3], w, h, conf))
    detections.sort(key=lambda b: b["confidence"], reverse=True)
    quality = float(np.mean([d["confidence"] for d in detections[:2]])) if detections else 0.0
    return detections[:2], _clamp01(quality)


def _pose_point(pose: dict, idx: int) -> tuple[float, float, float] | None:
    pts = pose.get("keypoints") if isinstance(pose, dict) else None
    if not isinstance(pts, list) or idx >= len(pts):
        return None
    p = pts[idx]
    if not isinstance(p, dict) or _num(p.get("confidence")) < 0.25:
        return None
    return _clamp01(p.get("x")), _clamp01(p.get("y")), _clamp01(p.get("confidence"))


def _detect_racquet_candidates(frame: np.ndarray, poses: list[dict]) -> tuple[list[dict], float]:
    """Weak pose-guided racquet candidates near wrists; not detector evidence."""
    h, w = frame.shape[:2]
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    candidates = []
    for pose in poses[:2]:
        for wrist_idx, elbow_idx in ((9, 7), (10, 8)):
            wrist = _pose_point(pose, wrist_idx)
            if not wrist:
                continue
            elbow = _pose_point(pose, elbow_idx)
            wx, wy, wconf = wrist
            # Crop a hand-zone slightly larger than a racquet head/handle at proxy size.
            r = int(max(24, min(w, h) * 0.08))
            cx, cy = int(wx * w), int(wy * h)
            x1, y1 = max(0, cx - r), max(0, cy - r)
            x2, y2 = min(w, cx + r), min(h, cy + r)
            if x2 - x1 < 16 or y2 - y1 < 16:
                continue
            roi = gray[y1:y2, x1:x2]
            edges = cv2.Canny(cv2.GaussianBlur(roi, (3, 3), 0), 60, 150)
            lines = cv2.HoughLinesP(
                edges,
                rho=1,
                theta=np.pi / 180,
                threshold=12,
                minLineLength=max(10, int(r * 0.45)),
                maxLineGap=5,
            )
            if lines is None:
                continue
            for line in lines[:12]:
                lx1, ly1, lx2, ly2 = [int(v) for v in line[0]]
                length = math.hypot(lx2 - lx1, ly2 - ly1)
                if length < max(10, r * 0.45):
                    continue
                mx, my = x1 + (lx1 + lx2) / 2, y1 + (ly1 + ly2) / 2
                wrist_dist = math.hypot(mx - cx, my - cy) / max(r, 1)
                if wrist_dist > 1.15:
                    continue
                score = 0.12 + min(0.18, length / max(w, h) * 1.7) + wconf * 0.12
                if elbow:
                    ex, ey, _ = elbow
                    arm_angle = math.atan2(wy - ey, wx - ex)
                    line_angle = math.atan2(ly2 - ly1, lx2 - lx1)
                    delta = abs(math.atan2(math.sin(line_angle - arm_angle),
                                           math.cos(line_angle - arm_angle)))
                    # Racquets often extend away from the forearm; reward visible
                    # line evidence without requiring a specific stroke pose.
                    score += min(0.08, delta / math.pi * 0.08)
                pad = 5
                bx1, by1 = x1 + min(lx1, lx2) - pad, y1 + min(ly1, ly2) - pad
                bx2, by2 = x1 + max(lx1, lx2) + pad, y1 + max(ly1, ly2) + pad
                det = _norm_box(bx1, by1, bx2, by2, w, h, min(score, 0.42))
                det["source"] = "pose_guided_line"
                candidates.append(det)
    candidates.sort(key=lambda b: b["confidence"], reverse=True)
    deduped = []
    for cand in candidates:
        cx = (cand["box"][0] + cand["box"][2]) / 2
        cy = (cand["box"][1] + cand["box"][3]) / 2
        if any(abs(cx - (d["box"][0] + d["box"][2]) / 2) < 0.03
               and abs(cy - (d["box"][1] + d["box"][3]) / 2) < 0.03
               for d in deduped):
            continue
        deduped.append(cand)
        if len(deduped) >= 2:
            break
    quality = float(np.mean([d["confidence"] for d in deduped])) if deduped else 0.0
    return deduped, _clamp01(quality)


def _inside_player(px: int, py: int, boxes: list[dict], w: int, h: int) -> bool:
    for det in boxes:
        x1, y1, x2, y2 = det["box"]
        pad_x, pad_y = 0.04, 0.05
        if (x1 - pad_x) * w <= px <= (x2 + pad_x) * w and (y1 - pad_y) * h <= py <= (y2 + pad_y) * h:
            return True
    return False


def _detect_shuttle(frame: np.ndarray, prev_gray: np.ndarray | None,
                    player_boxes: list[dict]) -> tuple[dict | None, np.ndarray]:
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    if prev_gray is None:
        return None, gray
    h, w = gray.shape[:2]
    diff = cv2.absdiff(gray, prev_gray)
    _, mask = cv2.threshold(diff, 28, 255, cv2.THRESH_BINARY)
    mask = cv2.medianBlur(mask, 3)
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    candidates = []
    for c in contours:
        area = cv2.contourArea(c)
        if area < 2 or area > 160:
            continue
        x, y, bw, bh = cv2.boundingRect(c)
        cx, cy = x + bw / 2, y + bh / 2
        if cy < 0.06 * h or _inside_player(int(cx), int(cy), player_boxes, w, h):
            continue
        patch = frame[max(0, y - 1): min(h, y + bh + 1), max(0, x - 1): min(w, x + bw + 1)]
        brightness = float(np.mean(cv2.cvtColor(patch, cv2.COLOR_BGR2GRAY))) if patch.size else 0.0
        score = float(area) * (1.0 + max(0.0, brightness - 90.0) / 120.0)
        candidates.append((score, cx, cy, area))
    if not candidates:
        return None, gray
    score, cx, cy, area = max(candidates, key=lambda x: x[0])
    conf = min(0.92, 0.25 + score / 220.0 + min(area, 60.0) / 220.0)
    return {"x": _clamp01(cx / w), "y": _clamp01(cy / h), "confidence": _clamp01(conf)}, gray


def _cut_clip(src: Path, dst: Path, start: float, end: float) -> None:
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-ss", f"{start:.3f}", "-to", f"{end:.3f}",
         "-i", str(src), "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "24",
         "-pix_fmt", "yuv420p", str(dst)],
        check=True,
        timeout=max(30, int(end - start) + 60),
    )


def _run_tracknet(video: Path, source_start: float) -> tuple[list[dict], float, str]:
    """Run qaz812345/TrackNetV3 predict.py when the repo and weights are baked in."""
    global _tracknet_error
    if not _tracknet_ready():
        return [], 0.0, "not_configured"
    if TRACKNET_INPAINTNET_FILE and not Path(TRACKNET_INPAINTNET_FILE).exists():
        _tracknet_error = f"InpaintNet checkpoint missing: {TRACKNET_INPAINTNET_FILE}"
        return [], 0.0, "missing_inpaintnet"

    save_dir = video.parent / f"tracknet_{video.stem}"
    save_dir.mkdir(parents=True, exist_ok=True)
    cmd = [
        "python", "predict.py",
        "--video_file", str(video),
        "--tracknet_file", TRACKNET_TRACKNET_FILE,
        "--save_dir", str(save_dir),
        "--batch_size", str(TRACKNET_BATCH_SIZE),
        "--eval_mode", TRACKNET_EVAL_MODE,
        "--large_video",
    ]
    if TRACKNET_INPAINTNET_FILE:
        cmd.extend(["--inpaintnet_file", TRACKNET_INPAINTNET_FILE])
    try:
        subprocess.run(
            cmd,
            cwd=TRACKNET_REPO,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=TRACKNET_TIMEOUT_SEC,
        )
    except subprocess.CalledProcessError as exc:  # surface predict.py's own error
        tail = " | ".join((exc.output or "").strip().splitlines()[-4:])[:400]
        _tracknet_error = f"tracknet exit {exc.returncode}: {tail or '(no output)'}"
        return [], 0.0, "failed"
    except Exception as exc:  # noqa: BLE001 - worker can fall back to motion shuttle.
        _tracknet_error = f"{type(exc).__name__}: {exc}"
        return [], 0.0, "failed"

    meta = _video_meta(video)
    csv_path = save_dir / f"{video.stem}_ball.csv"
    if not csv_path.exists():
        _tracknet_error = f"missing TrackNet CSV: {csv_path.name}"
        return [], 0.0, "missing_csv"

    points: list[dict] = []
    with csv_path.open(newline="") as f:
        for row in csv.DictReader(f):
            try:
                visible = int(float(row.get("Visibility", "0"))) > 0
                frame = int(float(row.get("Frame", "0")))
                x = float(row.get("X", "0"))
                y = float(row.get("Y", "0"))
            except ValueError:
                continue
            if not visible or x <= 0 or y <= 0:
                continue
            points.append({
                "t": round(source_start + frame / max(meta["fps"], 1.0), 3),
                "x": _clamp01(x / max(meta["width"], 1)),
                "y": _clamp01(y / max(meta["height"], 1)),
                # TrackNetV3 CSV exposes visibility, not probability; confidence
                # is conservative and final quality is coverage-gated.
                "confidence": 0.82,
                "source": "tracknetv3",
            })
    quality = _quality([p["confidence"] for p in points], max(2, int(meta["duration"] * meta["fps"] * 0.35)))
    return points, quality, "ok" if points else "empty"


def _sample_times(start: float, end: float) -> list[float]:
    dur = max(0.01, end - start)
    n = min(MAX_FRAMES_PER_RALLY, max(2, int(math.ceil(dur * SAMPLE_FPS))))
    return [start + i * dur / max(n - 1, 1) for i in range(n)]


def _quality(values: list[float], expected: int) -> float:
    vals = [v for v in values if v > 0]
    if not vals:
        return 0.0
    coverage = min(1.0, len(vals) / max(expected, 1))
    return _clamp01(float(np.mean(vals)) * coverage)


def _process_rally(cap, meta: dict, rally: dict, video_path: Path, workdir: Path,
                   tasks: set | None = None) -> dict:
    tasks = tasks or {"players", "pose", "racquet", "shuttle"}
    want_shuttle = "shuttle" in tasks
    want_pose = bool({"players", "pose"} & tasks)
    want_racquet = "racquet" in tasks
    fps = meta["fps"]
    start = max(0.0, _num(rally.get("start")))
    end = min(meta["duration"], _num(rally.get("end"), start))
    times = _sample_times(start, end)
    tracknet_points: list[dict] = []
    tracknet_quality = 0.0
    tracknet_status = "skipped" if not want_shuttle else "not_configured"
    if want_shuttle and _tracknet_ready():
        clip = workdir / f"rally_{int(_num(rally.get('rally_index'), 0)):02d}_tracknet.mp4"
        try:
            _cut_clip(video_path, clip, start, end)
            tracknet_points, tracknet_quality, tracknet_status = _run_tracknet(clip, start)
        except Exception as exc:  # noqa: BLE001
            global _tracknet_error
            _tracknet_error = f"{type(exc).__name__}: {exc}"
            tracknet_status = "failed"
    prev_gray = None
    frames = []
    first_pose_frame = True   # fresh ByteTrack id space per rally
    player_confs, pose_confs, racquet_confs, candidate_confs, shuttle_confs = [], [], [], [], []
    for t in times:
        ok, frame = _seek_frame(cap, t, fps)
        if not ok or frame is None:
            continue
        players, poses, pose_q = (_detect_pose(frame, reset_tracker=first_pose_frame)
                                  if want_pose else ([], [], 0.0))
        if want_pose:
            first_pose_frame = False
        racquets, racquet_q = _detect_racquet(frame) if want_racquet else ([], 0.0)
        racquet_candidates, candidate_q = ([], 0.0)
        if want_racquet and not racquets:
            racquet_candidates, candidate_q = _detect_racquet_candidates(frame, poses)
        # Motion-diff shuttle only as a fallback when TrackNet wasn't run.
        if want_shuttle and not tracknet_points:
            shuttle, prev_gray = _detect_shuttle(frame, prev_gray, players)
        else:
            shuttle = None
        if not players:
            # Low-confidence fallback so the app can still reason about coverage.
            players = [{"box": [0.18, 0.12, 0.42, 0.95], "confidence": 0.12},
                       {"box": [0.58, 0.12, 0.82, 0.95], "confidence": 0.12}]
        row = {"t": round(t, 3), "players": players}
        if poses:
            row["poses"] = poses
        if racquets:
            row["racquets"] = racquets
        elif racquet_candidates:
            row["racquet_candidates"] = racquet_candidates
        if shuttle:
            row["shuttle"] = shuttle
            shuttle_confs.append(shuttle["confidence"])
        frames.append(row)
        player_confs.extend([p["confidence"] for p in players[:2]])
        pose_confs.append(pose_q)
        racquet_confs.append(racquet_q)
        candidate_confs.append(candidate_q)
    expected = len(times)
    shuttle_quality = max(
        tracknet_quality,
        _quality(shuttle_confs, max(2, expected // 3)),
    )
    return {
        "rally_index": int(_num(rally.get("rally_index"), 0)),
        "start": start,
        "end": end,
        "dur": round(end - start, 3),
        "player_quality": _quality(player_confs, expected * 2),
        "pose_quality": _quality(pose_confs, expected),
        "racquet_quality": _quality(racquet_confs, expected),
        "racquet_candidate_quality": _quality(candidate_confs, expected),
        "shuttle_quality": shuttle_quality,
        "shuttle": tracknet_points,
        "tracknet": {
            "enabled": _tracknet_ready(),
            "status": tracknet_status,
            "points": len(tracknet_points),
            "quality": tracknet_quality,
        },
        "racquet_candidate_samples": len([v for v in candidate_confs if v > 0]),
        "frames": frames,
    }


def process(job_input: dict) -> dict:
    if job_input.get("contract") != CONTRACT:
        raise ValueError(f"unsupported contract: {job_input.get('contract')!r}")
    proxy_url = job_input.get("proxy_url")
    if not proxy_url:
        raise ValueError("proxy_url is required")
    rallies = job_input.get("rallies") or []
    if not isinstance(rallies, list) or not rallies:
        raise ValueError("rallies must be a non-empty list")
    requested_pose_model = str(job_input.get("pose_model") or YOLO_POSE_MODEL or "").strip()
    _load_models(requested_pose_model)
    started = time.time()
    with tempfile.TemporaryDirectory(prefix="baddy-vision-") as td:
        video = Path(td) / "proxy.mp4"
        _download(proxy_url, video)
        meta = _video_meta(video)
        cap = cv2.VideoCapture(str(video))
        tasks = set(job_input.get("tasks") or ["players", "pose", "racquet", "shuttle"])
        try:
            results = [_process_rally(cap, meta, r, video, Path(td), tasks) for r in rallies]
        finally:
            cap.release()
    return {
        "contract": CONTRACT,
        "engine": "runpod-yolo-tracknetv3-gemini-flash-ready-v1",
        "worker_version": WORKER_VERSION,
        "message": _model_error or _tracknet_error or "ok",
        "video": {"width": meta["width"], "height": meta["height"],
                  "fps": round(meta["fps"], 3), "duration": round(meta["duration"], 3)},
        "sample_fps": SAMPLE_FPS,
        "model_status": {
            "pose_model": _pose_model_path if _pose_model is not None else None,
            "pose_requested_model": requested_pose_model,
            "pose_fallback_model": YOLO_POSE_FALLBACK,
            "pose_backend": "runpod",
            "pose_device": DEVICE,
            "pose_load_status": "loaded" if _pose_model is not None else "failed",
            "racquet_model": RACQUET_MODEL if _racquet_model is not None else None,
            "tracknet_repo": TRACKNET_REPO if _tracknet_ready() else None,
            "tracknet_model": TRACKNET_TRACKNET_FILE if _tracknet_ready() else None,
            "fallback": bool(_model_error),
            "error": _model_error,
            "tracknet_error": _tracknet_error,
            "track_error": _track_error,
            "player_tracker": "" if _track_error else "bytetrack",
        },
        "elapsed_sec": round(time.time() - started, 3),
        "rallies": results,
    }


def handler(job: dict) -> dict:
    return process(job.get("input") or {})


if __name__ == "__main__":
    runpod.serverless.start({"handler": handler})
