"""Baddy — AI sports highlight generator. FastAPI app serving API + frontend."""
import json
import math
import shutil
import time
import uuid
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import artifacts, config, db, worker
from .pipeline import gpu as gpu_pipeline
from .pipeline.run import STAGES

ALLOWED_EXT = {".mp4", ".mov", ".m4v", ".avi", ".mkv", ".webm"}
MEDIA_WHITELIST = {"reel.mp4", "thumb.jpg", "proxy.mp4"}
CHUNK_SIZE = 8 * 1024 * 1024
MAX_UPLOAD = 3 * 1024 ** 3

app = FastAPI(title="Baddy", docs_url=None, redoc_url=None)


def _sweep_stale_uploads(max_age_h: float = 24.0):
    """Abandoned chunked uploads (init without finish) must not fill the disk."""
    cutoff = time.time() - max_age_h * 3600
    for d in config.UPLOADS.iterdir():
        if not d.is_dir():
            continue
        markers = list(d.glob("meta_*.json")) + list(d.glob("part_*.bin"))
        if markers and max(m.stat().st_mtime for m in markers) < cutoff:
            shutil.rmtree(d, ignore_errors=True)


@app.on_event("startup")
def _startup():
    db.init()
    worker.start()
    _sweep_stale_uploads()


@app.get("/api/health")
def health():
    return {"ok": True}


@app.get("/api/vision/status")
def vision_status():
    return gpu_pipeline.readiness()


# --- Chunked upload: survives flaky connections (each chunk retries client-side).
# --- Multi-clip games: several files share one job (file index 0..n-1).

def _meta_path(job_id: str, fidx: int) -> Path:
    return config.UPLOADS / job_id / f"meta_{fidx:02d}.json"


def _part_path(job_id: str, fidx: int) -> Path:
    return config.UPLOADS / job_id / f"part_{fidx:02d}.bin"


def _load_meta(job_id: str, fidx: int) -> dict:
    p = _meta_path(job_id, fidx)
    if not job_id.isalnum() or not p.exists():
        raise HTTPException(404, "unknown upload")
    return json.loads(p.read_text())


_INIT_HITS: dict[str, list[float]] = {}


@app.post("/api/upload/init")
async def upload_init(payload: dict, request: Request):
    filename = str(payload.get("filename") or "video.mp4")
    size = int(payload.get("size") or 0)
    ext = Path(filename).suffix.lower()
    if ext not in ALLOWED_EXT:
        raise HTTPException(400, f"unsupported file type {ext}")
    if not 0 < size <= MAX_UPLOAD:
        raise HTTPException(400, "file size out of range (max 3 GB)")

    job = payload.get("job")
    if job:   # another clip joining an existing multi-clip upload
        if not str(job).isalnum() or not _meta_path(str(job), 0).exists():
            raise HTTPException(404, "unknown upload group")
        job_id = str(job)
        fidx = int(payload.get("index") or 0)
        if not 1 <= fidx <= 31:
            raise HTTPException(400, "bad file index")
    else:
        ip = (request.headers.get("x-forwarded-for", "").split(",")[0].strip()
              or (request.client.host if request.client else "?"))
        now = time.time()
        hits = [t for t in _INIT_HITS.get(ip, []) if now - t < 600]
        if len(hits) >= 8:
            raise HTTPException(429, "too many uploads — try again in a few minutes")
        _INIT_HITS[ip] = hits + [now]
        _sweep_stale_uploads()
        job_id = uuid.uuid4().hex[:12]
        fidx = 0
        (config.UPLOADS / job_id).mkdir(parents=True, exist_ok=True)

    _part_path(job_id, fidx).touch()
    _meta_path(job_id, fidx).write_text(json.dumps(
        {"filename": Path(filename).name, "size": size, "ext": ext, "chunks_done": 0}))
    return {"id": job_id, "file": fidx, "chunk_size": CHUNK_SIZE}


@app.put("/api/upload/{job_id}/chunk/{index}")
async def upload_chunk(job_id: str, index: int, request: Request, file: int = 0):
    meta = _load_meta(job_id, file)
    if index == meta["chunks_done"] - 1:
        return {"received": meta["chunks_done"]}   # duplicate after a lost response: ok
    if index != meta["chunks_done"]:
        raise HTTPException(409, f"expected chunk {meta['chunks_done']}, got {index}")
    body = await request.body()
    if not body:
        raise HTTPException(400, "empty chunk")
    part = _part_path(job_id, file)
    if part.stat().st_size + len(body) > min(meta["size"], MAX_UPLOAD):
        raise HTTPException(413, "chunks exceed the declared file size")
    with open(part, "ab") as f:
        f.write(body)
    meta["chunks_done"] += 1
    _meta_path(job_id, file).write_text(json.dumps(meta))
    return {"received": meta["chunks_done"]}


@app.post("/api/upload/{job_id}/finish")
async def upload_finish(job_id: str, request: Request):
    try:
        payload = await request.json()
    except Exception:  # noqa: BLE001 — empty body means single file
        payload = {}
    n_files = max(1, min(int(payload.get("files") or 1), 32))
    names = []
    for fidx in range(n_files):
        meta = _load_meta(job_id, fidx)
        part = _part_path(job_id, fidx)
        got = part.stat().st_size
        if got != meta["size"]:
            raise HTTPException(400, f"file {fidx} size mismatch: got {got}, "
                                     f"expected {meta['size']}")
        names.append(meta["filename"])
    for fidx in range(n_files):   # all verified — now commit
        meta = _load_meta(job_id, fidx)
        _part_path(job_id, fidx).rename(config.UPLOADS / job_id / f"input_{fidx:02d}{meta['ext']}")
        _meta_path(job_id, fidx).unlink(missing_ok=True)
    label = names[0] if n_files == 1 else f"{names[0]} +{n_files - 1} more"
    options = config.normalize_options(payload.get("options"))
    db.create_job(job_id, label, options=options)
    worker.enqueue(job_id)
    return {"id": job_id, "files": n_files, "options": options}


@app.post("/api/upload")
async def upload(file: UploadFile):
    ext = Path(file.filename or "video.mp4").suffix.lower()
    if ext not in ALLOWED_EXT:
        raise HTTPException(400, f"unsupported file type {ext}")
    job_id = uuid.uuid4().hex[:12]
    job_dir = config.UPLOADS / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    dst = job_dir / f"input{ext}"
    with open(dst, "wb") as f:
        while chunk := await file.read(4 * 1024 * 1024):
            f.write(chunk)
    db.create_job(job_id, Path(file.filename or "video").name)
    worker.enqueue(job_id)
    return {"id": job_id}


def _compact_vision(v: dict | None) -> dict | None:
    if not isinstance(v, dict):
        return None
    out = {k: v.get(k) for k in (
        "status", "camera_mode", "shuttle_quality", "player_quality",
        "pose_quality", "racquet_quality", "pose_samples", "racquet_samples",
        "racquet_candidate_quality", "racquet_candidate_samples",
        "mask_enabled", "shuttle_engine",
    ) if k in v}
    shuttle = v.get("shuttle") or []
    players = v.get("players") or []
    out["shuttle_samples"] = len(shuttle) if isinstance(shuttle, list) else 0
    if isinstance(players, list):
        out["player_samples"] = sum(
            len(f.get("boxes") or []) for f in players if isinstance(f, dict)
        )
    else:
        out["player_samples"] = 0
    tracknet = v.get("tracknet") if isinstance(v.get("tracknet"), dict) else None
    if tracknet:
        out["tracknet"] = {k: tracknet.get(k) for k in (
            "enabled", "status", "points", "quality"
        ) if k in tracknet}
    track = _sample_shuttle_track(shuttle)
    if track:
        out["shuttle_track"] = track
    ptrack = _sample_player_track(players)
    if ptrack:
        out["players_track"] = ptrack
    return out


def _sample_shuttle_track(points: list | None, max_points: int = 180) -> list[dict]:
    """Public, bounded time-level shuttle track for editor overlays.

    Internal vision output can contain dense frame-by-frame points. The editor only
    needs enough normalized samples to place/preview shuttle graphics, so keep the
    response small and strip non-coordinate vendor details.
    """
    if not isinstance(points, list) or not points:
        return []
    step = max(1, math.ceil(len(points) / max_points))
    out = []
    for p in points[::step]:
        if not isinstance(p, dict):
            continue
        try:
            out.append({
                "t": round(float(p.get("t")), 3),
                "x": round(float(p.get("x")), 5),
                "y": round(float(p.get("y")), 5),
                "confidence": round(float(p.get("confidence", 0.0)), 3),
            })
        except (TypeError, ValueError):
            continue
    return out


def _sample_player_track(players: list | None, max_frames: int = 120) -> list[dict]:
    """Public, bounded per-frame player boxes with stable track ids for the editor.

    Vision stores dense per-frame player detections as boxes only. The editor needs
    normalized box centers + sizes and a consistent id per player so it can draw a
    player overlay and let the camera follow a chosen player (TASK-014/015). Ids are
    assigned greedily by nearest-centroid continuity across sampled frames.
    """
    if not isinstance(players, list) or not players:
        return []
    step = max(1, math.ceil(len(players) / max_frames))
    frames = [f for f in players[::step] if isinstance(f, dict)]
    out: list[dict] = []
    prev: list[tuple[int, float, float]] = []  # (id, cx, cy) from the last emitted frame
    next_id = 0
    gate = 0.22  # max normalized centroid move to keep the same id between samples
    for f in frames:
        cur: list[tuple[int, float, float]] = []
        used_prev: set[int] = set()
        norm_boxes: list[dict] = []
        for b in (f.get("boxes") or []):
            try:
                x1, y1, x2, y2 = float(b["x1"]), float(b["y1"]), float(b["x2"]), float(b["y2"])
            except (KeyError, TypeError, ValueError):
                continue
            cx, cy = (x1 + x2) / 2.0, (y1 + y2) / 2.0
            best_id, best_i, best_d = None, None, gate
            for i, (pid, px, py) in enumerate(prev):
                if i in used_prev:
                    continue
                d = ((cx - px) ** 2 + (cy - py) ** 2) ** 0.5
                if d < best_d:
                    best_id, best_i, best_d = pid, i, d
            if best_id is None:
                best_id = next_id
                next_id += 1
            else:
                used_prev.add(best_i)
            cur.append((best_id, cx, cy))
            norm_boxes.append({
                "id": best_id,
                "x": round(cx, 5), "y": round(cy, 5),
                "w": round(max(0.0, x2 - x1), 5), "h": round(max(0.0, y2 - y1), 5),
                "confidence": round(float(b.get("confidence", 0.0)), 3),
            })
        if norm_boxes:
            try:
                t = round(float(f.get("t")), 3)
            except (TypeError, ValueError):
                t = 0.0
            out.append({"t": t, "boxes": norm_boxes})
        prev = cur
    return out


def _public_rally(rr: dict) -> dict:
    out = {k: rr.get(k) for k in ("start", "end", "dur", "clip_dur", "src_start",
                                  "intensity", "note", "trimmed")}
    vision = _compact_vision(rr.get("vision"))
    if vision:
        out["vision"] = vision
    return out


def _public_result(job: dict) -> dict | None:
    import json
    if not job.get("result"):
        return None
    r = json.loads(job["result"])
    return {
        "video": f"/media/{job['id']}/reel.mp4",
        "thumb": f"/media/{job['id']}/thumb.jpg",
        "proxy": f"/media/{job['id']}/proxy.mp4",
        "duration": r.get("duration"),
        "sport": r.get("sport"),
        "n_rallies_found": r.get("n_rallies_found"),
        "n_rallies_used": r.get("n_rallies_used"),
        "rallies": [_public_rally(rr) for rr in r.get("rallies", [])],
        "all_rallies": r.get("all_rallies", []),
        "source_duration": (r.get("source") or {}).get("duration"),
        "n_clips": r.get("n_clips", 1),
        "clip_order": r.get("clip_order"),
        "pov_camera": r.get("pov_camera"),
        "vision": r.get("vision"),
        "options": r.get("options"),
        "coach": r.get("coach"),
        "remix": r.get("remix"),
        "rally_pool": [_public_rally(rr) for rr in r.get("rally_pool", [])]
        if isinstance(r.get("rally_pool"), list) else None,
        "gemini_usage": r.get("gemini_usage"),
        "elapsed_sec": r.get("elapsed_sec"),
    }


def _gen_seconds(job: dict) -> float | None:
    try:
        started = float(job.get("started_at"))
        finished = float(job.get("finished_at"))
    except (TypeError, ValueError):
        return None
    if finished < started:
        return None
    return round(finished - started, 1)


def _job_meta(job: dict) -> dict:
    pipeline = job.get("pipeline") or "unknown"
    return {
        "pipeline": pipeline,
        "submitted_at": job.get("created_at"),
        "started_at": job.get("started_at"),
        "finished_at": job.get("finished_at"),
        "gen_seconds": _gen_seconds(job),
        "expected_gen_seconds": config.expected_gen_seconds(pipeline),
    }


@app.get("/api/capabilities")
def capabilities():
    """What vision workers this deployment can run, for the upload UI."""
    gpu_ready = bool(config.RUNPOD_ENDPOINT_ID and config.RUNPOD_API_KEY)
    try:
        from .pipeline import vision_local
        pose_ok, pose_why = vision_local.available(need_shuttle=False)
        cpu_shuttle_ok, _ = vision_local.available(need_shuttle=True)
    except Exception as e:  # noqa: BLE001
        pose_ok, pose_why, cpu_shuttle_ok = False, str(e), False
    cpu_shuttle = cpu_shuttle_ok and config.VISION_ALLOW_CPU_TRACKNET
    return {
        "shuttle": {
            "tracknetv3": {
                "available": gpu_ready or cpu_shuttle,
                "backend": "runpod" if gpu_ready else ("cpu" if cpu_shuttle else "none"),
                "note": "GPU shuttle tracking" if gpu_ready
                        else "on-device (slow)" if cpu_shuttle else "needs GPU (not configured)",
            },
        },
        "pose": {
            "yolo11": {"available": pose_ok or gpu_ready,
                       "backend": "cpu" if pose_ok else ("runpod" if gpu_ready else "none"),
                       "note": "on-device YOLO11 pose" if pose_ok else pose_why},
        },
        "coach": {"available": bool(config.GEMINI_API_KEY)},
        "defaults": {"shuttle": config.VISION_DEFAULT_SHUTTLE,
                     "pose": config.VISION_DEFAULT_POSE},
    }


@app.get("/api/jobs/{job_id}")
def job_status(job_id: str):
    job = db.get_job(job_id)
    if not job:
        raise HTTPException(404, "job not found")
    try:
        cur = STAGES.index(job["stage"])
    except ValueError:
        cur = -1 if job["status"] == "queued" else 0
    stages = []
    for i, s in enumerate(STAGES):
        state = "pending"
        if job["status"] == "done":
            state = "done"
        elif job["status"] == "failed":
            if i < cur:
                state = "done"
            elif i == cur:
                state = "failed"
        elif i == cur and job["status"] == "processing":
            state = "active"
        elif i < cur:
            state = "done"
        stages.append({"key": s, "state": state})
    return {
        "id": job["id"], "status": job["status"], "stage": job["stage"],
        "message": job["message"], "error": job["error"], "stages": stages,
        "filename": job["filename"], "created_at": job["created_at"], **_job_meta(job),
        "result": _public_result(job),
    }


@app.post("/api/jobs/{job_id}/remix")
async def job_remix(job_id: str, request: Request):
    job = db.get_job(job_id)
    if not job or job["status"] != "done":
        raise HTTPException(409, "job is not in a remixable state")
    try:
        payload = await request.json()
    except Exception:  # noqa: BLE001
        raise HTTPException(400, "missing remix payload")
    result = json.loads(job["result"])
    n_pool = len(result.get("rally_pool") or result.get("rallies") or [])
    order = payload.get("rallies") or []
    if (not isinstance(order, list) or not order
            or not all(isinstance(i, int) and 1 <= i <= n_pool for i in order)
            or len(order) != len(set(order))):
        raise HTTPException(400, f"rallies must be unique 1-based indices within 1..{n_pool}")
    mirror = bool(payload.get("mirror"))
    camera = _validate_camera(payload.get("camera"))
    db.update_stage(job_id, "render", "rebuilding reel from your edit")
    worker.enqueue_remix(job_id, {"rallies": order, "mirror": mirror, "camera": camera})
    return {"ok": True, "id": job_id}


def _validate_camera(camera) -> dict | None:
    """Accept a TASK-014 camera plan from the editor, or None. Keeps only known
    fields and well-formed keyframes so a malformed plan can't reach the renderer."""
    if not isinstance(camera, dict) or not camera.get("enabled"):
        return None
    out_kfs = []
    for k in (camera.get("keyframes") or []):
        if not isinstance(k, dict):
            continue
        target = k.get("target") if k.get("target") in ("shuttle", "player", "point") else "shuttle"
        try:
            kf = {"t": float(k.get("t", 0.0)), "target": target,
                  "target_player": int(k.get("targetPlayer", k.get("target_player", 0)) or 0),
                  "zoom": float(k.get("zoom", 1.4))}
        except (TypeError, ValueError):
            continue
        pt = k.get("point")
        if isinstance(pt, dict):
            try:
                kf["point"] = {"x": float(pt.get("x", 0.5)), "y": float(pt.get("y", 0.45))}
            except (TypeError, ValueError):
                kf["point"] = {"x": 0.5, "y": 0.45}
        out_kfs.append(kf)
    if not out_kfs:
        return None
    return {"enabled": True, "keyframes": out_kfs}


@app.get("/api/gallery")
def gallery():
    items = []
    for job in db.gallery():
        r = _public_result(job)
        if not r:
            continue
        items.append({"id": job["id"], "filename": job["filename"],
                      "created_at": job["updated_at"], **_job_meta(job), **r})
    return {"items": items}


@app.get("/media/{job_id}/{name}")
def media_file(job_id: str, name: str):
    if name not in MEDIA_WHITELIST or not job_id.isalnum():
        raise HTTPException(404)
    path = config.OUTPUTS / job_id / name
    if not path.exists():
        raise HTTPException(404)
    return FileResponse(path)


@app.get("/api/gpu-artifacts/{job_id}/{name}")
def gpu_artifact(job_id: str, name: str, token: str = ""):
    if not job_id.isalnum() or not artifacts.verify(job_id, name, token):
        raise HTTPException(404)
    path = artifacts.path_for(job_id, name)
    if not path.exists():
        raise HTTPException(404)
    return FileResponse(path)


@app.exception_handler(500)
async def err500(_, exc):
    return JSONResponse(status_code=500, content={"error": str(exc)})


@app.middleware("http")
async def _no_html_cache(request: Request, call_next):
    """index.html must always revalidate, or UI updates never reach returning users."""
    resp = await call_next(request)
    if "text/html" in (resp.headers.get("content-type") or ""):
        resp.headers["Cache-Control"] = "no-cache"
    return resp


app.mount("/", StaticFiles(directory=config.ROOT / "web", html=True), name="web")
