"""Per-job analysis export (TASK-039): one machine-readable match report.

Everything the pipeline learned about a game, exported "along with the video"
as `analysis.json`: the full play/no-play timeline (dead time is labelled, not
implied), per-rally markers (hits with speeds, shuttle flight segments, audio
impact peaks), and per-player court-space movement series (the time-series
representation heatmaps and trajectory analytics build on).

Builders here are PURE — they take the stored result dict plus the public
tracks the API layer already samples (main.py owns those helpers; importing
them here would be circular). The API endpoint caches the built file into the
job's output dir so model outputs are never recomputed to answer analytics
questions.
"""
from __future__ import annotations

from typing import Any

from . import court as court_mod

SCHEMA = "baddy.analysis.v2"   # v2: in-play index on flight segments + wrist series
NO_PLAY_MIN_S = 1.0        # a gap shorter than this is boundary noise, not rest
FLIGHT_GAP_S = 0.25        # matches the public shuttle-track segment contract
ANKLE_MIN_CONF = 0.15      # matches the pose smoother/render gate


def _num(v: Any, default: float = 0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def timeline_segments(all_rallies: list, selected: list, duration: float) -> list[dict]:
    """Full-video timeline: every detected rally + explicit no_play gaps.

    ``selected`` are the reel rallies (carry ``src_start`` when trimmed);
    a detected rally that wasn't selected is still play — it's just not in
    the reel. Gaps ≥ NO_PLAY_MIN_S between play segments are labelled
    ``no_play`` so "nothing is happening here" is data, not absence of data.
    """
    sel_keys = set()
    for r in selected or []:
        sel_keys.add(round(_num(r.get("src_start", r.get("start"))), 2))
    segs = []
    for r in sorted(all_rallies or [], key=lambda x: _num(x.get("start"))):
        s, e = _num(r.get("start")), _num(r.get("end"))
        if e <= s:
            continue
        segs.append({
            "kind": "rally",
            "start": round(s, 2), "end": round(e, 2), "dur": round(e - s, 2),
            "intensity": int(_num(r.get("intensity"), 3)),
            "note": str(r.get("note") or "")[:80],
            "in_reel": round(s, 2) in sel_keys,
        })
    out = []
    cursor = 0.0
    for seg in segs:
        if seg["start"] - cursor >= NO_PLAY_MIN_S:
            out.append({"kind": "no_play", "start": round(cursor, 2),
                        "end": seg["start"], "dur": round(seg["start"] - cursor, 2)})
        out.append(seg)
        cursor = max(cursor, seg["end"])
    if duration - cursor >= NO_PLAY_MIN_S:
        out.append({"kind": "no_play", "start": round(cursor, 2),
                    "end": round(duration, 2), "dur": round(duration - cursor, 2)})
    return out


# In-play speed gate (user spec 2026-07-12): the shuttle is IN PLAY when it is
# airborne AND moving fast; a shuttle carried in a hand or drifting near a
# body tracks slowly. Units are normalized-frame/s (the frame spans ~14 m of
# court, so 0.15/s ≈ 2 m/s — well above carry/walk speed, well below any real
# stroke). Court-plane m/s is deliberately NOT computed here: projecting an
# AIRBORNE shuttle through the ground homography is parallax-wrong; accurate
# speeds come from the 3D layer.
IN_PLAY_MIN_SPEED = 0.15
IN_PLAY_MIN_DUR_S = 0.4


def flight_segments(shuttle_pts: list, gap_s: float = FLIGHT_GAP_S,
                    min_conf: float = 0.3) -> list[dict]:
    """Contiguous observed-shuttle-flight windows with kinematics — the
    in-play index (user spec): each segment carries median/max speed and an
    ``in_play`` verdict (fast enough to be a live shuttle, long enough to be
    an exchange). Slow segments (shuttle carried to the service line) and
    static ones (already removed upstream by the tracking filter) are the
    false positives the speed gate exists to reject.
    """
    pts = sorted(((_num(p.get("t")), _num(p.get("x")), _num(p.get("y")))
                  for p in (shuttle_pts or [])
                  if isinstance(p, dict) and _num(p.get("confidence"), 1.0) >= min_conf),
                 key=lambda r: r[0])
    segs: list[list[tuple[float, float, float]]] = []
    for pt in pts:
        if segs and pt[0] - segs[-1][-1][0] <= gap_s:
            segs[-1].append(pt)
        else:
            segs.append([pt])
    out = []
    for seg in segs:
        if len(seg) < 3:
            continue
        speeds = []
        for (t0, x0, y0), (t1, x1, y1) in zip(seg, seg[1:]):
            dt = t1 - t0
            if dt > 1e-3:
                speeds.append(((x1 - x0) ** 2 + (y1 - y0) ** 2) ** 0.5 / dt)
        if not speeds:
            continue
        speeds.sort()
        med = speeds[len(speeds) // 2]
        dur = seg[-1][0] - seg[0][0]
        out.append({
            "start": round(seg[0][0], 2), "end": round(seg[-1][0], 2),
            "points": len(seg),
            "median_speed": round(med, 3),          # normalized-frame units /s
            "max_speed": round(speeds[-1], 3),
            "in_play": bool(med >= IN_PLAY_MIN_SPEED and dur >= IN_PLAY_MIN_DUR_S),
        })
    return out


def wrist_series(pose_track: list, min_conf: float = ANKLE_MIN_CONF) -> dict[str, list[dict]]:
    """Per-player wrist time series (COCO 9/10, image-normalized): the raw
    signal for stroke/hit detection — a hit is a wrist-speed spike coinciding
    with a shuttle direction change and an audio impact (user spec: save the
    pose movement so the hit algorithm has data to run on)."""
    out: dict[str, list[dict]] = {}
    for frame in pose_track or []:
        t = round(_num(frame.get("t")), 2)
        for person in frame.get("people") or []:
            kps = person.get("keypoints") or []
            if len(kps) < 11 or person.get("id") is None:
                continue
            entry: dict = {"t": t}
            for key, idx in (("l", 9), ("r", 10)):
                kp = kps[idx]
                if _num(kp.get("confidence")) >= min_conf:
                    entry[key] = [round(_num(kp.get("x")), 4), round(_num(kp.get("y")), 4)]
            if len(entry) > 1:
                out.setdefault(str(int(person["id"])), []).append(entry)
    return out


def rally_hits(rally_3d: dict | None) -> list[dict]:
    """Hit markers from accepted 3D shots (each shot starts at a hit)."""
    if not isinstance(rally_3d, dict) or rally_3d.get("status") != "ok":
        return []
    hits = []
    for shot in rally_3d.get("shots") or []:
        h = {"t": _num(shot.get("t0")), "speed_kmh": _num(shot.get("speed_kmh"))}
        if shot.get("speed_at_net_kmh") is not None:
            h["speed_at_net_kmh"] = _num(shot.get("speed_at_net_kmh"))
        hits.append(h)
    return hits


def peaks_in_window(peaks: list, start: float, end: float) -> list[dict]:
    return [p for p in (peaks or [])
            if isinstance(p, dict) and start <= _num(p.get("t")) <= end]


def court_movement(players_track: list, pose_track: list,
                   homography: list | None) -> dict[str, list[dict]]:
    """Per-player court-space movement series: {player_id: [{t, x, y, src}]}.

    Positions are meters on the court plane (x across 0–6.1, y along 0–13.4).
    The ground contact is what projects correctly through the homography, so
    ankles (COCO 15/16 midpoint) are preferred — the "leg movement"
    representation — with the box foot-center as fallback when pose is
    missing or weak. Off-court projections are kept (players do stand outside
    the lines); consumers clip as needed.
    """
    if not homography:
        return {}
    ankles: dict[tuple[float, int], tuple[float, float]] = {}
    for frame in pose_track or []:
        t = round(_num(frame.get("t")), 2)
        for person in frame.get("people") or []:
            kps = person.get("keypoints") or []
            if len(kps) < 17 or person.get("id") is None:
                continue
            la, ra = kps[15], kps[16]
            if (_num(la.get("confidence")) >= ANKLE_MIN_CONF
                    and _num(ra.get("confidence")) >= ANKLE_MIN_CONF):
                ankles[(t, int(person["id"]))] = (
                    (_num(la.get("x")) + _num(ra.get("x"))) / 2,
                    (_num(la.get("y")) + _num(ra.get("y"))) / 2,
                )
    series: dict[str, list[dict]] = {}
    for frame in players_track or []:
        t = round(_num(frame.get("t")), 2)
        for box in frame.get("boxes") or []:
            if box.get("id") is None:
                continue
            pid = int(box["id"])
            pt = ankles.get((t, pid))
            src = "ankles" if pt else "box_foot"
            if pt is None:
                pt = (_num(box.get("x")), _num(box.get("y")) + _num(box.get("h")) / 2)
            try:
                cx, cy = court_mod.project(homography, pt[0], pt[1])
            except Exception:  # noqa: BLE001 - degenerate homography row
                continue
            series.setdefault(str(pid), []).append(
                {"t": t, "x": round(float(cx), 2), "y": round(float(cy), 2), "src": src})
    return series


def build_analysis(result: dict, *, job_id: str, per_rally_tracks: list[dict],
                   generated_at: str) -> dict:
    """Assemble analysis.json from a stored result + pre-sampled public tracks.

    ``per_rally_tracks[i]`` = {"players_track": [...], "pose_track": [...]}
    aligned with ``result["rallies"]`` (the API layer samples them with the
    same code the Studio uses, so ids match what the user sees).
    """
    # result["duration"] is the REEL length; the timeline lives on the SOURCE
    # clock (rally times are source times), so prefer source.duration.
    src = result.get("source") if isinstance(result.get("source"), dict) else {}
    duration = _num(src.get("duration"), _num(result.get("duration")))
    rallies = result.get("rallies") or []
    audio = result.get("audio") if isinstance(result.get("audio"), dict) else {}
    court_info = result.get("court") if isinstance(result.get("court"), dict) else {}
    homography = court_info.get("homography") if court_info.get("status") == "ok" else None
    peaks = audio.get("peaks") or []

    out_rallies = []
    for i, rr in enumerate(rallies):
        vision = rr.get("vision") or {}
        tracks = per_rally_tracks[i] if i < len(per_rally_tracks) else {}
        start = _num(rr.get("src_start", rr.get("start")))
        end = _num(rr.get("end"))
        flight = flight_segments(vision.get("shuttle"))
        entry = {
            "index": i,
            "start": round(start, 2), "end": round(end, 2),
            "dur": _num(rr.get("dur")),
            "intensity": int(_num(rr.get("intensity"), 3)),
            "note": str(rr.get("note") or "")[:80],
            # The in-play index (user spec 2026-07-12): shuttle observed
            # flying AND fast. Everything else inside the rally window is
            # walking, pickup, serve prep — measurable dead time.
            "in_play": [{"start": s["start"], "end": s["end"]}
                        for s in flight if s["in_play"]],
            "markers": {
                "hits": rally_hits(rr.get("rally_3d")),
                "shuttle_flight": flight,
                "audio_peaks": peaks_in_window(peaks, start - 1.0, end + 1.0),
            },
            "quality": {k: vision.get(k) for k in
                        ("shuttle_quality", "player_quality", "pose_quality") if k in vision},
            "players_court_m": court_movement(tracks.get("players_track") or [],
                                              tracks.get("pose_track") or [], homography),
            "wrists": wrist_series(tracks.get("pose_track") or []),
        }
        out_rallies.append(entry)

    play_s = sum(r["dur"] for r in out_rallies)
    return {
        "schema": SCHEMA,
        "job_id": job_id,
        "generated_at": generated_at,
        "sport": result.get("sport"),
        "duration_s": round(duration, 2),
        "court": {
            "status": court_info.get("status", "unknown"),
            "source": court_info.get("source"),
            "width_m": court_mod.COURT_WIDTH_M,
            "length_m": court_mod.COURT_LENGTH_M,
            "calibrated": bool(homography),
        },
        "summary": {
            "rallies_found": int(_num(result.get("n_rallies_found"),
                                      len(result.get("all_rallies") or []))),
            "rallies_in_reel": len(out_rallies),
            "play_time_s": round(play_s, 1),
            "no_play_time_s": round(max(0.0, duration - sum(
                _num(r.get("dur")) for r in (result.get("all_rallies") or []))), 1),
            "audio": audio.get("status", "not_analyzed"),
            "audio_peaks": len(peaks),
        },
        "timeline": timeline_segments(result.get("all_rallies") or [], rallies, duration),
        "rallies": out_rallies,
        "audio": {"status": audio.get("status", "not_analyzed"),
                  "hop_s": audio.get("hop_s"), "series": audio.get("series") or [],
                  "peaks": peaks},
    }
