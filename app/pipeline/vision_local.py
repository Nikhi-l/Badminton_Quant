"""On-device vision engine: TrackNetV3 shuttle tracking + YOLO pose.

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
YOLO_POSE_MODEL = os.environ.get("VISION_POSE_MODEL", config.POSE_MODEL_LOCAL)
YOLO_POSE_FALLBACK = os.environ.get("VISION_POSE_FALLBACK", config.POSE_MODEL_FALLBACK)
YOLO_CONF = float(os.environ.get("VISION_YOLO_CONF", "0.25"))
YOLO_IMGSZ = int(os.environ.get("VISION_YOLO_IMGSZ", "640"))
TRACKNET_BATCH = int(os.environ.get("VISION_TRACKNET_BATCH", "8"))
TRACKNET_TIMEOUT = int(os.environ.get("VISION_TRACKNET_TIMEOUT", "1800"))
# 'nonoverlap' samples each frame once (≈8x fewer windows than the default
# 'weight' temporal ensemble) — far faster on CPU/MPS, plenty for camera framing.
TRACKNET_EVAL_MODE = os.environ.get("VISION_TRACKNET_EVAL_MODE", "nonoverlap")
# InpaintNet fills gaps but doubles the passes; off by default for speed.
TRACKNET_INPAINT = os.environ.get("VISION_TRACKNET_INPAINT", "0").lower() \
    not in {"0", "false", "no", "off"}
WORKER_VERSION = "local-tracknetv3-yolo-pose-20260626"

_pose_model = None
_pose_model_path = ""
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


def available(need_shuttle: bool = False) -> tuple[bool, str]:
    """Whether on-device vision can run here. Pose needs only torch+ultralytics;
    CPU shuttle (TrackNetV3) additionally needs the vendored repo + weights."""
    try:
        import cv2  # noqa: F401
        import torch  # noqa: F401
        import ultralytics  # noqa: F401
    except Exception as e:  # noqa: BLE001
        return False, f"vision deps not installed ({type(e).__name__})"
    if need_shuttle:
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
    global _pose_model, _pose_model_path, _pose_error
    if _pose_model is not None or _pose_error:
        return
    try:
        from ultralytics import YOLO
    except Exception as e:  # noqa: BLE001
        _pose_error = f"{type(e).__name__}: {e}"
        return

    errors = []
    candidates = []
    for candidate in (YOLO_POSE_MODEL, YOLO_POSE_FALLBACK):
        candidate = str(candidate or "").strip()
        if candidate and candidate not in candidates:
            candidates.append(candidate)
    for candidate in candidates:
        try:
            _pose_model = YOLO(candidate)
            _pose_model_path = candidate
            return
        except Exception as e:  # noqa: BLE001
            errors.append(f"{Path(candidate).name}: {type(e).__name__}: {e}")
    _pose_error = "; ".join(errors) or "no pose model configured"


def _norm_box(x1, y1, x2, y2, w, h, conf) -> dict:
    return {
        "box": [_clamp01(x1 / max(w, 1)), _clamp01(y1 / max(h, 1)),
                _clamp01(x2 / max(w, 1)), _clamp01(y2 / max(h, 1))],
        "confidence": _clamp01(conf, 1.0),
    }


def _box_area(b: dict) -> float:
    x1, y1, x2, y2 = b["box"]
    return max(0.0, x2 - x1) * max(0.0, y2 - y1)


MAX_PLAYERS = int(os.environ.get("VISION_MAX_PLAYERS", "4"))


def _court_polygon(corners) -> np.ndarray | None:
    """Expanded court quad for gating person detections (TASK-031); mirrors the
    Runpod worker's gate so local and GPU results stay comparable."""
    if not isinstance(corners, (list, tuple)) or len(corners) != 4:
        return None
    try:
        quad = np.array([[float(p[0]), float(p[1])] for p in corners], np.float64)
    except (TypeError, ValueError, IndexError):
        return None
    if not np.isfinite(quad).all():
        return None
    center = quad.mean(axis=0)
    return center + (quad - center) * 1.22


def _inside_polygon(x: float, y: float, poly: np.ndarray) -> bool:
    inside = False
    n = len(poly)
    for i in range(n):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % n]
        if (y1 > y) != (y2 > y):
            t = (y - y1) / (y2 - y1)
            if x < x1 + t * (x2 - x1):
                inside = not inside
    return inside


def _detect_pose(frame, device: str, court_poly: np.ndarray | None = None):
    """YOLO pose: top-4 player boxes (doubles) + COCO-17 keypoints, normalized."""
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
                   key=lambda i: (players[i]["confidence"], _box_area(players[i])), reverse=True)
    if court_poly is not None:
        # Foot point must stand on/near the court; fail-safe to ungated when the
        # gate would blank the frame (mis-drawn quad must not hide real players).
        gated = [i for i in order
                 if _inside_polygon((players[i]["box"][0] + players[i]["box"][2]) / 2,
                                    players[i]["box"][3], court_poly)]
        order = gated or order
    order = order[:MAX_PLAYERS]
    players = [players[i] for i in order]
    poses = [poses[i] for i in order if i < len(poses)]
    pose_q = float(np.mean([p["confidence"] for p in poses])) if poses else 0.0
    return players, poses, _clamp01(pose_q)


def _run_tracknet(clip: Path, source_start: float, log) -> tuple[list[dict], float, str]:
    """Invoke the vendored, device-patched TrackNetV3 predict.py on one clip."""
    # predict.py runs with cwd=REPO, so a relative clip path resolves against the
    # repo dir and OpenCV silently reads an empty stream (median -> scalar crash).
    # Always hand the subprocess absolute paths.
    clip = Path(clip).resolve()
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
           "--eval_mode", TRACKNET_EVAL_MODE,
           "--large_video"]
    if TRACKNET_INPAINT and INET_WEIGHTS.exists():
        cmd += ["--inpaintnet_file", str(INET_WEIGHTS)]
    try:
        subprocess.run(cmd, cwd=str(REPO), check=True, timeout=TRACKNET_TIMEOUT,
                       stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    except subprocess.CalledProcessError as e:
        err = (e.stderr or b"").decode("utf-8", "ignore").strip()
        (save_dir / "stderr.txt").write_text(err)  # full traceback for diagnosis
        lines = err.splitlines()
        log(f"tracknet failed: {(lines[-1] if lines else '?')[:160]} "
            f"(full: {save_dir / 'stderr.txt'})")
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
                   proxy_path: Path, workdir: Path, device: str, tasks: set[str], log,
                   court_poly: np.ndarray | None = None) -> dict:
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
        players, poses, pose_q = _detect_pose(frame, device, court_poly=court_poly)
        # No detections → an honest empty frame; the old hardcoded placeholder
        # boxes steered the camera to empty court and inflated player_quality
        # past the camera's trust gate (TASK-031).
        row = {"t": round(t, 3), "players": players}
        if poses:
            row["poses"] = poses
        frames.append(row)
        player_confs.extend([p["confidence"] for p in players[:MAX_PLAYERS]])
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
                tasks: list[str] | None = None, log=print,
                court_corners: list | None = None) -> dict:
    """Run on-device vision over the selected rallies; returns raw vision.v1.

    tasks subset of {shuttle, pose, players}; only requested workers run.
    court_corners (normalized quad) gates person detections to the court.
    """
    import cv2

    task_set = set(tasks or ["shuttle", "pose"])
    court_poly = _court_polygon(court_corners)
    proxy_path = Path(proxy_path).resolve()  # clips inherit this dir; keep it absolute
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
                                          device, task_set, log, court_poly=court_poly))
            done = results[-1]
            log(f"rally {done['rally_index']}: shuttle {done['tracknet']['points']}pts "
                f"({done['tracknet']['status']}), players {done['player_quality']:.0%}")
    finally:
        cap.release()

    return {
        "contract": "baddy.vision.v1",
        "engine": "local-yolo-pose-tracknetv3",
        "worker_version": WORKER_VERSION,
        "message": _pose_error or "ok",
        "video": {"width": width, "height": height, "fps": round(fps, 3),
                  "duration": round(duration, 3)},
        "sample_fps": SAMPLE_FPS,
        "model_status": {
            "pose_model": _pose_model_path if _pose_model is not None else None,
            "pose_requested_model": YOLO_POSE_MODEL,
            "pose_fallback_model": YOLO_POSE_FALLBACK,
            "pose_backend": "local",
            "pose_device": device,
            "pose_load_status": "loaded" if _pose_model is not None else "failed",
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
