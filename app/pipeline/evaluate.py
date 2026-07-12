"""Gemini frame evaluator (TASK-041): a second pair of eyes on the tracker.

Owner spec: after tracking, send a few ANNOTATED frames (player boxes + ids
drawn on real video) to Gemini Pro and ask (a) how many people are playing on
the MAIN court, and (b) which drawn boxes are those players — background
courts routinely leak spectators and other games into the tracker. The
verdict prunes stored player/pose tracks BEFORE the camera plans its path,
so background players stop steering the virtual camera and the Studio.

Fail-open by design: no API key, a refused answer, or an implausible verdict
(count outside 2..4, empty keep list) changes nothing and is recorded as
skipped — an evaluator must never sink a job.
"""
from __future__ import annotations

import base64
from pathlib import Path

import cv2

from .. import config
from . import annotate, gemini

PROMPT = """These are frames from one badminton video. Our tracker drew a box
around every person it follows, labelled P<number> (the number is the track id).

The MAIN court is the one the camera is filming — largest in frame, roughly
centered. Other courts/people may be visible behind it.

Answer in JSON:
- "main_court_players": how many people are PLAYING on the main court
  (2 = singles, 4 = doubles). Count players, not referees/spectators.
- "keep_track_ids": the P-numbers of exactly those main-court players.
- "boxes_correct": true if the drawn boxes sit on people (not empty court,
  bags, or posts).
- "notes": one short sentence, e.g. "2v2 doubles; P7 is on the back court".
"""

SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "main_court_players": {"type": "INTEGER"},
        "keep_track_ids": {"type": "ARRAY", "items": {"type": "INTEGER"}},
        "boxes_correct": {"type": "BOOLEAN"},
        "notes": {"type": "STRING"},
    },
    "required": ["main_court_players", "keep_track_ids", "boxes_correct"],
}


def _jpeg_part(rgb) -> dict | None:
    ok, buf = cv2.imencode(".jpg", rgb[:, :, ::-1], [cv2.IMWRITE_JPEG_QUALITY, 82])
    if not ok:
        return None
    return {"inlineData": {"mimeType": "image/jpeg",
                           "data": base64.b64encode(buf.tobytes()).decode()}}


def _persistence(vision_rally: dict) -> dict[int, int]:
    """frames-seen count per worker track_id in one rally."""
    seen: dict[int, int] = {}
    for f in vision_rally.get("players") or []:
        for b in f.get("boxes") or []:
            tid = b.get("track_id")
            if isinstance(tid, (int, float)):
                seen[int(tid)] = seen.get(int(tid), 0) + 1
    return seen


def _prune_rally(vision_rally: dict, allowed: set[int]) -> int:
    """Drop boxes/poses whose track_id is not allowed. Id-less detections drop
    too — with a confirmed player list, an unidentified box is noise. Returns
    the number of removed boxes."""
    removed = 0
    for f in vision_rally.get("players") or []:
        boxes = f.get("boxes") or []
        kept = [b for b in boxes if isinstance(b.get("track_id"), (int, float))
                and int(b["track_id"]) in allowed]
        removed += len(boxes) - len(kept)
        f["boxes"] = kept
    for f in vision_rally.get("poses") or []:
        people = f.get("people") or []
        f["people"] = [p for p in people if isinstance(p.get("track_id"), (int, float))
                       and int(p["track_id"]) in allowed]
    return removed


def apply_verdict(vision: dict, verdict: dict, judged_index: int | None) -> dict:
    """Prune every rally's tracks to the confirmed main-court players.

    The judged rally keeps exactly ``keep_track_ids``. Track ids reset per
    rally (fresh tracker), so OTHER rallies keep their ``main_court_players``
    most-persistent ids — the main-court players are on court the whole rally;
    background leakage is intermittent. Pure + unit-tested.
    """
    count = int(verdict.get("main_court_players") or 0)
    keep = {int(v) for v in (verdict.get("keep_track_ids") or [])}
    stats = {"applied": False, "removed_boxes": 0}
    if not verdict.get("boxes_correct") or not 2 <= count <= 4 or not keep:
        return stats
    removed = 0
    for idx, rr in enumerate(vision.get("rallies") or []):
        if not isinstance(rr, dict):
            continue
        if judged_index is not None and idx == judged_index:
            allowed = keep
        else:
            pers = _persistence(rr)
            allowed = set(sorted(pers, key=lambda k: -pers[k])[:count])
        if allowed:
            removed += _prune_rally(rr, allowed)
    stats.update(applied=True, removed_boxes=removed)
    return stats


def evaluate_players(workdir: str | Path, vision: dict, log=print) -> dict:
    """Run the annotated-frame evaluation and prune tracks in place.

    Returns the evaluation record stored on the result:
    {status, main_court_players?, keep_track_ids?, boxes_correct?, notes?,
     removed_boxes?, model, judged_rally}.
    """
    if not config.GEMINI_EVAL:
        return {"status": "disabled"}
    if not config.GEMINI_API_KEY:
        return {"status": "skipped", "message": "GEMINI_API_KEY not configured"}
    rallies = vision.get("rallies") or []
    scored = [(float((rr or {}).get("player_quality") or 0), i, rr)
              for i, rr in enumerate(rallies) if isinstance(rr, dict) and rr.get("players")]
    if not scored:
        return {"status": "skipped", "message": "no player tracks to evaluate"}
    _, judged_index, judged = max(scored, key=lambda s: (s[0], -s[1]))

    frames = annotate.evaluation_frames(Path(workdir), {"vision": judged})
    parts = [p for p in (_jpeg_part(f) for f in frames) if p]
    if not parts:
        return {"status": "skipped", "message": "no evaluation frames"}
    try:
        log(f"asking {config.PRO_MODEL} to verify player tracking ({len(parts)} frames)")
        text = gemini.generate(config.PRO_MODEL, parts + [{"text": PROMPT}], json_schema=SCHEMA)
        verdict = gemini.parse_json(text)
    except Exception as e:  # noqa: BLE001 - the evaluator must never sink a job
        return {"status": "failed", "message": f"{type(e).__name__}: {e}"}

    stats = apply_verdict(vision, verdict, judged_index)
    out = {
        "status": "ok" if stats["applied"] else "rejected",
        "main_court_players": verdict.get("main_court_players"),
        "keep_track_ids": verdict.get("keep_track_ids"),
        "boxes_correct": verdict.get("boxes_correct"),
        "notes": str(verdict.get("notes") or "")[:160],
        "removed_boxes": stats["removed_boxes"],
        "model": config.PRO_MODEL,
        "judged_rally": judged_index,
    }
    log(f"evaluator: {out['status']} — {out['main_court_players']} players, "
        f"{out['removed_boxes']} background boxes removed")
    return out
