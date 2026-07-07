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
    poses = v.get("poses") or []
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
    pose_track = _sample_pose_track(poses)
    if pose_track:
        out["pose_track"] = pose_track
    return out


def _sample_shuttle_track(points: list | None, max_points: int = 180) -> list[dict]:
    """Public, bounded time-level shuttle track for editor overlays.

    Internal vision output can contain dense frame-by-frame points. The editor only
    needs enough normalized samples to place/preview shuttle graphics, so keep the
    response small and strip non-coordinate vendor details. False detections are
    filtered with the same outlier rejection the camera uses, so the overlay never
    shows a marker jumping to a light or a shirt.
    """
    if not isinstance(points, list) or not points:
        return []
    from .pipeline import track as _track
    points = _track.filter_shuttle_points(points)
    if not points:
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


def _stable_ids(frames: list[tuple[float, list[tuple[float, float, float]]]],
                max_ids: int = 4, base_gate: float = 0.22) -> list[list[int]]:
    """Stable small ids for sampled detections. frames: [(t, [(cx, cy, h), ...])].

    Greedy min-cost matching against remembered slots. Cost mixes centroid
    distance with box-height difference — the near and far player differ strongly
    in apparent height, which keeps identity when only one of them is detected.
    The match gate widens with the time gap between samples (fast rallies cover
    real court between sparse samples), and the id pool is bounded: a re-entering
    track reuses the stalest slot instead of minting ever-higher ids — the id
    churn that made the Studio look like "only P1 is ever tracked".
    Ids are finally relabeled so id 0 is the most-persistent (then nearest/tallest)
    track: P1 means the near player on every rally.
    """
    slots: dict[int, tuple[float, float, float, float]] = {}  # id -> (cx, cy, h, t_last)
    raw_ids: list[list[int]] = []
    for t, dets in frames:
        ids = [-1] * len(dets)
        cands = []
        for di, (cx, cy, h) in enumerate(dets):
            for sid, (px, py, ph, pt) in slots.items():
                dt = max(0.0, t - pt)
                gate = min(0.6, base_gate + 0.28 * max(0.0, dt - 0.25))
                cost = math.hypot(cx - px, cy - py) + 0.5 * abs(h - ph)
                if cost <= gate:
                    cands.append((cost, di, sid))
        cands.sort()
        used_d: set[int] = set()
        used_s: set[int] = set()
        for cost, di, sid in cands:
            if di in used_d or sid in used_s:
                continue
            ids[di] = sid
            used_d.add(di)
            used_s.add(sid)
        for di in range(len(dets)):
            if ids[di] != -1:
                continue
            cx, cy, h = dets[di]
            # A same-sized unmatched slot IS this player re-detected after fast
            # motion or a detector dropout — apparent height separates near from
            # far court in a fixed camera, and players don't teleport. Reusing it
            # beats minting a new id every time a lunge outruns the gate.
            sized = [s for s in slots if s not in used_s and abs(slots[s][2] - h) < 0.12]
            free = [i for i in range(max_ids) if i not in slots and i not in used_s]
            if sized:
                sid = min(sized, key=lambda s: math.hypot(cx - slots[s][0], cy - slots[s][1]))
            elif free:
                sid = free[0]
            else:
                stale = [s for s in slots if s not in used_s]
                sid = (min(stale, key=lambda s: slots[s][3]) if stale
                       else max(slots) + 1)  # >max_ids simultaneous dets: overflow safely
            ids[di] = sid
            used_s.add(sid)
        for di, sid in enumerate(ids):
            cx, cy, h = dets[di]
            slots[sid] = (cx, cy, h, t)
        raw_ids.append(ids)
    # Relabel: persistence first, then taller (nearer) first → near player = P1.
    seen: dict[int, tuple[int, list[float]]] = {}
    for (_, dets), ids in zip(frames, raw_ids):
        for (_, _, h), sid in zip(dets, ids):
            n, hs = seen.setdefault(sid, (0, []))
            hs.append(h)
            seen[sid] = (n + 1, hs)
    order = sorted(seen, key=lambda s: (-seen[s][0], -sorted(seen[s][1])[len(seen[s][1]) // 2], s))
    remap = {sid: i for i, sid in enumerate(order)}
    return [[remap[sid] for sid in ids] for ids in raw_ids]


def _sample_player_track(players: list | None, max_frames: int = 120) -> list[dict]:
    """Public, bounded per-frame player boxes with stable track ids for the editor.

    Vision stores dense per-frame player detections as boxes only. The editor needs
    normalized box centers + sizes and a consistent id per player so it can draw a
    player overlay and let the camera follow a chosen player (TASK-014/015). Ids
    come from :func:`_stable_ids` (bounded pool, motion+size-aware matching).
    """
    if not isinstance(players, list) or not players:
        return []
    step = max(1, math.ceil(len(players) / max_frames))
    sampled: list[tuple[float, list[dict]]] = []
    for f in players[::step]:
        if not isinstance(f, dict):
            continue
        norm_boxes: list[dict] = []
        for b in (f.get("boxes") or []):
            try:
                x1, y1, x2, y2 = float(b["x1"]), float(b["y1"]), float(b["x2"]), float(b["y2"])
            except (KeyError, TypeError, ValueError):
                continue
            norm_boxes.append({
                "x": round((x1 + x2) / 2.0, 5), "y": round((y1 + y2) / 2.0, 5),
                "w": round(max(0.0, x2 - x1), 5), "h": round(max(0.0, y2 - y1), 5),
                "confidence": round(float(b.get("confidence", 0.0)), 3),
            })
        if not norm_boxes:
            continue
        try:
            t = round(float(f.get("t")), 3)
        except (TypeError, ValueError):
            t = 0.0
        sampled.append((t, norm_boxes))
    ids = _stable_ids([(t, [(b["x"], b["y"], b["h"]) for b in boxes]) for t, boxes in sampled])
    out: list[dict] = []
    for (t, boxes), frame_ids in zip(sampled, ids):
        for b, sid in zip(boxes, frame_ids):
            b["id"] = sid
        out.append({"t": t, "boxes": boxes})
    return out


def _compact_bbox(raw: dict | None) -> dict | None:
    if not isinstance(raw, dict):
        return None
    try:
        x1, y1, x2, y2 = (float(raw[k]) for k in ("x1", "y1", "x2", "y2"))
    except (KeyError, TypeError, ValueError):
        return None
    return {
        "x": round((x1 + x2) / 2.0, 5),
        "y": round((y1 + y2) / 2.0, 5),
        "w": round(max(0.0, x2 - x1), 5),
        "h": round(max(0.0, y2 - y1), 5),
        "confidence": round(float(raw.get("confidence", 0.0)), 3),
    }


def _pose_center(person: dict) -> tuple[float, float] | None:
    bbox = _compact_bbox(person.get("bbox"))
    if bbox:
        return bbox["x"], bbox["y"]
    pts = []
    for p in person.get("keypoints") or []:
        try:
            if float(p.get("confidence", 0.0)) >= 0.05:
                pts.append((float(p["x"]), float(p["y"])))
        except (KeyError, TypeError, ValueError):
            continue
    if not pts:
        return None
    return sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts)


def _pose_height(person: dict, keypoints: list[dict]) -> float:
    bbox = _compact_bbox(person.get("bbox"))
    if bbox and bbox["h"] > 0:
        return bbox["h"]
    ys = [kp["y"] for kp in keypoints if kp["confidence"] >= 0.05]
    return (max(ys) - min(ys)) if len(ys) >= 2 else 0.25


def _sample_pose_track(poses: list | None, max_frames: int = 120) -> list[dict]:
    """Public, bounded COCO-17 pose track for Studio skeleton overlays.

    Canonical vision stores per-frame people with normalized keypoints. This keeps
    the full job payload useful without letting gallery/list responses inherit the
    dense raw arrays. Person ids come from :func:`_stable_ids`, the same bounded
    motion+size-aware tracker as the player boxes, so skeleton and box colors agree.
    """
    if not isinstance(poses, list) or not poses:
        return []
    step = max(1, math.ceil(len(poses) / max_frames))
    sampled: list[tuple[float, list[dict], list[tuple[float, float, float]]]] = []
    for f in poses[::step]:
        if not isinstance(f, dict):
            continue
        people: list[dict] = []
        dets: list[tuple[float, float, float]] = []
        for person in (f.get("people") or []):
            if not isinstance(person, dict):
                continue
            center = _pose_center(person)
            if center is None:
                continue
            keypoints = []
            for kp in (person.get("keypoints") or [])[:17]:
                try:
                    keypoints.append({
                        "x": round(float(kp["x"]), 5),
                        "y": round(float(kp["y"]), 5),
                        "confidence": round(float(kp.get("confidence", 0.0)), 3),
                    })
                except (KeyError, TypeError, ValueError):
                    continue
            if not keypoints:
                continue
            item = {
                "confidence": round(float(person.get("confidence", 0.0)), 3),
                "keypoints": keypoints,
            }
            bbox = _compact_bbox(person.get("bbox"))
            if bbox:
                item["bbox"] = bbox
            people.append(item)
            dets.append((center[0], center[1], _pose_height(person, keypoints)))
        if not people:
            continue
        try:
            t = round(float(f.get("t")), 3)
        except (TypeError, ValueError):
            t = 0.0
        sampled.append((t, people, dets))
    ids = _stable_ids([(t, dets) for t, _, dets in sampled])
    out: list[dict] = []
    for (t, people, _), frame_ids in zip(sampled, ids):
        for person, sid in zip(people, frame_ids):
            person["id"] = sid
        out.append({"t": t, "people": people})
    return out


def _sample_camera_path(path: list | None, max_points: int = 240) -> list[dict]:
    """Bounded render crop-window samples ({t,x,y,w,h} normalized to the source
    frame) so the Studio can project source-space tracks onto the cropped reel."""
    if not isinstance(path, list) or not path:
        return []
    step = max(1, math.ceil(len(path) / max_points))
    out = []
    for p in path[::step]:
        try:
            out.append({"t": round(float(p["t"]), 3),
                        "x": round(float(p["x"]), 4), "y": round(float(p["y"]), 4),
                        "w": round(float(p["w"]), 4), "h": round(float(p["h"]), 4)})
        except (KeyError, TypeError, ValueError):
            continue
    return out


def _public_rally(rr: dict) -> dict:
    out = {k: rr.get(k) for k in ("start", "end", "dur", "clip_dur", "src_start",
                                  "intensity", "note", "trimmed", "render_window")}
    cam = _sample_camera_path(rr.get("camera_path"))
    if cam:
        out["camera_path"] = cam
    vision = _compact_vision(rr.get("vision"))
    if vision:
        out["vision"] = vision
    return out


def _public_result(job: dict, light: bool = False) -> dict | None:
    """Public reel payload. `light=True` (gallery list) omits the heavy per-rally
    tracking arrays (shuttle_track / players_track via the rallies + rally_pool) so
    listing many reels stays small and fast — the Studio re-fetches the full result
    by id when a reel is opened. `light=False` (single job) returns everything."""
    import json
    if not job.get("result"):
        return None
    r = json.loads(job["result"])
    out = {
        "video": f"/media/{job['id']}/reel.mp4",
        "thumb": f"/media/{job['id']}/thumb.jpg",
        "proxy": f"/media/{job['id']}/proxy.mp4",
        "duration": r.get("duration"),
        "sport": r.get("sport"),
        "n_rallies_found": r.get("n_rallies_found"),
        "n_rallies_used": r.get("n_rallies_used"),
        "source_duration": (r.get("source") or {}).get("duration"),
        "n_clips": r.get("n_clips", 1),
        "clip_order": r.get("clip_order"),
        "pov_camera": r.get("pov_camera"),
        "vision": r.get("vision"),
        "options": r.get("options"),
        "coach": r.get("coach"),
        "remix": r.get("remix"),
        "gemini_usage": r.get("gemini_usage"),
        "elapsed_sec": r.get("elapsed_sec"),
    }
    if light:
        return out
    out["stitch"] = r.get("stitch")
    out["rallies"] = [_public_rally(rr) for rr in r.get("rallies", [])]
    out["all_rallies"] = r.get("all_rallies", [])
    out["rally_pool"] = ([_public_rally(rr) for rr in r.get("rally_pool", [])]
                         if isinstance(r.get("rally_pool"), list) else None)
    return out


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
                       "backend": "runpod" if config.pose_prefers_gpu() and gpu_ready
                                  else ("local" if pose_ok else "none"),
                       "model": config.POSE_MODEL_GPU if config.pose_prefers_gpu() and gpu_ready
                                else config.POSE_MODEL_LOCAL,
                       "note": ("RunPod YOLO pose" if config.pose_prefers_gpu() and gpu_ready
                                else "on-device YOLO pose") if (pose_ok or gpu_ready) else pose_why},
            "pose": {"available": pose_ok or gpu_ready,
                     "backend": "runpod" if config.pose_prefers_gpu() and gpu_ready
                                else ("local" if pose_ok else "none"),
                     "model": config.POSE_MODEL_GPU if config.pose_prefers_gpu() and gpu_ready
                              else config.POSE_MODEL_LOCAL},
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
        r = _public_result(job, light=True)   # list view: no heavy per-rally tracking
        if not r:
            continue
        items.append({"id": job["id"], "filename": job["filename"],
                      "created_at": job["updated_at"], **_job_meta(job), **r})
    return {"items": items}


@app.get("/api/jobs")
def jobs_queue(limit: int = 60):
    """Queue view (TASK-005): every job newest-first with live status, the CPU/GPU
    pipeline, submission + generation time, and the error on failed jobs."""
    out = []
    for job in db.recent_jobs(limit):
        status = job.get("status")
        item = {
            "id": job["id"],
            "filename": job.get("filename"),
            "status": status,
            "stage": job.get("stage"),
            "message": job.get("message"),
            "error": job.get("error") if status == "failed" else None,
            **_job_meta(job),
        }
        if status == "done":
            item["thumb"] = f"/media/{job['id']}/thumb.jpg"
        out.append(item)
    return {"jobs": out}


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
