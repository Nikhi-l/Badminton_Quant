"""Rally segmentation: upload the proxy video to Gemini and get rally time ranges back."""
from pathlib import Path

from .. import config
from . import gemini

PROMPT = """You are analyzing a racket/paddle sport game (badminton, pickleball, tennis,
padel, table tennis, squash...) recorded from a single fixed camera.

First identify which sport it is. Be careful with first-person (POV) footage:
pickleball is played standing on a court with a low net and a perforated plastic ball —
table tennis is played over a small table. Look at the playing surface and net height.

Then identify EVERY rally in the video. A rally STARTS at the moment the serve is struck
and ENDS when the ball/shuttle goes out of play (hits the floor twice in pickleball/tennis
terms — i.e. the point is clearly over, lands in the net, goes out) or play clearly stops
(players walk around, retrieve the ball, talk, prepare to serve).

Strictly exclude all dead time between rallies.

Return JSON:
- "sport": the sport you identified, lowercase, e.g. "pickleball"
- "rallies": one object per rally:
  - "start": rally start as "m:ss" (round down to the whole second)
  - "end": rally end as "m:ss"
  - "intensity": integer 1-5, where 5 = spectacular long rally (smashes, dives, fast exchanges)
  - "note": short description, max 8 words, e.g. "long rally ending in cross-court smash"

Cover the entire video from 0:00 to the end. If unsure about an exact boundary, widen it by one second.
"""

SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "sport": {"type": "STRING"},
        "rallies": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "start": {"type": "STRING"},
                    "end": {"type": "STRING"},
                    "intensity": {"type": "INTEGER"},
                    "note": {"type": "STRING"},
                },
                "required": ["start", "end"],
            },
        },
    },
    "required": ["sport", "rallies"],
}


def _to_sec(ts) -> float:
    if isinstance(ts, (int, float)):
        return float(ts)
    parts = [p for p in str(ts).strip().split(":") if p != ""]
    sec = 0.0
    for p in parts:
        sec = sec * 60 + float(p)
    return sec


def _clean(raw: list, duration: float) -> list[dict]:
    rallies = []
    for r in raw:
        try:
            s, e = _to_sec(r["start"]), _to_sec(r["end"])
        except (KeyError, ValueError):
            continue
        s, e = max(0.0, s), min(float(duration), e)
        if e - s < config.MIN_RALLY_SEC:
            continue
        rallies.append({
            "start": s, "end": e, "dur": round(e - s, 2),
            "intensity": int(r.get("intensity") or 3),
            "note": str(r.get("note") or "")[:80],
        })
    rallies.sort(key=lambda r: r["start"])
    merged: list[dict] = []
    for r in rallies:
        if merged and r["start"] < merged[-1]["end"] - 0.5:
            merged[-1]["end"] = max(merged[-1]["end"], r["end"])
            merged[-1]["dur"] = round(merged[-1]["end"] - merged[-1]["start"], 2)
            merged[-1]["intensity"] = max(merged[-1]["intensity"], r["intensity"])
        else:
            merged.append(r)
    return merged


def segment(proxy_path: str | Path, duration: float, log=print) -> tuple[str, list[dict]]:
    """Returns (sport, rallies sorted by start time)."""
    log(f"uploading proxy to Gemini Files API ({Path(proxy_path).stat().st_size // 1_000_000} MB)")
    file = gemini.upload_file(proxy_path, mime="video/mp4")
    file = gemini.wait_active(file)
    part_video = {"fileData": {"fileUri": file["uri"], "mimeType": "video/mp4"}}

    for model in (config.SEGMENT_MODEL, config.PRO_MODEL):
        try:
            log(f"asking {model} for rally boundaries")
            text = gemini.generate(model, [part_video, {"text": PROMPT}], json_schema=SCHEMA)
            data = gemini.parse_json(text)
            sport = str(data.get("sport") or "racket sport").lower()[:30]
            rallies = _clean(data.get("rallies") or [], duration)
            if rallies:
                log(f"{model}: {sport}, {len(rallies)} rallies found")
                return sport, rallies
            log(f"{model} returned no usable rallies, trying next model")
        except gemini.GeminiError as e:
            log(f"{model} failed: {e}")
    raise gemini.GeminiError("rally segmentation failed on all models")


def select_for_reel(rallies: list[dict]) -> list[dict]:
    """Longest rallies first (what viewers want), capped by count and total reel length."""
    ranked = sorted(rallies, key=lambda r: (r["dur"], r["intensity"]), reverse=True)
    picked: list[dict] = []
    total = 0.0
    for r in ranked:
        clip = r["dur"] + config.PAD_BEFORE + config.PAD_AFTER
        if len(picked) >= config.TOP_RALLIES:
            break
        if total + clip > config.MAX_REEL_SEC and picked:
            continue
        picked.append(r)
        total += clip
    return picked
