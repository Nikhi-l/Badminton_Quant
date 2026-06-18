"""Baddy — AI sports highlight generator. FastAPI app serving API + frontend."""
import json
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


@app.get("/api/capabilities")
def capabilities():
    """What vision workers this deployment can run, for the upload UI."""
    gpu_ready = bool(config.RUNPOD_ENDPOINT_ID and config.RUNPOD_API_KEY)
    try:
        from .pipeline import vision_local
        local_ok, local_why = vision_local.available()
    except Exception as e:  # noqa: BLE001
        local_ok, local_why = False, str(e)
    return {
        "shuttle": {
            "tracknetv3": {
                "available": gpu_ready or (local_ok and config.VISION_ALLOW_CPU_TRACKNET),
                "backend": "runpod" if gpu_ready else ("cpu" if local_ok else "none"),
                "note": "GPU shuttle tracking" if gpu_ready
                        else "on-device (slow) " if local_ok else "not configured",
            },
        },
        "pose": {
            "yolo11": {"available": local_ok or gpu_ready,
                       "backend": "cpu" if local_ok else ("runpod" if gpu_ready else "none"),
                       "note": local_why if not local_ok else "on-device YOLO11 pose"},
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
        cur = -1 if job["status"] == "queued" else len(STAGES)
    stages = []
    for i, s in enumerate(STAGES):
        state = "pending"
        if job["status"] == "done" or i < cur:
            state = "done"
        elif i == cur and job["status"] == "processing":
            state = "active"
        stages.append({"key": s, "state": state})
    return {
        "id": job["id"], "status": job["status"], "stage": job["stage"],
        "message": job["message"], "error": job["error"], "stages": stages,
        "filename": job["filename"], "created_at": job["created_at"],
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
    db.update_stage(job_id, "render", "rebuilding reel from your edit")
    worker.enqueue_remix(job_id, {"rallies": order, "mirror": mirror})
    return {"ok": True, "id": job_id}


@app.get("/api/gallery")
def gallery():
    items = []
    for job in db.gallery():
        r = _public_result(job)
        if not r:
            continue
        items.append({"id": job["id"], "filename": job["filename"],
                      "created_at": job["updated_at"], **r})
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
