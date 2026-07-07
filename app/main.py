"""Baddy — AI sports highlight generator. FastAPI app serving API + frontend."""
import json
import math
import shutil
import time
import uuid
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import artifacts, auth, config, db, worker
from .pipeline import court as court_geo
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
    # Signed-in uploads belong to the uploader's school (TASK-026); anonymous
    # uploads keep working exactly as before with NULL ownership.
    user = auth.current_user(request)
    if user and user.get("school_id"):
        db.set_job_owner(job_id, user["school_id"], user["id"])
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
    return _relabel_merged(frames, raw_ids)


def _relabel_merged(frames: list[tuple[float, list[tuple[float, float, float]]]],
                    raw_ids: list[list[int]]) -> list[list[int]]:
    """Fragment-merge + near-player-first relabel over raw per-frame ids.

    Shared by the heuristic matcher and worker-supplied (ByteTrack) ids, so
    P1 = the near player regardless of where identity came from.
    """
    # Track stats: sample count, heights, and lifespan per raw id.
    seen: dict[int, dict] = {}
    for (t, dets), ids in zip(frames, raw_ids):
        for (_, _, h), sid in zip(dets, ids):
            st = seen.setdefault(sid, {"n": 0, "hs": [], "t0": t, "t1": t})
            st["n"] += 1
            st["hs"].append(h)
            st["t0"] = min(st["t0"], t)
            st["t1"] = max(st["t1"], t)
    med = {sid: sorted(st["hs"])[len(st["hs"]) // 2] for sid, st in seen.items()}

    # Merge fragments: a track that dies and another that starts later at the
    # same apparent height are the same player re-acquired (a long occlusion or
    # a missed stretch splits one player into P1+P3 otherwise).
    group = {sid: sid for sid in seen}
    for sid in sorted(seen, key=lambda s: seen[s]["t0"]):
        for tid in sorted(seen, key=lambda s: seen[s]["t0"]):
            if group[tid] == group[sid] or tid == sid:
                continue
            a, b = seen[sid], seen[tid]
            overlap = min(a["t1"], b["t1"]) - max(a["t0"], b["t0"])
            if overlap <= 0.0 and abs(med[sid] - med[tid]) < 0.1:
                root = group[sid]
                for k, g in group.items():
                    if g == group[tid]:
                        group[k] = root
    # Relabel groups: persistence first, then taller (nearer) first → P1 = near player.
    gstat: dict[int, tuple[int, list[float]]] = {}
    for sid, st in seen.items():
        n, hs = gstat.setdefault(group[sid], (0, []))
        gstat[group[sid]] = (n + st["n"], hs + st["hs"])
    order = sorted(gstat, key=lambda g: (-gstat[g][0], -sorted(gstat[g][1])[len(gstat[g][1]) // 2], g))
    remap = {g: i for i, g in enumerate(order)}
    return [[remap[group[sid]] for sid in ids] for ids in raw_ids]


def _ids_from_worker(worker_ids: list[list[int | None]]) -> list[list[int]] | None:
    """Densified per-frame ids from the worker's ByteTrack track_ids (TASK-024),
    or None when coverage is too thin to trust (falls back to the heuristic).
    Rare id-less detections get isolated one-off ids; the fragment merge folds
    them back into the right player where the size evidence agrees."""
    total = have = 0
    for row in worker_ids:
        for wid in row:
            total += 1
            have += wid is not None
    if not total or have / total < 0.9:
        return None
    dense: dict[int, int] = {}
    out: list[list[int]] = []
    orphan = 1000
    for row in worker_ids:
        ids = []
        for wid in row:
            if wid is None:
                ids.append(orphan)
                orphan += 1
            else:
                ids.append(dense.setdefault(int(wid), len(dense)))
        out.append(ids)
    return out


def _sample_player_track(players: list | None, max_frames: int = 120) -> list[dict]:
    """Public, bounded per-frame player boxes with stable track ids for the editor.

    Vision stores dense per-frame player detections as boxes only. The editor needs
    normalized box centers + sizes and a consistent id per player so it can draw a
    player overlay and let the camera follow a chosen player (TASK-014/015). Ids
    prefer the worker's ByteTrack track_ids (TASK-024) and fall back to
    :func:`_stable_ids` (bounded pool, motion+size-aware matching); both paths
    share the fragment merge + near-player-first relabel.
    """
    if not isinstance(players, list) or not players:
        return []
    step = max(1, math.ceil(len(players) / max_frames))
    sampled: list[tuple[float, list[dict]]] = []
    worker_ids: list[list[int | None]] = []
    for f in players[::step]:
        if not isinstance(f, dict):
            continue
        norm_boxes: list[dict] = []
        wids: list[int | None] = []
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
            tid = b.get("track_id")
            wids.append(int(tid) if isinstance(tid, (int, float)) else None)
        if not norm_boxes:
            continue
        try:
            t = round(float(f.get("t")), 3)
        except (TypeError, ValueError):
            t = 0.0
        sampled.append((t, norm_boxes))
        worker_ids.append(wids)
    frames = [(t, [(b["x"], b["y"], b["h"]) for b in boxes]) for t, boxes in sampled]
    raw = _ids_from_worker(worker_ids)
    ids = _relabel_merged(frames, raw) if raw else _stable_ids(frames)
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
    worker_ids: list[list[int | None]] = []
    for f in poses[::step]:
        if not isinstance(f, dict):
            continue
        people: list[dict] = []
        dets: list[tuple[float, float, float]] = []
        wids: list[int | None] = []
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
            tid = person.get("track_id")
            wids.append(int(tid) if isinstance(tid, (int, float)) else None)
        if not people:
            continue
        try:
            t = round(float(f.get("t")), 3)
        except (TypeError, ValueError):
            t = 0.0
        sampled.append((t, people, dets))
        worker_ids.append(wids)
    frames = [(t, dets) for t, _, dets in sampled]
    raw = _ids_from_worker(worker_ids)
    ids = _relabel_merged(frames, raw) if raw else _stable_ids(frames)
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
    out["court"] = r.get("court")
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


# ---------- schools platform: auth + panels (TASK-026 P0) ----------

_LOGIN_HITS: dict[str, list[float]] = {}


def _login_throttle(request: Request):
    ip = (request.headers.get("x-forwarded-for", "").split(",")[0].strip()
          or (request.client.host if request.client else "?"))
    now = time.time()
    hits = [t for t in _LOGIN_HITS.get(ip, []) if now - t < 600]
    if len(hits) >= 10:
        raise HTTPException(429, "too many attempts — try again in a few minutes")
    _LOGIN_HITS[ip] = hits + [now]


@app.post("/api/auth/register-school")
async def auth_register_school(payload: dict, request: Request, response: Response):
    """Create a school + its first admin account, signed in on success."""
    _login_throttle(request)
    school_name = str(payload.get("school_name") or "").strip()
    username = str(payload.get("username") or "")
    name = str(payload.get("name") or "")
    password = str(payload.get("password") or "")
    if not 2 <= len(school_name) <= 80:
        raise HTTPException(400, "school name is required")
    err = auth.validate_credentials(username, password, name)
    if err:
        raise HTTPException(400, err)
    user = auth.register_user(username, name, password)
    school_id = uuid.uuid4().hex[:12]
    db.create_school(school_id, school_name,
                     auth.new_join_code("ST"), auth.new_join_code("CO"))
    db.add_membership(user["id"], school_id, "admin")
    auth.start_session(response, request, user["id"])
    return {"ok": True, "school_id": school_id, "role": "admin"}


@app.post("/api/auth/join")
async def auth_join(payload: dict, request: Request, response: Response):
    """Join an existing school with a student or coach code."""
    _login_throttle(request)
    resolved = db.school_by_join_code(str(payload.get("code") or ""))
    if not resolved:
        raise HTTPException(404, "unknown join code")
    school, role = resolved
    username = str(payload.get("username") or "")
    name = str(payload.get("name") or "")
    password = str(payload.get("password") or "")
    err = auth.validate_credentials(username, password, name)
    if err:
        raise HTTPException(400, err)
    user = auth.register_user(username, name, password)
    db.add_membership(user["id"], school["id"], role)
    auth.start_session(response, request, user["id"])
    return {"ok": True, "school_id": school["id"], "role": role}


@app.post("/api/auth/login")
async def auth_login(payload: dict, request: Request, response: Response):
    _login_throttle(request)
    user = db.get_user_by_username(str(payload.get("username") or ""))
    if not user or not auth.verify_password(str(payload.get("password") or ""), user["pass_hash"]):
        raise HTTPException(401, "wrong username or password")
    auth.start_session(response, request, user["id"])
    m = db.membership_of(user["id"]) or {}
    return {"ok": True, "role": m.get("role")}


@app.post("/api/auth/logout")
async def auth_logout(request: Request, response: Response):
    auth.end_session(request, response)
    return {"ok": True}


@app.get("/api/auth/me")
def auth_me(request: Request):
    user = auth.current_user(request)
    if not user:
        raise HTTPException(401, "not signed in")
    return user


@app.get("/api/school/overview")
def school_overview(request: Request):
    """Coach/admin panel data: roster, join codes, recent school sessions."""
    user = auth.require_role(request, "admin", "coach")
    school = db.get_school(user["school_id"]) or {}
    jobs = []
    for job in db.school_jobs(user["school_id"]):
        item = {
            "id": job["id"], "filename": job.get("filename"), "status": job.get("status"),
            "created_at": job.get("created_at"),
            "assignees": db.job_assignees(job["id"]),
        }
        if job.get("status") == "done":
            item["thumb"] = f"/media/{job['id']}/thumb.jpg"
            r = _public_result(job, light=True)
            if r:
                item.update(duration=r.get("duration"), n_rallies_used=r.get("n_rallies_used"),
                            vision=r.get("vision"))
        jobs.append(item)
    return {
        "school": {"id": school.get("id"), "name": school.get("name")},
        "join_codes": {
            "student": school.get("student_code"),
            "coach": school.get("coach_code") if user["role"] == "admin" else None,
        },
        "students": db.school_members(user["school_id"], "student"),
        "coaches": [m for m in db.school_members(user["school_id"])
                    if m["role"] in ("coach", "admin")],
        "jobs": jobs,
    }


@app.post("/api/jobs/{job_id}/assign")
async def job_assign(job_id: str, payload: dict, request: Request):
    """Assign a session video to a student, optionally pinning which tracked
    player (players_track id) is them — that pin drives per-student metrics."""
    user = auth.require_role(request, "admin", "coach")
    job = db.get_job(job_id)
    if not job or job.get("school_id") != user["school_id"]:
        raise HTTPException(404, "job not found in your school")
    student_id = str(payload.get("student_id") or "")
    students = {m["id"] for m in db.school_members(user["school_id"], "student")}
    if student_id not in students:
        raise HTTPException(404, "student not found in your school")
    player_id = payload.get("player_id")
    if player_id is not None:
        try:
            player_id = int(player_id)
        except (TypeError, ValueError):
            raise HTTPException(400, "player_id must be an integer or null")
    db.assign_job_student(job_id, student_id, player_id, user["id"])
    return {"ok": True, "assignees": db.job_assignees(job_id)}


@app.delete("/api/jobs/{job_id}/assign/{student_id}")
def job_unassign(job_id: str, student_id: str, request: Request):
    user = auth.require_role(request, "admin", "coach")
    job = db.get_job(job_id)
    if not job or job.get("school_id") != user["school_id"]:
        raise HTTPException(404, "job not found in your school")
    db.unassign_job_student(job_id, student_id)
    return {"ok": True}


def _movement_stats(result: dict, player_id: int | None) -> dict:
    """Court-space movement for the pinned player across all rallies: distance
    (m), court coverage (% of a 10x22 grid visited). Camera-space fallback
    reports coverage only. Bounded by the same samplers the Studio uses."""
    court_info = result.get("court") or {}
    H = court_info.get("homography") if court_info.get("status") == "ok" else None
    cells: set[tuple[int, int]] = set()
    dist = 0.0
    prev = None
    n_pts = 0
    for rr in result.get("rallies") or []:
        players = ((rr.get("vision") or {}).get("players")) or []
        for f in _sample_player_track(players):
            for b in f["boxes"]:
                if player_id is not None and b["id"] != player_id:
                    continue
                x, y = b["x"], b["y"] + b["h"] / 2  # foot point
                n_pts += 1
                if H:
                    u, v = court_geo.project(H, x, y)
                    if not (-1.0 <= u <= 7.1 and -1.5 <= v <= 14.9):
                        prev = None
                        continue
                    cells.add((int(max(0.0, min(0.99, u / 6.1)) * 10),
                               int(max(0.0, min(0.99, v / 13.4)) * 22)))
                    if prev is not None:
                        step = ((u - prev[0]) ** 2 + (v - prev[1]) ** 2) ** 0.5
                        if step < 3.0:  # ignore teleports across sample gaps
                            dist += step
                    prev = (u, v)
                else:
                    cells.add((int(max(0.0, min(0.99, x)) * 10),
                               int(max(0.0, min(0.99, y)) * 22)))
        prev = None
    return {
        "points": n_pts,
        "distance_m": round(dist, 1) if H else None,
        "coverage_pct": round(len(cells) / (10 * 22) * 100, 1),
        "court_space": bool(H),
    }


@app.get("/api/students/{student_id}/profile")
def student_profile(student_id: str, request: Request):
    """Everything the student panel shows: highlights, rallies, AI-coach notes,
    per-session progress metrics. Visible to the student themself and to
    coaches/admins of the same school."""
    user = auth.require_user(request)
    if user["id"] != student_id:
        auth.require_role(request, "admin", "coach")
    student = db.get_user(student_id)
    member = next((m for m in db.school_members(user["school_id"], "student")
                   if m["id"] == student_id), None)
    if not student or member is None:
        raise HTTPException(404, "student not found in your school")

    sessions = []
    for job in db.student_assignments(student_id):
        try:
            result = json.loads(job["result"]) if job.get("result") else {}
        except ValueError:
            continue
        rallies = result.get("rallies") or []
        durs = [float(r.get("dur") or 0) for r in rallies]
        summary = ((result.get("vision") or {}).get("summary")) or {}
        coach_out = result.get("coach") or {}
        sessions.append({
            "job_id": job["id"],
            "filename": job.get("filename"),
            "date": job.get("created_at"),
            "video": f"/media/{job['id']}/reel.mp4",
            "thumb": f"/media/{job['id']}/thumb.jpg",
            "duration": result.get("duration"),
            "player_id": job.get("player_id"),
            "n_rallies": len(rallies),
            "longest_rally": round(max(durs), 1) if durs else 0,
            "rallies": [{"i": i + 1, "dur": r.get("dur"), "note": r.get("note"),
                         "shuttle_quality": ((r.get("vision") or {}).get("shuttle_quality"))}
                        for i, r in enumerate(rallies)],
            "quality": {"shuttle": summary.get("shuttle_quality"),
                        "pose": summary.get("pose_quality"),
                        "players": summary.get("player_quality")},
            "coach": ({"headline": coach_out.get("headline"),
                       "confidence": coach_out.get("confidence"),
                       "strengths": (coach_out.get("strengths") or [])[:3],
                       "work_on": (coach_out.get("work_on") or [])[:3]}
                      if coach_out.get("status") == "ok" else None),
            "movement": _movement_stats(result, job.get("player_id")),
        })
    sessions.sort(key=lambda s: s["date"] or 0)
    return {
        "student": {"id": student["id"], "name": student["name"],
                    "username": student["username"]},
        "school": {"id": user["school_id"], "name": user["school_name"]},
        "sessions": sessions,
    }


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
