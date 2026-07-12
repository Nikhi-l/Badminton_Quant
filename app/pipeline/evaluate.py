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


def _iou(a: dict, b: dict) -> float:
    try:
        ax1, ay1, ax2, ay2 = float(a["x1"]), float(a["y1"]), float(a["x2"]), float(a["y2"])
        bx1, by1, bx2, by2 = float(b["x1"]), float(b["y1"]), float(b["x2"]), float(b["y2"])
    except (KeyError, TypeError, ValueError):
        return 0.0
    ix = max(0.0, min(ax2, bx2) - max(ax1, bx1))
    iy = max(0.0, min(ay2, by2) - max(ay1, by1))
    inter = ix * iy
    if inter <= 0:
        return 0.0
    union = (ax2 - ax1) * (ay2 - ay1) + (bx2 - bx1) * (by2 - by1) - inter
    return inter / union if union > 0 else 0.0


def _tid(obj: dict) -> int | None:
    tid = obj.get("track_id")
    return int(tid) if isinstance(tid, (int, float)) else None


def _prune_rally(vision_rally: dict, allowed: set[int], count: int,
                 iou_min: float = 0.30, max_gap_s: float = 0.8) -> int:
    """Keep the confirmed players' boxes/poses, following them THROUGH tracker
    id churn: when a kept player's id disappears and a new id's box overlaps
    their last kept box (IoU >= ``iou_min`` within ``max_gap_s``), the new id
    is adopted into the keep set — BoT-SORT re-identified the same player
    (TASK-042: the old exact-id filter deleted far doubles players wholesale,
    the evaluator's own notes flagged the churn). Kept boxes are capped at
    ``count`` per frame. Returns the number of removed boxes."""
    allowed = set(allowed)
    removed = 0
    prev_kept: list[dict] = []
    prev_t = None
    for f in vision_rally.get("players") or []:
        boxes = f.get("boxes") or []
        try:
            t = float(f.get("t", 0.0))
        except (TypeError, ValueError):
            t = 0.0
        kept = [b for b in boxes if _tid(b) in allowed]
        kept_ids = {_tid(b) for b in kept}
        if prev_kept and prev_t is not None and t - prev_t <= max_gap_s:
            # boxes whose (old) id vanished this frame are adoption anchors
            anchors = [pb for pb in prev_kept if _tid(pb) not in kept_ids]
            for b in boxes:
                if _tid(b) in allowed or b in kept:
                    continue
                best = max(anchors, key=lambda pb: _iou(pb, b), default=None)
                if best is not None and _iou(best, b) >= iou_min:
                    kept.append(b)
                    anchors.remove(best)
                    if (tid := _tid(b)) is not None:
                        allowed.add(tid)
        if len(kept) > count:
            kept = sorted(kept, key=lambda b: -float(b.get("confidence", 0.0)))[:count]
        removed += len(boxes) - len(kept)
        f["boxes"] = kept
        if kept:
            prev_kept, prev_t = kept, t
    for f in vision_rally.get("poses") or []:
        people = f.get("people") or []
        f["people"] = [p for p in people if _tid(p) in allowed]
    return removed


def apply_verdict(vision: dict, verdict: dict, judged_index: int | None) -> dict:
    """Prune every rally's tracks to the confirmed main-court players.

    The judged rally seeds from exactly ``keep_track_ids``. Track ids reset
    per rally (fresh tracker), so OTHER rallies seed their
    ``main_court_players`` most-persistent ids; id churn is bridged by IoU
    continuation inside :func:`_prune_rally`. Per-rally fail-open guard: a
    prune that leaves under half the confirmed players on court (median
    boxes/frame < count/2 while dropping >50% of boxes) contradicts the
    verdict itself and is reverted. Pure + unit-tested.
    """
    count = int(verdict.get("main_court_players") or 0)
    keep = {int(v) for v in (verdict.get("keep_track_ids") or [])}
    stats = {"applied": False, "removed_boxes": 0, "reverted_rallies": 0}
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
        if not allowed:
            continue
        pframes = rr.get("players") or []
        snap_boxes = [list(f.get("boxes") or []) for f in pframes]
        snap_people = [list(f.get("people") or []) for f in (rr.get("poses") or [])]
        total = sum(len(b) for b in snap_boxes)
        r = _prune_rally(rr, allowed, count)
        kept_counts = sorted(len(f.get("boxes") or []) for f in pframes)
        median_kept = kept_counts[len(kept_counts) // 2] if kept_counts else 0
        if total and r / total > 0.5 and median_kept < count / 2:
            for f, b in zip(pframes, snap_boxes):
                f["boxes"] = b
            for f, ppl in zip(rr.get("poses") or [], snap_people):
                f["people"] = ppl
            stats["reverted_rallies"] += 1
            continue
        removed += r
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
