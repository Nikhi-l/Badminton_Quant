"""On-device vision engine: TrackNetV3 shuttle tracking + YOLO11 pose.

Runs the same models as the Runpod worker, but in-process against the local
proxy file — no GPU service, no upload, no polling. Picks the best available
device automatically (CUDA > Apple MPS > CPU), so it works on the dev Mac
(MPS-accelerated) and on the CPU-only VM (slower, offline pass).

Output is the raw `baddy.vision.v1` shape that ``gpu._canonicalize`` consumes,
so the rest of the pipeline (camera, render overlays, coach) is unchanged.
"""
from __future__ import annotations

import csv
import math
import os
import subprocess
import sys
import time
from pathlib import Path

import numpy as np

from .. import config

REPO = config.ROOT / "vendor" / "TrackNetV3"
TNET_WEIGHTS = config.ROOT / "runpod_worker" / "models" / "tracknet" / "TrackNet_best.pt"
INET_WEIGHTS = config.ROOT / "runpod_worker" / "models" / "tracknet" / "InpaintNet_best.pt"

SAMPLE_FPS = float(os.environ.get("VISION_SAMPLE_FPS", "6"))
MAX_FRAMES_PER_RALLY = int(os.environ.get("VISION_MAX_FRAMES_PER_RALLY", "180"))
YOLO_POSE_MODEL = os.environ.get("VISION_POSE_MODEL",
                                 str(config.DATA / "models" / "yolo11n-pose.pt"))
YOLO_CONF = float(os.environ.get("VISION_YOLO_CONF", "0.25"))
YOLO_IMGSZ = int(os.environ.get("VISION_YOLO_IMGSZ", "640"))
TRACKNET_BATCH = int(os.environ.get("VISION_TRACKNET_BATCH", "8"))
TRACKNET_TIMEOUT = int(os.environ.get("VISION_TRACKNET_TIMEOUT", "1800"))
WORKER_VERSION = "local-tracknetv3-yolo11-20260618"

_pose_model = None
_pose_error = ""
_device_cache: str | None = None


def torch_device() -> str:
    """cuda | mps | cpu, honoring VISION_DEVICE override."""
    global _device_cache
    if _device_cache is not None:
        return _device_cache
    forced = os.environ.get("VISION_DEVICE", "").strip().lower()
    if forced:
        _device_cache = forced
        return forced
    try:
        import torch

        if torch.cuda.is_available():
            _device_cache = "cuda"
        elif getattr(torch.backends, "mps", None) is not None and torch.backends.mps.is_available():
            _device_cache = "mps"
        else:
            _device_cache = "cpu"
    except Exception:  # noqa: BLE001
        _device_cache = "cpu"
    return _device_cache


def _yolo_device(dev: str) -> str:
    return "0" if dev == "cuda" else dev


def available() -> tuple[bool, str]:
    """Whether on-device vision can run here (deps + repo + weights present)."""
    try:
        import cv2  # noqa: F401
        import torch  # noqa: F401
        import ultralytics  # noqa: F401
    except Exception as e:  # noqa: BLE001
        return False, f"local vision deps not installed ({type(e).__name__})"
    if not (REPO / "predict.py").exists():
        return False, "TrackNetV3 repo not vendored at vendor/TrackNetV3"
    if not TNET_WEIGHTS.exists():
        return False, "TrackNet weights missing under runpod_worker/models/tracknet"
    return True, "ok"


def _clamp01(v, default: float = 0.0) -> float:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return default
    return min(max(f, 0.0), 1.0)


def _quality(values: list[float], expected: int) -> float:
    vals = [v for v in values if v > 0]
    if not vals:
        return 0.0
    coverage = min(1.0, len(vals) / max(expected, 1))
    return _clamp01(float(np.mean(vals)) * coverage)


def _load_pose():
    global _pose_model, _pose_error
    if _pose_model is not None or _pose_error:
        return
    try:
        from ultralytics import YOLO

        _pose_model = YOLO(YOLO_POSE_MODEL)
    except Exception as e:  # noqa: BLE001
        _pose_error = f"{type(e).__name__}: {e}"


def _norm_box(x1, y1, x2, y2, w, h, conf) -> dict:
    return {
        "box": [_clamp01(x1 / max(w, 1)), _clamp01(y1 / max(h, 1)),
                _clamp01(x2 / max(w, 1)), _clamp01(y2 / max(h, 1))],
        "confidence": _clamp01(conf, 1.0),
    }


def _box_area(b: dict) -> float:
    x1, y1, x2, y2 = b["box"]
    return max(0.0, x2 - x1) * max(0.0, y2 - y1)


def _detect_pose(frame, device: str):
    """YOLO11 pose: top-2 player boxes + COCO-17 keypoints, normalized."""
    if _pose_model is None:
        return [], [], 0.0
    h, w = frame.shape[:2]
    res = _pose_model.predict(frame, imgsz=YOLO_IMGSZ, conf=YOLO_CONF,
                              device=_yolo_device(device), verbose=False)[0]
    boxes = getattr(res, "boxes", None)
    kpts = getattr(res, "keypoints", None)
    if boxes is None or boxes.xyxy is None:
        return [], [], 0.0
    xyxy = boxes.xyxy.cpu().numpy()
    confs = boxes.conf.cpu().numpy() if boxes.conf is not None else np.ones(len(xyxy))
    kxy = kpts.xy.cpu().numpy() if kpts is not None and kpts.xy is not None else []
    kcf = kpts.conf.cpu().numpy() if kpts is not None and kpts.conf is not None else []
    players, poses = [], []
    for i, box in enumerate(xyxy):
        players.append(_norm_box(box[0], box[1], box[2], box[3], w, h, confs[i]))
        if i < len(kxy):
            pts = []
            for j, pt in enumerate(kxy[i]):
                sc = float(kcf[i][j]) if i < len(kcf) and j < len(kcf[i]) else 1.0
                pts.append({"x": _clamp01(pt[0] / max(w, 1)), "y": _clamp01(pt[1] / max(h, 1)),
                            "confidence": _clamp01(sc, 1.0)})
            poses.append({"keypoints": pts,
                          "confidence": float(np.mean([p["confidence"] for p in pts])) if pts else 0.0})
    order = sorted(range(len(players)),
                   key=lambda i: (players[i]["confidence"], _box_area(players[i])), reverse=True)[:2]
    players = [players[i] for i in order]
    poses = [poses[i] for i in order if i < len(poses)]
    pose_q = float(np.mean([p["confidence"] for p in poses])) if poses else 0.0
    return players, poses, _clamp01(pose_q)


def _run_tracknet(clip: Path, source_start: float, log) -> tuple[list[dict], float, str]:
    """Invoke the vendored, device-patched TrackNetV3 predict.py on one clip."""
    save_dir = clip.parent / f"tnt_{clip.stem}"
    save_dir.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    env["TRACKNET_DEVICE"] = torch_device()
    env.setdefault("PYTORCH_ENABLE_MPS_FALLBACK", "1")  # unsupported MPS ops -> CPU
    cmd = [sys.executable, "predict.py",
           "--video_file", str(clip),
           "--tracknet_file", str(TNET_WEIGHTS),
           "--save_dir", str(save_dir),
           "--batch_size", str(TRACKNET_BATCH),
           "--large_video"]
    if INET_WEIGHTS.exists():
        cmd += ["--inpaintnet_file", str(INET_WEIGHTS)]
    try:
        subprocess.run(cmd, cwd=str(REPO), check=True, timeout=TRACKNET_TIMEOUT,
                       stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    except subprocess.CalledProcessError as e:
        tail = (e.stderr or b"").decode("utf-8", "ignore").strip().splitlines()[-1:] or ["?"]
        log(f"tracknet failed: {tail[0][:160]}")
        return [], 0.0, "failed"
    except subprocess.TimeoutExpired:
        return [], 0.0, "timeout"

    csv_path = save_dir / f"{clip.stem}_ball.csv"
    if not csv_path.exists():
        return [], 0.0, "missing_csv"

    import cv2
    cap = cv2.VideoCapture(str(clip))
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    cw = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 1)
    ch = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 1)
    cap.release()

    pts: list[dict] = []
    total_rows = 0
    with csv_path.open(newline="") as f:
        for row in csv.DictReader(f):
            total_rows += 1
            try:
                if int(float(row.get("Visibility", "0"))) <= 0:
                    continue
                frame = int(float(row.get("Frame", "0")))
                x, y = float(row.get("X", "0")), float(row.get("Y", "0"))
            except ValueError:
                continue
            if x <= 0 or y <= 0:
                continue
            pts.append({"t": round(source_start + frame / max(fps, 1.0), 3),
                        "x": _clamp01(x / cw), "y": _clamp01(y / ch),
                        "confidence": 0.82, "source": "tracknetv3"})
    # Quality = confident-mean gated by coverage (≈35% of clip frames carry a
    # visible shuttle in normal rally play; full coverage is unrealistic).
    expected = max(2, int(round(total_rows * 0.35)))
    quality = _quality([p["confidence"] for p in pts], expected)
    return pts, quality, "ok" if pts else "empty"


def _cut_clip(src: Path, dst: Path, start: float, end: float):
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-ss", f"{start:.3f}", "-to", f"{end:.3f}",
         "-i", str(src), "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "24",
         "-pix_fmt", "yuv420p", str(dst)],
        check=True, timeout=max(60, int(end - start) + 60))


def _sample_times(start: float, end: float) -> list[float]:
    dur = max(0.01, end - start)
    n = min(MAX_FRAMES_PER_RALLY, max(2, int(math.ceil(dur * SAMPLE_FPS))))
    return [start + i * dur / max(n - 1, 1) for i in range(n)]


def _process_rally(cap, fps: float, duration: float, rally: dict,
                   proxy_path: Path, workdir: Path, device: str, tasks: set[str], log) -> dict:
    import cv2

    idx = int(float(rally.get("rally_index", 0) or 0))
    start = max(0.0, float(rally.get("start", 0) or 0))
    end = min(duration, float(rally.get("end", start) or start))

    # Shuttle: TrackNetV3 on the exact rally window (only if requested).
    tnt_pts, tnt_q, tnt_status = [], 0.0, "skipped"
    if "shuttle" in tasks:
        tnt_status = "not_run"
        clip = workdir / f"rally_{idx:02d}_tnt.mp4"
        try:
            _cut_clip(proxy_path, clip, start, end)
            tnt_pts, tnt_q, tnt_status = _run_tracknet(clip, start, log)
        except Exception as e:  # noqa: BLE001
            log(f"rally {idx}: tracknet error {type(e).__name__}: {e}")
            tnt_status = "failed"
        finally:
            clip.unlink(missing_ok=True)

    # Players + pose: YOLO11 at SAMPLE_FPS (only if requested).
    frames, player_confs, pose_confs = [], [], []
    want_pose = "pose" in tasks or "players" in tasks
    for t in (_sample_times(start, end) if want_pose else []):
        cap.set(cv2.CAP_PROP_POS_FRAMES, max(0, int(round(t * fps))))
        ok, frame = cap.read()
        if not ok or frame is None:
            continue
        players, poses, pose_q = _detect_pose(frame, device)
        if not players:
            players = [{"box": [0.18, 0.12, 0.42, 0.95], "confidence": 0.12},
                       {"box": [0.58, 0.12, 0.82, 0.95], "confidence": 0.12}]
        row = {"t": round(t, 3), "players": players}
        if poses:
            row["poses"] = poses
        frames.append(row)
        player_confs.extend([p["confidence"] for p in players[:2]])
        pose_confs.append(pose_q)

    expected = max(2, len(frames))
    return {
        "rally_index": idx,
        "start": start,
        "end": end,
        "dur": round(end - start, 3),
        "player_quality": _quality(player_confs, expected * 2),
        "pose_quality": _quality(pose_confs, expected),
        "racquet_quality": 0.0,
        "racquet_candidate_quality": 0.0,
        "shuttle_quality": tnt_q,
        "shuttle": tnt_pts,
        "tracknet": {"enabled": True, "status": tnt_status,
                     "points": len(tnt_pts), "quality": tnt_q},
        "frames": frames,
    }


def analyze_raw(proxy_path: str | Path, sport: str, rallies: list[dict],
                tasks: list[str] | None = None, log=print) -> dict:
    """Run on-device vision over the selected rallies; returns raw vision.v1.

    tasks subset of {shuttle, pose, players}; only requested workers run.
    """
    import cv2

    task_set = set(tasks or ["shuttle", "pose"])
    proxy_path = Path(proxy_path)
    device = torch_device()
    log(f"on-device vision ({'+'.join(sorted(task_set))}) on {device}")
    if "pose" in task_set or "players" in task_set:
        _load_pose()
        if _pose_error:
            log(f"pose model unavailable ({_pose_error}); players/pose degraded")

    cap = cv2.VideoCapture(str(proxy_path))
    if not cap.isOpened():
        raise RuntimeError(f"cannot open proxy: {proxy_path}")
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    nframes = cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
    duration = nframes / fps if fps else 0.0

    indexed = [{"rally_index": i, **r} for i, r in enumerate(rallies, 1)]
    started = time.time()
    results = []
    workdir = proxy_path.parent
    try:
        for r in indexed:
            results.append(_process_rally(cap, fps, duration, r, proxy_path, workdir,
                                          device, task_set, log))
            done = results[-1]
            log(f"rally {done['rally_index']}: shuttle {done['tracknet']['points']}pts "
                f"({done['tracknet']['status']}), players {done['player_quality']:.0%}")
    finally:
        cap.release()

    return {
        "contract": "baddy.vision.v1",
        "engine": "local-yolo11-tracknetv3",
        "worker_version": WORKER_VERSION,
        "message": _pose_error or "ok",
        "video": {"width": width, "height": height, "fps": round(fps, 3),
                  "duration": round(duration, 3)},
        "sample_fps": SAMPLE_FPS,
        "model_status": {
            "pose_model": YOLO_POSE_MODEL if _pose_model is not None else None,
            "racquet_model": None,
            "tracknet_repo": str(REPO),
            "tracknet_model": str(TNET_WEIGHTS),
            "fallback": bool(_pose_error),
            "error": _pose_error,
            "tracknet_error": "",
        },
        "elapsed_sec": round(time.time() - started, 3),
        "rallies": results,
    }
