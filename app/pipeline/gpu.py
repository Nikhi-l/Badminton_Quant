"""Optional Runpod-backed player/pose/racquet/shuttle analysis.

The CPU pipeline is the source of truth for job completion. This module adds a
best-effort GPU pass that can enrich camera tracking, shuttle overlays, and
Studio coaching metadata whenever a Runpod Serverless endpoint is configured.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import requests

from .. import artifacts, config

CONTRACT = "baddy.vision.v1"


def _clamp01(v: Any, default: float = 0.0) -> float:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return default
    return min(max(f, 0.0), 1.0)


def _num(v: Any, default: float = 0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _disabled(message: str) -> dict:
    return {
        "enabled": False,
        "status": "disabled",
        "engine": "cpu-motion",
        "contract": CONTRACT,
        "message": message,
        "summary": {
            "camera_mode": "cpu_motion",
            "shuttle_mask": False,
            "shuttle_quality": 0.0,
            "pose_quality": 0.0,
            "racquet_quality": 0.0,
            "player_quality": 0.0,
        },
        "rallies": [],
    }


def _failed(message: str) -> dict:
    out = _disabled(message)
    out.update(enabled=True, status="failed", engine="runpod")
    return out


def _short_text(v: Any, limit: int = 140) -> str:
    text = " ".join(str(v or "").split())
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + "..."


def _basename(v: Any) -> str | None:
    if not v:
        return None
    return Path(str(v)).name


def _redacted(v: str) -> str | None:
    if not v:
        return None
    if len(v) <= 8:
        return v
    return f"{v[:4]}...{v[-4:]}"


def _model_status(raw: dict) -> dict:
    status = raw.get("model_status") if isinstance(raw.get("model_status"), dict) else {}
    pose_model = status.get("pose_model")
    racquet_model = status.get("racquet_model")
    tracknet_model = status.get("tracknet_model")
    return {
        "pose": {
            "enabled": bool(pose_model),
            "model": _basename(pose_model),
            "requested_model": _basename(status.get("pose_requested_model")),
            "fallback_model": _basename(status.get("pose_fallback_model")),
            "backend": status.get("pose_backend") or "",
            "device": str(status.get("pose_device") or ""),
            "load_status": str(status.get("pose_load_status") or ("loaded" if pose_model else "not_loaded")),
        },
        "racquet": {
            "enabled": bool(racquet_model),
            "model": _basename(racquet_model),
            "source": str(status.get("racquet_source") or ""),
            "mode": "measured_boxes" if racquet_model else "not_configured",
        },
        "tracknet": {
            "enabled": bool(tracknet_model),
            "model": _basename(tracknet_model),
            "repo_baked": bool(status.get("tracknet_repo")),
            "error": _short_text(status.get("tracknet_error")) if status.get("tracknet_error") else "",
        },
        "fallback": bool(status.get("fallback")),
        "error": _short_text(status.get("error")) if status.get("error") else "",
    }


def readiness() -> dict:
    """Return non-secret config readiness without submitting a GPU job."""
    runpod_ready = bool(config.RUNPOD_ENDPOINT_ID and config.RUNPOD_API_KEY)
    artifact_ready = bool(config.PUBLIC_BASE_URL and config.GPU_ARTIFACT_TOKEN)
    return {
        "contract": CONTRACT,
        "runpod": {
            "configured": runpod_ready,
            "endpoint_id": _redacted(config.RUNPOD_ENDPOINT_ID),
            "base_url": config.RUNPOD_BASE_URL,
            "api_key": "configured" if config.RUNPOD_API_KEY else "missing",
            "artifact_input": artifact_ready,
            "timeout_sec": config.RUNPOD_TIMEOUT_SEC,
            "poll_sec": config.RUNPOD_POLL_SEC,
        },
        "coach": {
            "enabled": bool(config.COACH_ENABLED),
            "model": config.COACH_MODEL,
            "frame_count": config.COACH_FRAME_COUNT,
            "frame_height": config.COACH_FRAME_HEIGHT,
            "gemini_key": "configured" if config.GEMINI_API_KEY else "missing",
        },
        "render": {
            "shuttle_mask_min_quality": config.SHUTTLE_MASK_MIN_QUALITY,
            "shuttle_mask_min_conf": config.SHUTTLE_MASK_MIN_CONF,
        },
        "ready_for_gpu_jobs": bool(runpod_ready and artifact_ready),
        "submits_gpu_job": False,
    }


def _box(raw: Any) -> dict | None:
    if isinstance(raw, dict):
        if "box" in raw:
            b = _box(raw["box"])
            if b:
                b["confidence"] = _clamp01(raw.get("confidence", raw.get("conf", b["confidence"])))
                if isinstance(raw.get("track_id"), (int, float)):   # ByteTrack id (TASK-024)
                    b["track_id"] = int(raw["track_id"])
            return b
        if {"x1", "y1", "x2", "y2"} <= raw.keys():
            x1, y1, x2, y2 = (_clamp01(raw[k]) for k in ("x1", "y1", "x2", "y2"))
            conf = _clamp01(raw.get("confidence", raw.get("conf", raw.get("score", 1.0))), 1.0)
            return {"x1": min(x1, x2), "y1": min(y1, y2),
                    "x2": max(x1, x2), "y2": max(y1, y2), "confidence": conf}
        if {"x", "y", "w", "h"} <= raw.keys():
            x, y, w, h = (_clamp01(raw[k]) for k in ("x", "y", "w", "h"))
            conf = _clamp01(raw.get("confidence", raw.get("conf", raw.get("score", 1.0))), 1.0)
            return {"x1": x, "y1": y, "x2": _clamp01(x + w), "y2": _clamp01(y + h),
                    "confidence": conf}
    if isinstance(raw, (list, tuple)) and len(raw) >= 4:
        x1, y1, x2, y2 = (_clamp01(v) for v in raw[:4])
        conf = _clamp01(raw[4] if len(raw) > 4 else 1.0, 1.0)
        return {"x1": min(x1, x2), "y1": min(y1, y2),
                "x2": max(x1, x2), "y2": max(y1, y2), "confidence": conf}
    return None


def _point(raw: Any) -> dict | None:
    if isinstance(raw, dict):
        if "point" in raw:
            p = _point(raw["point"])
            if p:
                p["confidence"] = _clamp01(raw.get("confidence", raw.get("conf", p["confidence"])))
            return p
        if {"x", "y"} <= raw.keys():
            point = {
                "x": _clamp01(raw["x"]),
                "y": _clamp01(raw["y"]),
                "confidence": _clamp01(raw.get("confidence", raw.get("conf", raw.get("score", 1.0))), 1.0),
            }
            if raw.get("source"):
                point["source"] = str(raw.get("source"))[:40]
            return point
    if isinstance(raw, (list, tuple)) and len(raw) >= 2:
        return {
            "x": _clamp01(raw[0]),
            "y": _clamp01(raw[1]),
            "confidence": _clamp01(raw[2] if len(raw) > 2 else 1.0, 1.0),
        }
    return None


def _keypoints(raw: Any) -> list[dict]:
    pts = raw.get("keypoints") if isinstance(raw, dict) else raw
    if not isinstance(pts, list):
        return []
    out = []
    for item in pts:
        p = _point(item)
        if p:
            out.append({"x": p["x"], "y": p["y"], "confidence": p["confidence"]})
    return out


def _pose_people(raw_poses: Any, boxes: list[dict]) -> list[dict]:
    if not isinstance(raw_poses, list):
        return []
    # Some integrations send one bare keypoint list instead of a list of people.
    if raw_poses and isinstance(raw_poses[0], dict) and {"x", "y"} <= raw_poses[0].keys():
        raw_poses = [{"keypoints": raw_poses}]
    people = []
    for i, raw_pose in enumerate(raw_poses[:6]):   # gate trims back to 4 (TASK-042)
        pts = _keypoints(raw_pose)
        if not pts:
            continue
        conf = _conf(raw_pose, sum(p["confidence"] for p in pts) / max(len(pts), 1))
        person = {
            "id": i,
            "confidence": round(conf, 3),
            "keypoints": pts[:17],
        }
        if isinstance(raw_pose, dict) and isinstance(raw_pose.get("track_id"), (int, float)):
            person["track_id"] = int(raw_pose["track_id"])   # ByteTrack id (TASK-024)
        if i < len(boxes):
            person["bbox"] = {k: boxes[i][k] for k in ("x1", "y1", "x2", "y2", "confidence")}
        people.append(person)
    return people


def _abs_t(raw_t: Any, rally: dict) -> float:
    t = _num(raw_t)
    start = _num(rally.get("start"))
    dur = _num(rally.get("dur"), _num(rally.get("end")) - start)
    if t < start - 0.25 and 0 <= t <= dur + config.PAD_BEFORE + config.PAD_AFTER + 1:
        return start + t
    return t


def _conf(raw: Any, default: float = 1.0) -> float:
    if isinstance(raw, dict):
        return _clamp01(raw.get("confidence", raw.get("conf", raw.get("score", default))), default)
    return _clamp01(default, default)


def _frames_from(raw_rally: dict, rally: dict,
                 court_corners: list | None = None) -> tuple[list[dict], list[dict], list[dict], list[dict], list[dict]]:
    shuttle: list[dict] = []
    players: list[dict] = []
    poses: list[dict] = []
    racquets: list[dict] = []
    racquet_candidates: list[dict] = []

    def add_frame(frame: dict):
        t = _abs_t(frame.get("t", frame.get("time", frame.get("sec", 0))), rally)
        raw_shuttle = frame.get("shuttle")
        if raw_shuttle is None and frame.get("shuttle_x") is not None and frame.get("shuttle_y") is not None:
            raw_shuttle = {
                "x": frame.get("shuttle_x"),
                "y": frame.get("shuttle_y"),
                "confidence": frame.get("shuttle_confidence", frame.get("shuttle_conf")),
            }
        p = _point(raw_shuttle) if raw_shuttle is not None else None
        if p and p["confidence"] >= 0:
            shuttle.append({"t": t, **p})
        raw_players = (
            frame.get("players")
            or frame.get("player_boxes")
            or frame.get("person_boxes")
            or frame.get("people")
            or []
        )
        boxes = [_box(b) for b in raw_players]
        boxes = [b for b in boxes if b and b["confidence"] >= 0.05]
        if boxes:
            # collect 6 so the court gate below sees background players before
            # the doubles cap — [:4] here let a background box evict a real
            # far player from storage entirely (TASK-042)
            players.append({"t": t, "boxes": boxes[:6]})
        raw_poses = frame.get("poses") or frame.get("pose_tracks") or frame.get("keypoints") or []
        people = _pose_people(raw_poses, boxes)
        if people:
            conf = round(sum(p["confidence"] for p in people) / len(people), 3)
            poses.append({"t": t, "people": people, "count": len(people), "confidence": conf})
        raw_racquets = frame.get("racquets") or frame.get("rackets") or frame.get("racquet_boxes") or []
        racket_boxes = [_box(b) for b in raw_racquets]
        racket_boxes = [b for b in racket_boxes if b and b["confidence"] >= 0.05][:4]
        if racket_boxes:   # doubles = up to 4 racquets (TASK-031)
            racquets.append({"t": t, "boxes": racket_boxes,
                             "confidence": round(sum(b["confidence"] for b in racket_boxes)
                                                 / len(racket_boxes), 3)})
        raw_candidates = frame.get("racquet_candidates") or frame.get("racket_candidates") or []
        candidate_boxes = [_box(b) for b in raw_candidates]
        candidate_boxes = [b for b in candidate_boxes if b and b["confidence"] >= 0.05][:4]
        if candidate_boxes:
            racquet_candidates.append({
                "t": t,
                "boxes": candidate_boxes,
                "confidence": round(sum(b["confidence"] for b in candidate_boxes)
                                    / len(candidate_boxes), 3),
                "source": "pose_guided_line",
            })

    for f in raw_rally.get("frames") or raw_rally.get("timeline") or []:
        if isinstance(f, dict):
            add_frame(f)

    for p in raw_rally.get("shuttle") or raw_rally.get("shuttle_track") or []:
        if not isinstance(p, dict):
            p = {"point": p}
        point = _point(p)
        if point:
            t = _abs_t(p.get("t", p.get("time", p.get("sec", 0))), rally)
            shuttle.append({"t": t, **point})

    for f in raw_rally.get("players") or raw_rally.get("player_tracks") or []:
        if not isinstance(f, dict):
            continue
        t = _abs_t(f.get("t", f.get("time", f.get("sec", 0))), rally)
        raw_boxes = f.get("boxes") or f.get("players") or f.get("detections") or []
        boxes = [_box(b) for b in raw_boxes]
        boxes = [b for b in boxes if b and b["confidence"] >= 0.05]
        if boxes:
            players.append({"t": t, "boxes": boxes[:6]})

    shuttle.sort(key=lambda x: x["t"])
    # TASK-035: replace the workers' placeholder confidence (flat 0.82 —
    # TrackNet only exposes binary visibility) with measured plausibility +
    # provenance BEFORE storage, so every consumer (camera, Studio, render
    # marker, 3D) inherits it. Both vision backends flow through here
    # (vision.py routes the CPU path into _canonicalize too).
    from . import track as _track
    shuttle = _track.refine_shuttle_track(shuttle)
    # TASK-041: a background court's rally passes every kinematic filter —
    # only geometry separates the courts. Segment-level main-court gate.
    shuttle = _track.court_shuttle_gate(shuttle, court_corners)
    players.sort(key=lambda x: x["t"])
    poses.sort(key=lambda x: x["t"])
    # TASK-042: player feet live ON the floor quad (unlike the airborne
    # shuttle), so the full expanded quad gates people deterministically —
    # neighbouring-court players never reach the camera, evaluator, or Studio.
    players, poses = _track.court_player_gate(players, poses, court_corners)
    racquets.sort(key=lambda x: x["t"])
    racquet_candidates.sort(key=lambda x: x["t"])
    return shuttle, players, poses, racquets, racquet_candidates


def _sampling_meta(rr: dict, dur: float) -> dict:
    """Per-rally sampling telemetry (TASK-044 Slice 0).

    Worker-reported when present (new workers emit a ``sampling`` block);
    always augmented with a MEASURED cadence from the raw frame timestamps so
    old stored raws and the CPU path gain effective-cadence visibility on
    reprocess. Fail-open: absent data yields nulls, never an error.
    """
    raw = rr.get("sampling") if isinstance(rr.get("sampling"), dict) else {}
    ts = sorted({round(_num(f.get("t")), 3)
                 for f in (rr.get("frames") or []) if isinstance(f, dict)})
    measured = None
    if len(ts) >= 2:
        dts = sorted(b - a for a, b in zip(ts, ts[1:]) if b - a > 1e-4)
        if dts:
            measured = round(1.0 / dts[len(dts) // 2], 3)   # median spacing
    out = {
        "requested_sample_fps": _num(raw.get("requested_sample_fps")) or None,
        "effective_sample_fps": _num(raw.get("effective_sample_fps")) or None,
        "measured_sample_fps": measured,
        "sample_count": int(_num(raw.get("sample_count"), len(ts))),
        "degraded": str(raw.get("degraded") or ""),
    }
    if raw.get("frame_cap") is not None:
        out["frame_cap"] = int(_num(raw.get("frame_cap")))
    return out


def _track_health(players: list[dict], poses: list[dict],
                  cadence_fps: float) -> dict:
    """Per-worker-track-id health vectors (TASK-044 Slice 0).

    The aggregate player/pose qualities average confidence×coverage over the
    whole rally — they cannot say WHICH track went unhealthy or when. This
    records, per BoT-SORT track id: samples seen, observed span, longest
    unobserved gap inside the span, coverage against the sampling cadence, and
    mean confidence. It is telemetry for the labelled bench and the future
    selective-reprocessing router; nothing downstream steers on it yet.
    """
    def per_track(frames: list[dict], key: str, conf_of) -> dict:
        tracks: dict[int, dict] = {}
        for f in frames or []:
            if not isinstance(f, dict):
                continue
            t = _num(f.get("t"))
            for item in f.get(key) or []:
                tid = item.get("track_id") if isinstance(item, dict) else None
                if not isinstance(tid, (int, float)):
                    continue
                st = tracks.setdefault(int(tid), {
                    "n": 0, "t0": t, "t1": t, "gap": 0.0, "conf": 0.0, "_last": None})
                if st["_last"] is not None:
                    st["gap"] = max(st["gap"], t - st["_last"])
                st["_last"] = t
                st["n"] += 1
                st["t0"] = min(st["t0"], t)
                st["t1"] = max(st["t1"], t)
                st["conf"] += _clamp01(conf_of(item))
        out = {}
        # top 8 by sample count: doubles + a couple of transient ids, bounded
        for tid in sorted(tracks, key=lambda k: -tracks[k]["n"])[:8]:
            st = tracks[tid]
            span = max(st["t1"] - st["t0"], 0.0)
            expected = max(1.0, span * max(cadence_fps, 0.1) + 1.0)
            out[str(tid)] = {
                "samples": st["n"],
                "t0": round(st["t0"], 3),
                "t1": round(st["t1"], 3),
                "longest_gap_sec": round(st["gap"], 3),
                "coverage": round(min(1.0, st["n"] / expected), 3),
                "mean_conf": round(st["conf"] / max(st["n"], 1), 3),
            }
        return out

    health = {}
    p = per_track(players, "boxes", lambda b: b.get("confidence", 0.0))
    if p:
        health["players"] = p
    q = per_track(poses, "people", lambda pp: pp.get("confidence", 0.0))
    if q:
        health["poses"] = q
    return health


def _score_samples(samples: list[dict], dur: float, fps_goal: float = 5.0) -> float:
    if not samples:
        return 0.0
    conf = sum(_clamp01(s.get("confidence", 1.0), 1.0) for s in samples) / len(samples)
    coverage = min(1.0, len(samples) / max(3.0, dur * fps_goal))
    return round(conf * coverage, 3)


def _match(raw_rallies: list, idx: int) -> dict:
    for rr in raw_rallies:
        if isinstance(rr, dict) and int(_num(rr.get("rally_index", rr.get("index", -1)), -1)) == idx:
            return rr
    if idx - 1 < len(raw_rallies) and isinstance(raw_rallies[idx - 1], dict):
        return raw_rallies[idx - 1]
    return {}


def _canonicalize(raw: Any, rallies: list[dict],
                  court_corners: list | None = None) -> dict:
    if isinstance(raw, str):
        raw = json.loads(raw)
    raw = raw if isinstance(raw, dict) else {}
    raw_rallies = raw.get("rallies") or raw.get("results") or raw.get("clips") or []
    out_rallies = []
    for idx, rally in enumerate(rallies, 1):
        rr = _match(raw_rallies, idx)
        shuttle, players, poses, racquets, racquet_candidates = _frames_from(rr, rally, court_corners)
        dur = _num(rally.get("dur"), _num(rally.get("end")) - _num(rally.get("start")))
        # TASK-041: score the track the CONSUMERS actually use — i.e. after the
        # SAME Hampel outlier filter the public overlay and camera apply
        # (filter_shuttle_points), not the raw refined list. The worker scores
        # its own raw output (still visible in the tracknet payload); a rally
        # whose raw track teleported to a background court read 0.0 there even
        # after filtering left a clean main-court trail — starving the
        # shuttle-follow camera on tracks that are actually usable.
        from . import track as _track_mod
        if shuttle:
            scored = _track_mod.filter_shuttle_points(shuttle)
            shuttle_quality = _clamp01(_track_mod.shuttle_track_quality(scored, dur))
        else:
            shuttle_quality = _clamp01(
                rr.get("shuttle_quality", rr.get("shuttle_track_quality", 0.0)))
        player_samples = [b for f in players for b in f.get("boxes", [])]
        player_quality = _clamp01(
            rr.get("player_quality", rr.get("person_quality", _score_samples(player_samples, dur, 2.0))),
            _score_samples(player_samples, dur, 2.0),
        )
        pose_quality = _clamp01(
            rr.get("pose_quality", rr.get("pose_confidence", _score_samples(poses, dur, 2.0))),
            _score_samples(poses, dur, 2.0),
        )
        racquet_boxes = [b for f in racquets for b in f.get("boxes", [])]
        racquet_quality = _clamp01(
            rr.get("racquet_quality", rr.get("racket_quality", rr.get("racquet_confidence",
                                                                       _score_samples(racquet_boxes, dur, 2.0)))),
            _score_samples(racquet_boxes, dur, 2.0),
        )
        candidate_boxes = [b for f in racquet_candidates for b in f.get("boxes", [])]
        racquet_candidate_quality = _clamp01(
            rr.get("racquet_candidate_quality", rr.get("racket_candidate_quality",
                                                       _score_samples(candidate_boxes, dur, 2.0))),
            _score_samples(candidate_boxes, dur, 2.0),
        )
        mask_enabled = bool(shuttle_quality >= config.SHUTTLE_MASK_MIN_QUALITY)
        sampling = _sampling_meta(rr, dur)
        cadence = (sampling.get("effective_sample_fps")
                   or sampling.get("measured_sample_fps")
                   or sampling.get("requested_sample_fps") or 6.0)
        track_health = _track_health(players, poses, cadence)
        raw_tracknet = rr.get("tracknet") if isinstance(rr.get("tracknet"), dict) else {}
        shuttle_engine = "tracknetv3" if (
            raw_tracknet.get("status") == "ok"
            or any(str(p.get("source", "")).lower() == "tracknetv3" for p in shuttle)
        ) else "motion"
        out_rallies.append({
            "rally_index": idx,
            "start": rally.get("start"),
            "end": rally.get("end"),
            "dur": rally.get("dur"),
            "status": "ok" if (shuttle or players or pose_quality or racquet_quality) else "empty",
            "camera_mode": "gpu_pose_shuttle" if player_quality >= 0.35 else "cpu_motion",
            "shuttle_quality": shuttle_quality,
            "player_quality": player_quality,
            "pose_quality": pose_quality,
            "racquet_quality": racquet_quality,
            "racquet_candidate_quality": racquet_candidate_quality,
            "mask_enabled": mask_enabled,
            "shuttle_engine": shuttle_engine,
            "tracknet": {
                "enabled": bool(raw_tracknet.get("enabled")),
                "status": str(raw_tracknet.get("status") or "not_configured"),
                "points": int(_num(raw_tracknet.get("points"), 0)),
                "quality": _clamp01(raw_tracknet.get("quality")),
            },
            "pose_samples": len(poses),
            "racquet_samples": len(racquets),
            "racquet_candidate_samples": len(racquet_candidates),
            "sampling": sampling,
            **({"track_health": track_health} if track_health else {}),
            "shuttle": shuttle,
            "players": players,
            "poses": poses,
            "racquets": racquets,
        })

    def avg(key: str) -> float:
        vals = [r[key] for r in out_rallies if r.get(key, 0) > 0]
        return round(sum(vals) / len(vals), 3) if vals else 0.0

    return {
        "enabled": True,
        "status": "ok",
        "engine": str(raw.get("engine") or raw.get("model") or "runpod"),
        "contract": str(raw.get("contract") or CONTRACT),
        "worker_version": _short_text(raw.get("worker_version"), 80) if raw.get("worker_version") else "",
        "message": str(raw.get("message") or "Runpod vision analysis completed"),
        "models": _model_status(raw),
        "summary": {
            "camera_mode": "gpu_pose_shuttle" if avg("player_quality") >= 0.35 else "cpu_motion",
            "shuttle_engine": "tracknetv3" if any(
                r.get("shuttle_engine") == "tracknetv3" for r in out_rallies
            ) else "motion",
            "shuttle_mask": any(r["mask_enabled"] for r in out_rallies),
            "shuttle_quality": avg("shuttle_quality"),
            "pose_quality": avg("pose_quality"),
            "racquet_quality": avg("racquet_quality"),
            "racquet_candidate_quality": avg("racquet_candidate_quality"),
            "player_quality": avg("player_quality"),
        },
        "rallies": out_rallies,
    }


def _runpod_request(payload: dict, log=print) -> dict:
    endpoint = f"{config.RUNPOD_BASE_URL.rstrip('/')}/v2/{config.RUNPOD_ENDPOINT_ID}"
    headers = {
        "authorization": f"Bearer {config.RUNPOD_API_KEY}",
        "content-type": "application/json",
    }
    body = {
        "input": payload,
        "policy": {
            "executionTimeout": int(config.RUNPOD_TIMEOUT_SEC * 1000),
            "ttl": int((config.RUNPOD_TIMEOUT_SEC + 1800) * 1000),
        },
    }
    r = requests.post(f"{endpoint}/run", headers=headers, json=body, timeout=60)
    r.raise_for_status()
    data = r.json()
    run_id = data.get("id")
    if not run_id:
        raise RuntimeError(f"Runpod did not return a job id: {json.dumps(data)[:300]}")
    # Two SEPARATE budgets: queue time must not eat the execution budget.
    # A busy endpoint can hold a job IN_QUEUE for minutes (cold start, other
    # jobs); the old single deadline (submission + TIMEOUT) let an 8-min queue
    # + 13-min run blow past 20 min and abandon a job that then COMPLETED on
    # the worker — silently downgrading the reel to the CPU camera. Now the
    # execution clock starts only when the job goes RUNNING.
    queued_since = time.time()
    exec_deadline: float | None = None
    last_status = ""
    while True:
        time.sleep(config.RUNPOD_POLL_SEC)
        s = requests.get(f"{endpoint}/status/{run_id}", headers=headers, timeout=60)
        s.raise_for_status()
        status = s.json()
        state = str(status.get("status") or "").upper()
        if state != last_status:
            log(f"Runpod {run_id}: {state or 'UNKNOWN'}")
            last_status = state
        if state == "COMPLETED":
            return status.get("output") or status.get("result") or {}
        if state in {"FAILED", "CANCELLED", "TIMED_OUT"}:
            raise RuntimeError(f"Runpod {run_id} {state}: {json.dumps(status)[:500]}")
        if state == "IN_QUEUE":
            # Fast-fail only a TRULY stalled queue (no workers at all — max=0 or
            # out of credits). A queue behind other jobs keeps waiting up to the
            # queue cap; it does not consume the execution budget.
            if time.time() - queued_since > config.RUNPOD_QUEUE_STALL_SEC:
                try:
                    h = requests.get(f"{endpoint}/health", headers=headers, timeout=20).json()
                    w = h.get("workers", {})
                    active = sum(int(w.get(k, 0)) for k in ("idle", "running", "initializing", "throttled"))
                except Exception:  # noqa: BLE001
                    active = 0
                if active == 0:
                    raise RuntimeError(
                        f"Runpod endpoint has no available workers after "
                        f"{config.RUNPOD_QUEUE_STALL_SEC:.0f}s (max-workers=0 or out of "
                        f"credits). Falling back to CPU camera.")
            if time.time() - queued_since > config.RUNPOD_QUEUE_MAX_SEC:
                raise TimeoutError(
                    f"Runpod job stuck in queue >{config.RUNPOD_QUEUE_MAX_SEC:.0f}s")
        else:
            # RUNNING/IN_PROGRESS: start (once) the execution clock.
            if exec_deadline is None:
                exec_deadline = time.time() + config.RUNPOD_TIMEOUT_SEC
            if time.time() > exec_deadline:
                raise TimeoutError(
                    f"Runpod job ran >{config.RUNPOD_TIMEOUT_SEC:.0f}s after starting")


def analyze(proxy_path: str | Path, workdir: str | Path, sport: str,
            rallies: list[dict], log=print, tasks: list[str] | None = None,
            court_corners: list | None = None) -> dict:
    if not config.RUNPOD_ENDPOINT_ID or not config.RUNPOD_API_KEY:
        return _disabled("RUNPOD_ENDPOINT_ID/RUNPOD_API_KEY not configured")
    tasks = tasks or ["players", "pose", "racquet", "shuttle"]

    workdir = Path(workdir)
    job_id = workdir.name
    # Use whichever proxy the caller passed (TASK-030: a higher-res vision proxy
    # when one was built, else the 480p analysis proxy). Both are signed GPU
    # artifacts served from OUTPUTS/{job_id}/.
    proxy_name = Path(proxy_path).name
    if proxy_name not in artifacts.GPU_ARTIFACTS or not (workdir / proxy_name).exists():
        proxy_name = "proxy.mp4"
    proxy_url = artifacts.url_for(job_id, proxy_name)
    if not proxy_url:
        return _disabled("PUBLIC_BASE_URL and GPU_ARTIFACT_TOKEN are required for Runpod input")

    payload = {
        "contract": CONTRACT,
        "job_id": job_id,
        "sport": sport,
        "proxy_url": proxy_url,
        "proxy_name": Path(proxy_path).name,
        "rallies": [
            {
                "rally_index": i,
                "start": r.get("start"),
                "end": r.get("end"),
                "dur": r.get("dur"),
                "note": r.get("note"),
                "intensity": r.get("intensity"),
            }
            for i, r in enumerate(rallies, 1)
        ],
        "tasks": tasks,
        "pose_model": config.POSE_MODEL_GPU if "pose" in tasks or "players" in tasks else "",
        "return_normalized_coordinates": True,
    }
    if court_corners:
        # Normalized quad (far-L, far-R, near-R, near-L): the worker gates person
        # detections to the court so spectators can't crowd out far players (TASK-031).
        payload["court_corners"] = court_corners
    try:
        log("submitting proxy and rally windows to Runpod")
        raw = _runpod_request(payload, log=log)
        try:
            # TASK-039: persist the worker's verbatim output — GPU minutes are
            # paid for once; canonicalization changes must be re-runnable
            # against stored raws, never against the meter.
            (workdir / "vision_raw.json").write_text(json.dumps(raw))
        except (OSError, TypeError):
            pass
        return _canonicalize(raw, rallies, court_corners=court_corners)
    except Exception as e:  # noqa: BLE001 - GPU enrichment must not kill CPU reel generation.
        log(f"Runpod vision failed, continuing with CPU tracking: {type(e).__name__}: {e}")
        return _failed(f"{type(e).__name__}: {e}")


def rally(analysis: dict | None, index: int) -> dict | None:
    if not analysis:
        return None
    for item in analysis.get("rallies") or []:
        if item.get("rally_index") == index:
            return item
    return None
