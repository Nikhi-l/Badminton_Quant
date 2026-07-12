"""Rally segmentation: upload the proxy video to Gemini and get rally time ranges back."""
import json
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


def _audio_evidence(peaks: list | None, limit: int = 120) -> str:
    """Impact-peak timestamps as prompt evidence (TASK-042, owner architecture:
    signals extracted first, the model reasons WITH them). Empty string when
    the signal is too thin to be worth anchoring on."""
    ts = []
    for p in peaks or []:
        try:
            ts.append(float(p["t"]))
        except (KeyError, TypeError, ValueError):
            continue
    if len(ts) < 10:
        return ""
    shown = ", ".join(f"{t:.0f}" for t in sorted(ts)[:limit])
    return (
        "\nMicrophone analysis of this exact video found racket-impact-like "
        f"sound transients at these times (seconds): {shown}.\n"
        "Real rallies contain clusters of these impacts; a stretch of several "
        "seconds with none is almost always dead time (walking, retrieving the "
        "shuttle, preparing to serve). Anchor your rally boundaries on this "
        "evidence — do NOT return rallies that tile the whole video back-to-back.\n"
    )


def segment(proxy_path: str | Path, duration: float, log=print,
            save_raw: Path | None = None,
            audio_peaks: list | None = None) -> tuple[str, list[dict]]:
    """Returns (sport, rallies sorted by start time).

    ``save_raw`` persists the model's verbatim parsed response next to the
    job's other artifacts (TASK-039): rally boundaries are model output paid
    for once — audits and boundary-algorithm work must never need a re-run.
    ``audio_peaks`` (TASK-042) are measured impact transients passed to the
    model as boundary evidence.
    """
    log(f"uploading proxy to Gemini Files API ({Path(proxy_path).stat().st_size // 1_000_000} MB)")
    file = gemini.upload_file(proxy_path, mime="video/mp4")
    file = gemini.wait_active(file)
    part_video = {"fileData": {"fileUri": file["uri"], "mimeType": "video/mp4"}}
    prompt = PROMPT + _audio_evidence(audio_peaks)

    for model in (config.SEGMENT_MODEL, config.PRO_MODEL):
        try:
            log(f"asking {model} for rally boundaries")
            text = gemini.generate(model, [part_video, {"text": prompt}], json_schema=SCHEMA)
            data = gemini.parse_json(text)
            if save_raw is not None:
                try:
                    save_raw.write_text(json.dumps({"model": model, "response": data}, indent=2))
                except OSError:
                    pass
            sport = str(data.get("sport") or "racket sport").lower()[:30]
            rallies = _clean(data.get("rallies") or [], duration)
            if rallies:
                log(f"{model}: {sport}, {len(rallies)} rallies found")
                return sport, rallies
            log(f"{model} returned no usable rallies, trying next model")
        except gemini.GeminiError as e:
            log(f"{model} failed: {e}")
    raise gemini.GeminiError("rally segmentation failed on all models")


def refine_with_audio(rallies: list[dict], peaks: list | None, duration: float,
                      log=print, coverage_max: float = 0.70, min_peaks: int = 2,
                      split_gap_s: float = 5.0, pad_before: float = 2.0,
                      pad_after: float = 2.0) -> list[dict]:
    """Deterministic audio cross-check of Gemini rally boundaries (TASK-042).

    Owner architecture: signals first, the model's output verified against
    them. On owner footage Gemini tiled the whole video as 18 back-to-back
    "rallies" (257s of a 270s video marked as play) — badminton always has
    dead time between rallies. Racket impacts are loud transients, so when
    the segmentation is implausibly wall-to-wall (play coverage above
    ``coverage_max``), each rally window is shrunk to its impact cluster,
    windows without ``min_peaks`` impacts are dropped as fake, and windows
    whose cluster contains a silent stretch over ``split_gap_s`` are SPLIT —
    they are several real rallies merged with their dead time.

    Shrink-only: refined windows always lie inside the original ones. Fail
    open (input returned unchanged) when audio is too thin to judge
    (under 10 peaks) or the segmentation already looks healthy.
    """
    ts = []
    for p in peaks or []:
        try:
            ts.append(float(p["t"]))
        except (KeyError, TypeError, ValueError):
            continue
    ts.sort()
    if len(ts) < 10 or not rallies or duration <= 0:
        return rallies
    coverage = sum(r["end"] - r["start"] for r in rallies) / duration
    if coverage <= coverage_max:
        return rallies

    refined: list[dict] = []
    dropped = 0
    for r in rallies:
        inside = [t for t in ts if r["start"] - 0.5 <= t <= r["end"] + 0.5]
        if len(inside) < min_peaks:
            dropped += 1
            continue
        clusters: list[list[float]] = [[inside[0]]]
        for t in inside[1:]:
            if t - clusters[-1][-1] > split_gap_s:
                clusters.append([t])
            else:
                clusters[-1].append(t)
        for c in clusters:
            if len(c) < min_peaks:
                continue
            s = max(r["start"], c[0] - pad_before)
            e = min(r["end"], c[-1] + pad_after)
            if e - s < config.MIN_RALLY_SEC:
                continue
            refined.append({**r, "start": round(s, 2), "end": round(e, 2),
                            "dur": round(e - s, 2), "audio_hits": len(c)})
    if not refined:      # audio contradicting EVERY window means the audio is wrong
        return rallies
    refined.sort(key=lambda r: r["start"])
    kept_cov = sum(r["dur"] for r in refined) / duration
    log(f"audio check: segmentation covered {coverage:.0%} of the video "
        f"(implausible) — refined to {len(refined)} rallies at {kept_cov:.0%} "
        f"coverage, {dropped} window(s) had no impact evidence")
    return refined


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
