"""Grounded Gemini coach notes from measured vision metadata."""
from __future__ import annotations

import base64
import json
import subprocess
from pathlib import Path
from typing import Any

from .. import config
from . import gemini

CONTRACT = "baddy.coach.v1"

SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "headline": {"type": "STRING"},
        "confidence": {"type": "NUMBER"},
        "strengths": {"type": "ARRAY", "items": {"type": "STRING"}},
        "work_on": {"type": "ARRAY", "items": {"type": "STRING"}},
        "moments": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "rally_index": {"type": "INTEGER"},
                    "label": {"type": "STRING"},
                    "reason": {"type": "STRING"},
                },
                "required": ["rally_index", "label", "reason"],
            },
        },
        "caveats": {"type": "ARRAY", "items": {"type": "STRING"}},
    },
    "required": ["headline", "confidence", "strengths", "work_on", "moments", "caveats"],
}


PROMPT = """You are Baddy's badminton highlight coach.

You receive measured computer-vision metadata, not enough evidence for free-form
video diagnosis. You may also receive a few representative rally frames. Convert
the metadata and frames into concise, mobile-friendly coaching notes for the
player reviewing a generated highlight reel.

Rules:
- Only make claims supported by the metadata.
- Treat frame images as supporting evidence for visible context only; they do not
  override low measured quality scores.
- Use quality_summary.racquet_evidence to decide racquet claims. "measured"
  means racquet boxes were detected; "pose_guided_candidate" means a weak
  wrist-adjacent line candidate exists; "frame_context_only" means frames may
  show visible racquet context but there are no measured racquet boxes.
- Do not invent stroke types, injuries, intent, grip, contact point, or tactical
  choices that are not present in the rally notes or measurements.
- If pose quality is low, avoid detailed body-mechanics advice.
- If racquet_evidence.mode is not "measured", avoid grip, swing path,
  contact-point, racquet-speed, and stroke-classification advice. You may only
  mention whether racquet context is visible in the provided frames.
- If shuttle quality is low, avoid shuttle-flight, placement, spin, or trajectory
  coaching.
- Use careful language such as "tracking suggests" or "the selected rallies show"
  when the signal is partial.
- Keep every string short enough for a compact mobile UI.
- Return JSON only.
"""


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


def _short(text: Any, limit: int) -> str:
    s = " ".join(str(text or "").split())
    if len(s) <= limit:
        return s
    return s[: max(0, limit - 1)].rstrip() + "..."


def _texts(values: Any, *, limit: int, chars: int) -> list[str]:
    if not isinstance(values, list):
        return []
    out = []
    for value in values:
        text = _short(value, chars)
        if text and text not in out:
            out.append(text)
        if len(out) >= limit:
            break
    return out


def _disabled(message: str) -> dict:
    return {
        "enabled": False,
        "status": "disabled",
        "engine": config.COACH_MODEL,
        "contract": CONTRACT,
        "message": message,
    }


def _skipped(message: str, summary: dict | None = None) -> dict:
    return {
        "enabled": True,
        "status": "skipped",
        "engine": config.COACH_MODEL,
        "contract": CONTRACT,
        "message": message,
        "summary": summary or {},
    }


def _failed(message: str, summary: dict | None = None) -> dict:
    return {
        "enabled": True,
        "status": "failed",
        "engine": config.COACH_MODEL,
        "contract": CONTRACT,
        "message": message,
        "summary": summary or {},
    }


def _quality_summary(vision: dict | None) -> dict:
    raw = ((vision or {}).get("summary") or {}) if isinstance(vision, dict) else {}
    player = _clamp01(raw.get("player_quality"))
    pose = _clamp01(raw.get("pose_quality"))
    racquet = _clamp01(raw.get("racquet_quality"))
    racquet_candidate = _clamp01(raw.get("racquet_candidate_quality"))
    shuttle = _clamp01(raw.get("shuttle_quality"))
    confidence = round(min(1.0, player * 0.5 + pose * 0.25 + racquet * 0.15 + shuttle * 0.1), 3)
    return {
        "player_quality": player,
        "pose_quality": pose,
        "racquet_quality": racquet,
        "racquet_candidate_quality": racquet_candidate,
        "shuttle_quality": shuttle,
        "shuttle_mask": bool(raw.get("shuttle_mask")),
        "tracking_confidence": confidence,
    }


def _racquet_evidence(summary: dict, rallies: list[dict], frame_evidence: list[dict]) -> dict:
    measured_samples = sum(
        int(_num(((r.get("vision") or {}).get("racquet_samples")), 0))
        for r in rallies
        if isinstance(r, dict)
    )
    measured_quality = _clamp01(summary.get("racquet_quality"))
    candidate_samples = sum(
        int(_num(((r.get("vision") or {}).get("racquet_candidate_samples")), 0))
        for r in rallies
        if isinstance(r, dict)
    )
    candidate_quality = _clamp01(summary.get("racquet_candidate_quality"))
    frame_score = min(1.0, len(frame_evidence) / max(1, min(config.COACH_FRAME_COUNT, len(rallies) or 1)))
    visual_context = 0.0
    if frame_evidence or candidate_quality > 0:
        visual_context = min(
            0.55,
            _clamp01(summary.get("pose_quality")) * 0.38
            + _clamp01(summary.get("player_quality")) * 0.22
            + _clamp01(summary.get("shuttle_quality")) * 0.20
            + max(frame_score, candidate_quality) * 0.20,
        )

    if measured_samples > 0 or measured_quality >= 0.45:
        mode = "measured"
        allowed = [
            "racquet presence from measured boxes",
            "limited swing/contact observations when visible and consistent with measurements",
        ]
        forbidden = ["exact racquet speed"]
    elif candidate_samples > 0 or candidate_quality > 0:
        mode = "pose_guided_candidate"
        allowed = [
            "racquet candidate regions from pose-guided line evidence",
            "visible racquet context only",
        ]
        forbidden = ["grip", "swing path", "contact point", "racquet speed", "stroke classification"]
    elif frame_evidence:
        mode = "frame_context_only"
        allowed = [
            "racquet visibility in representative frames only",
            "broad movement timing when supported by pose and shuttle signals",
        ]
        forbidden = ["grip", "swing path", "contact point", "racquet speed", "stroke classification"]
    else:
        mode = "none"
        allowed = ["no racquet-specific claims"]
        forbidden = ["grip", "swing path", "contact point", "racquet speed", "stroke classification"]

    return {
        "mode": mode,
        "measured_quality": measured_quality,
        "measured_samples": measured_samples,
        "candidate_quality": candidate_quality,
        "candidate_samples": candidate_samples,
        "visual_context_quality": round(_clamp01(visual_context), 3),
        "allowed_claims": allowed,
        "forbidden_claims": forbidden,
    }


def _build_payload(sport: str, vision: dict, rendered: list[dict], all_rallies: list[dict]) -> dict:
    summary = _quality_summary(vision)
    rallies = []
    for idx, rally in enumerate(rendered, 1):
        rv = rally.get("vision") or {}
        shuttle = rv.get("shuttle") or []
        players = rv.get("players") or []
        rallies.append({
            "rally_index": idx,
            "source_start_sec": round(_num(rally.get("src_start", rally.get("start"))), 2),
            "rendered_duration_sec": round(_num(rally.get("clip_dur", rally.get("dur"))), 2),
            "rally_duration_sec": round(_num(rally.get("dur")), 2),
            "intensity": int(_num(rally.get("intensity"), 3)),
            "note": _short(rally.get("note"), 80),
            "trimmed": bool(rally.get("trimmed")),
            "vision": {
                "camera_mode": rv.get("camera_mode"),
                "player_quality": _clamp01(rv.get("player_quality")),
                "pose_quality": _clamp01(rv.get("pose_quality")),
                "racquet_quality": _clamp01(rv.get("racquet_quality")),
                "racquet_candidate_quality": _clamp01(rv.get("racquet_candidate_quality")),
                "shuttle_quality": _clamp01(rv.get("shuttle_quality")),
                "mask_enabled": bool(rv.get("mask_enabled")),
                "shuttle_engine": rv.get("shuttle_engine") or "motion",
                "tracknet": rv.get("tracknet") or {},
                "player_samples": len(players),
                "pose_samples": int(_num(rv.get("pose_samples"), 0)),
                "racquet_samples": int(_num(rv.get("racquet_samples"), 0)),
                "racquet_candidate_samples": int(_num(rv.get("racquet_candidate_samples"), 0)),
                "shuttle_samples": len(shuttle),
            },
        })
    return {
        "sport": _short(sport or "badminton", 30),
        "reel": {
            "rallies_found": len(all_rallies or []),
            "rallies_used": len(rendered or []),
            "total_rally_duration_sec": round(sum(_num(r.get("dur")) for r in rendered), 2),
            "selection": "longest rallies first",
        },
        "quality_summary": summary,
        "measurement_caveats": [],
        "rallies": rallies,
    }


def _measurement_caveats(summary: dict) -> list[str]:
    caveats = []
    if summary["pose_quality"] < 0.45:
        caveats.append("Pose quality is low, so form notes must stay conservative.")
    racquet_evidence = summary.get("racquet_evidence") or {}
    if racquet_evidence.get("mode") == "pose_guided_candidate":
        caveats.append("Racquet candidates are pose-guided and need Gemini/frame confirmation.")
    elif racquet_evidence.get("mode") == "frame_context_only":
        caveats.append("No measured racquet boxes yet; racquet notes are limited to visible frame context.")
    elif summary["racquet_quality"] < 0.45:
        caveats.append("Racquet quality is low, so swing/contact notes are unreliable.")
    if summary["shuttle_quality"] < config.SHUTTLE_MASK_MIN_QUALITY:
        caveats.append("Shuttle tracking is not reliable enough for flight-path coaching.")
    if summary["player_quality"] < 0.35:
        caveats.append("Player boxes are sparse, so movement coverage may be incomplete.")
    return caveats


def _clean_moments(values: Any, *, max_rally: int) -> list[dict]:
    if not isinstance(values, list):
        return []
    out = []
    for item in values:
        if not isinstance(item, dict):
            continue
        idx = int(_num(item.get("rally_index"), 0))
        if idx < 1 or idx > max_rally:
            continue
        label = _short(item.get("label"), 42)
        reason = _short(item.get("reason"), 90)
        if label and reason:
            out.append({"rally_index": idx, "label": label, "reason": reason})
        if len(out) >= 3:
            break
    return out


def _frame_time(rally: dict) -> float:
    start = _num(rally.get("start", rally.get("src_start")))
    end = _num(rally.get("end"), start + _num(rally.get("dur"), rally.get("clip_dur")))
    if end <= start:
        end = start + _num(rally.get("clip_dur", rally.get("dur")))
    return max(0.0, start + max(0.0, end - start) * 0.5)


def _grab_jpeg(path: str | Path, t: float) -> bytes:
    out = subprocess.run(
        ["ffmpeg", "-v", "error", "-ss", f"{t:.2f}", "-i", str(path),
         "-frames:v", "1", "-vf", f"scale=-2:{config.COACH_FRAME_HEIGHT},format=yuvj420p",
         "-q:v", "6", "-strict", "unofficial", "-f", "image2pipe", "-c:v", "mjpeg", "-"],
        capture_output=True, check=True)
    return out.stdout


def _frame_parts(proxy_path: str | Path | None, rendered: list[dict], log=print) -> tuple[list[dict], list[dict]]:
    if not proxy_path or config.COACH_FRAME_COUNT <= 0:
        return [], []
    path = Path(proxy_path)
    if not path.exists():
        return [], []

    parts: list[dict] = []
    evidence: list[dict] = []
    # Prefer rallies with the strongest measured action context; Gemini sees
    # fewer, better frames instead of a noisy contact sheet.
    ranked = sorted(
        enumerate(rendered, 1),
        key=lambda item: _frame_rank(item[1]),
        reverse=True,
    )
    for idx, rally in ranked[: max(0, config.COACH_FRAME_COUNT)]:
        t = _frame_time(rally)
        try:
            jpg = _grab_jpeg(path, t)
        except (subprocess.CalledProcessError, OSError) as exc:
            log(f"coach frame extraction skipped for rally {idx}: {type(exc).__name__}")
            continue
        evidence.append({"rally_index": idx, "source_time_sec": round(t, 2)})
        parts.append({"text": f"Representative frame: rally {idx}, source time {t:.2f}s"})
        parts.append({"inlineData": {"mimeType": "image/jpeg",
                                     "data": base64.b64encode(jpg).decode()}})
    return parts, evidence


def _frame_rank(rally: dict) -> tuple[float, float]:
    rv = rally.get("vision") or {}
    tracknet = rv.get("tracknet") if isinstance(rv.get("tracknet"), dict) else {}
    tracknet_bonus = 0.08 if (rv.get("shuttle_engine") == "tracknetv3" or tracknet.get("status") == "ok") else 0.0
    mask_bonus = 0.04 if rv.get("mask_enabled") else 0.0
    score = (
        _clamp01(rv.get("player_quality")) * 0.30
        + _clamp01(rv.get("pose_quality")) * 0.30
        + _clamp01(rv.get("shuttle_quality")) * 0.22
        + max(_clamp01(rv.get("racquet_quality")),
              _clamp01(rv.get("racquet_candidate_quality")) * 0.6) * 0.10
        + tracknet_bonus
        + mask_bonus
    )
    return (score, _num(rally.get("dur")))


def _sanitize(data: dict, payload: dict) -> dict:
    summary = payload["quality_summary"]
    model_conf = _clamp01(data.get("confidence"), summary["tracking_confidence"])
    confidence = round(min(model_conf, max(0.2, summary["tracking_confidence"])), 2)
    strengths = _texts(data.get("strengths"), limit=2, chars=92)
    work_on = _texts(data.get("work_on"), limit=2, chars=92)
    caveats = _texts(data.get("caveats"), limit=2, chars=110)
    for c in payload.get("measurement_caveats") or []:
        if c not in caveats and len(caveats) < 3:
            caveats.append(c)
    racquet_evidence = summary.get("racquet_evidence") or {}
    if racquet_evidence.get("mode") == "pose_guided_candidate":
        c = "Racquet guidance uses weak pose-guided candidates until a detector is active."
        if c not in caveats and len(caveats) < 3:
            caveats.append(c)
    if racquet_evidence.get("mode") == "frame_context_only":
        c = "Racquet guidance is frame-context only until a racquet detector is active."
        if c not in caveats and len(caveats) < 3:
            caveats.append(c)

    if not strengths:
        strengths = ["The selected reel favors longer exchanges with sustained movement."]
    if not work_on:
        work_on = ["Improve tracking quality before using technique-specific feedback."]

    return {
        "enabled": True,
        "status": "ok",
        "engine": config.COACH_MODEL,
        "contract": CONTRACT,
        "headline": _short(data.get("headline") or "Grounded coach notes are ready.", 110),
        "confidence": confidence,
        "strengths": strengths,
        "work_on": work_on,
        "moments": _clean_moments(data.get("moments"), max_rally=len(payload.get("rallies") or [])),
        "caveats": caveats,
        "summary": summary,
        "evidence": payload.get("evidence") or {"mode": "metadata", "frames": []},
    }


def summarize(sport: str, vision: dict | None, rendered: list[dict],
              all_rallies: list[dict], proxy_path: str | Path | None = None,
              log=print) -> dict:
    """Return a compact coach object; never fail the reel pipeline."""
    if not config.COACH_ENABLED:
        return _disabled("COACH_ENABLED is off")
    if not rendered:
        return _skipped("No rendered rallies available for coach notes")
    if not isinstance(vision, dict) or vision.get("status") != "ok":
        return _skipped("Runpod vision is unavailable; coach notes need measured player/pose data")

    payload = _build_payload(sport, vision, rendered, all_rallies)
    summary = payload["quality_summary"]
    if summary["player_quality"] < 0.2 and summary["pose_quality"] < 0.2:
        return _skipped("Vision signal is too weak for useful coach notes", summary)

    visual_parts, visual_evidence = _frame_parts(proxy_path, rendered, log=log)
    payload["evidence"] = {
        "mode": "metadata+frames" if visual_evidence else "metadata",
        "frames": visual_evidence,
    }
    summary["racquet_evidence"] = _racquet_evidence(summary, payload.get("rallies") or [], visual_evidence)
    payload["measurement_caveats"] = _measurement_caveats(summary)
    prompt = (
        f"{PROMPT}\n\nMeasured metadata:\n"
        f"{json.dumps(payload, indent=2, sort_keys=True)}"
    )
    try:
        log(f"asking {config.COACH_MODEL} for grounded coach notes")
        text = gemini.generate(
            config.COACH_MODEL,
            [{"text": prompt}, *visual_parts],
            json_schema=SCHEMA,
            temperature=0.25,
            max_tokens=2048,
        )
        data = gemini.parse_json(text)
        if not isinstance(data, dict):
            raise gemini.GeminiError("coach response was not a JSON object")
        return _sanitize(data, payload)
    except Exception as exc:  # noqa: BLE001 - coaching is optional enrichment.
        log(f"Gemini coach failed, keeping the reel: {type(exc).__name__}: {exc}")
        return _failed(f"{type(exc).__name__}: {exc}", summary)
