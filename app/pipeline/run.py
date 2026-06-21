"""Pipeline orchestrator. Callable from the web worker or as a CLI:

    python -m app.pipeline.run <video> --workdir data/outputs/test
"""
import argparse
import json
import time
from pathlib import Path

from .. import config
from . import coach, gemini, media, rally, render, stitch, track, validate
from . import vision as vision_engine

STAGES = ["combine", "probe", "proxy", "rallies", "vision", "tracking", "render",
          "validate", "coach", "stitch"]


def _good_window(v: dict, clip_dur: float) -> tuple[float, float] | None:
    """If a clip failed only because of bad frames clustered at its edges, return
    the longest clean (start, end) window worth keeping instead of dropping it."""
    frames = sorted(((v.get("gemini") or {}).get("frames") or []), key=lambda f: f.get("t", 0))
    if not frames:
        return None
    marks = [(f.get("t", 0.0), f.get("framing") == "ok") for f in frames]
    best, cur_start = None, None
    for idx, (t, ok) in enumerate(marks):
        if ok and cur_start is None:
            cur_start = idx
        if (not ok or idx == len(marks) - 1) and cur_start is not None:
            end_idx = idx if ok else idx - 1
            lo = 0.0 if cur_start == 0 else (marks[cur_start - 1][0] + marks[cur_start][0]) / 2
            hi = clip_dur if end_idx == len(marks) - 1 else (marks[end_idx][0] + marks[end_idx + 1][0]) / 2
            if best is None or hi - lo > best[1] - best[0]:
                best = (lo, hi)
            cur_start = None
    if best and best[1] - best[0] >= 4.5 and best[1] - best[0] < clip_dur - 0.5:
        return best
    return None


def _why(v: dict) -> str:
    h = v.get("heuristics") or {}
    if h and not h.get("ok", True):
        return "+".join(sorted({i["kind"] for i in h.get("issues", [])})) or "heuristics"
    m = v.get("motion") or {}
    if m and not m.get("ok", True):
        return f"jerky motion (p99={m.get('jerk99')}px)"
    g = v.get("gemini") or {}
    bad = [f for f in g.get("frames", []) if f.get("framing") != "ok"]
    return ", ".join(f"{f.get('framing')}@{f.get('t')}s" for f in bad[:3]) or "gemini"


def _order_clips(paths: list[Path], log) -> tuple[list[Path], str]:
    """Sort multi-clip uploads by recording time when every clip has one."""
    stamps = [(p, media.creation_time(p)) for p in paths]
    if all(s for _, s in stamps) and len({s for _, s in stamps}) == len(stamps):
        ordered = [p for p, _ in sorted(stamps, key=lambda x: x[1])]
        for p, s in sorted(stamps, key=lambda x: x[1]):
            log(f"{p.name} recorded {s}")
        return ordered, "recording time"
    log("clips lack distinct recording timestamps — keeping upload order")
    return paths, "upload order"


def process(input_path, workdir: str | Path, cb=None, options=None) -> dict:
    """input_path: one video path or a list of them (multi-clip game).
    options: per-job vision worker selection (see config.normalize_options).
    cb(stage, message) is invoked on stage transitions and progress notes."""
    t_start = time.time()
    gemini.reset_usage()
    opt = config.normalize_options(options)
    pipeline = config.pipeline_for_options(opt)
    paths = [Path(p) for p in (input_path if isinstance(input_path, (list, tuple)) else [input_path])]
    workdir = Path(workdir)
    clips_dir = workdir / "clips"
    clips_dir.mkdir(parents=True, exist_ok=True)

    def note(stage, msg=""):
        if cb:
            cb(stage, msg)
        print(f"[{stage}] {msg}", flush=True)

    order_source = None
    if len(paths) > 1:
        note("combine", f"{len(paths)} clips uploaded — ordering and joining")
        ordered, order_source = _order_clips(paths, log=lambda m: note("combine", m))
        combined = workdir / "combined.mp4"
        media.normalize_concat(ordered, combined, log=lambda m: note("combine", m))
        input_path = combined
    else:
        input_path = paths[0]

    note("probe", "reading video metadata")
    info = media.probe(input_path)
    note("probe", f"{info.width}x{info.height} @ {info.fps:.0f}fps, {info.duration:.1f}s")

    note("proxy", f"downscaling to {config.PROXY_HEIGHT}p analysis proxy")
    proxy = workdir / "proxy.mp4"
    pinfo = media.make_proxy(input_path, proxy)

    cam_px = validate.camera_motion_probe(proxy, pinfo.duration)
    pov = cam_px > 1.0
    motion_limit = 30.0 if pov else 3.0
    if pov:
        note("proxy", f"handheld/POV camera detected (motion {cam_px:.1f}px) — "
                      f"gentle camera, source shake tolerated")

    note("rallies", "Gemini is watching the game")
    sport, all_rallies = rally.segment(proxy, pinfo.duration, log=lambda m: note("rallies", m))
    picked = rally.select_for_reel(all_rallies)
    picked.sort(key=lambda r: r["dur"], reverse=True)  # longest first in the reel
    if not picked:
        raise RuntimeError("no rallies detected in this video")
    note("rallies", f"{len(all_rallies)} rallies found, using top {len(picked)} by length")

    note("vision", f"vision: shuttle={opt['shuttle']}, pose={opt['pose']}")
    vision = vision_engine.analyze(proxy, workdir, sport, picked, opt,
                                   log=lambda m: note("vision", m))
    if vision.get("status") == "disabled":
        note("vision", vision.get("message", "vision workers disabled"))
    elif vision.get("status") == "failed":
        note("vision", "vision worker failed; using CPU tracking")
    else:
        summary = vision.get("summary") or {}
        player_q = float(summary.get("player_quality") or 0)
        shuttle_q = float(summary.get("shuttle_quality") or 0)
        note("vision", f"vision ready ({vision.get('backend', 'gpu')}): "
                       f"players {player_q:.0%}, shuttle {shuttle_q:.0%}")

    clips: list[Path] = []
    rendered = []
    validation: list[dict] = []
    for i, r in enumerate(picked, 1):
        t0 = max(0.0, r["start"] - config.PAD_BEFORE)
        t1 = min(info.duration, r["end"] + config.PAD_AFTER)
        note("tracking", f"rally {i}/{len(picked)}: tracking action {t0:.0f}s-{t1:.0f}s")
        vision_rally = vision_engine.rally(vision, i)
        path = track.from_vision(proxy, t0, t1, vision_rally) if not pov else None
        shuttle_cam = path is not None   # shuttle-follow camera → lenient framing audit
        if path is None:
            path = track.track(proxy, t0, t1, force_gentle=pov)
        else:
            note("tracking", f"rally {i}: using shuttle-follow camera")
        cw_norm, ch_norm = track._crop_norms(proxy)
        ps = validate.path_smoothness(path, cw_norm, ch_norm)
        if not ps["ok"]:
            note("tracking", f"rally {i}: camera path too jerky "
                             f"(pan {ps['ax99']:.4f}, zoom {ps['az99']:.4f}) — extra smoothing")
            path = track.track(proxy, t0, t1, extra_smooth=True, force_gentle=pov)
            shuttle_cam = False  # replaced with a motion path → strict audit
            if not validate.path_smoothness(path, cw_norm, ch_norm)["ok"]:
                note("tracking", f"rally {i}: falling back to static wide camera")
                path = track.safe_path(proxy, t0, t1)
        note("render", f"rally {i}/{len(picked)}: virtual camera render")
        out = clips_dir / f"clip_{i:02d}.mp4"
        label = (f"RALLY {i}", f"{r['dur']:.0f}s · {r['note'] or 'match play'}")
        dur = render.render_rally(input_path, info, t0, t1, path, out, *label,
                                  annotations=vision_rally)

        note("validate", f"rally {i}/{len(picked)}: checking frames")
        v = validate.validate_clip(out, motion_limit, pov, lenient_framing=shuttle_cam)
        attempt = {"rally": i, "pass": "tracked", "ok": v["ok"]}
        trim_range = None
        if not v["ok"]:
            win = _good_window(v, dur)
            if win:   # bad frames hug an edge (usually a boundary overshoot): trim
                nt0, nt1 = t0 + win[0], t0 + win[1]
                note("validate", f"rally {i}: failed ({_why(v)}) — trimming to clean "
                                 f"window {win[0]:.1f}-{win[1]:.1f}s")
                path = track.from_vision(proxy, nt0, nt1, vision_rally) if not pov else None
                trim_shuttle_cam = path is not None
                if path is None:
                    path = track.track(proxy, nt0, nt1, force_gentle=pov)
                dur = render.render_rally(input_path, info, nt0, nt1, path, out, *label,
                                          annotations=vision_rally)
                v = validate.validate_clip(out, motion_limit, pov, lenient_framing=trim_shuttle_cam)
                attempt = {"rally": i, "pass": "trimmed", "ok": v["ok"]}
                if v["ok"]:
                    trim_range = (nt0, nt1)
        if not v["ok"]:
            note("validate", f"rally {i}: failed ({_why(v)}) — re-rendering with safe camera")
            dur = render.render_rally(input_path, info, t0, t1,
                                      track.safe_path(proxy, t0, t1), out, *label,
                                      annotations=vision_rally)
            v = validate.validate_clip(out, motion_limit, pov)
            attempt = {"rally": i, "pass": "safe", "ok": v["ok"]}
            if not v["ok"]:
                note("validate", f"rally {i}: still failing ({_why(v)}) — dropping from reel")
                validation.append({**attempt, "dropped": True, "detail": _why(v)})
                out.unlink(missing_ok=True)
                continue
        validation.append(attempt)
        clips.append(out)
        entry = {**r, "clip": out.name, "clip_dur": round(dur, 2), "src_start": r["start"]}
        if trim_range:   # report the window that actually shipped, keep identity via src_start
            entry.update(start=round(trim_range[0], 2), end=round(trim_range[1], 2),
                         dur=round(trim_range[1] - trim_range[0], 2), trimmed=True)
        if vision_rally:
            entry["vision"] = {k: vision_rally.get(k) for k in (
                "status", "camera_mode", "shuttle_quality", "player_quality",
                "pose_quality", "racquet_quality", "pose_samples", "racquet_samples",
                "racquet_candidate_quality", "racquet_candidate_samples",
                "mask_enabled", "shuttle_engine", "tracknet", "shuttle", "players"
            )}
        rendered.append(entry)

    if not clips:
        raise RuntimeError("all rally clips failed validation — source video may be unusable")

    if opt["coach"]:
        note("coach", "summarizing measured rally signals")
        coach_result = coach.summarize(sport, vision, rendered, all_rallies, proxy,
                                       log=lambda m: note("coach", m))
        if coach_result.get("status") == "ok":
            note("coach", coach_result.get("headline", "coach notes ready"))
        else:
            note("coach", coach_result.get("message", "coach notes skipped"))
    else:
        coach_result = {"status": "disabled", "message": "coach not selected for this job"}

    note("stitch", "concatenating clips and mixing soundtrack")
    result = stitch.stitch(clips, workdir, log=lambda m: note("stitch", m))
    reel_check = validate.heuristics(result["reel"])
    cuts, acc = [], 0.0
    for k, r in enumerate(rendered[:-1]):
        acc += r["clip_dur"]
        # crossfades overlap clips: boundary k sits at the center of fade k
        cuts.append(acc - (k + 1) * stitch.XFADE + stitch.XFADE / 2)
    reel_motion = validate.motion_jerk(result["reel"], exclude_times=cuts, limit=motion_limit)
    reel_check["motion"] = reel_motion
    reel_check["ok"] = reel_check["ok"] and reel_motion["ok"]
    note("validate", f"final reel: {reel_check['frames_checked']} frames, "
                     f"motion jerk p99={reel_motion['jerk99']}px — "
                     f"{'clean' if reel_check['ok'] else 'ISSUES'}")

    out = {
        "reel": str(result["reel"]),
        "thumb": str(result["thumb"]),
        "sport": sport,
        "all_rallies": [
            {**r, "used": any(abs(u.get("src_start", u["start"]) - r["start"]) < 0.5
                              for u in rendered)}
            for r in all_rallies
        ],
        "duration": result["duration"],
        "n_rallies_found": len(all_rallies),
        "n_rallies_used": len(rendered),
        "rallies": rendered,
        "validation": {"clips": validation, "reel": reel_check},
        "source": {"w": info.width, "h": info.height, "fps": round(info.fps, 2),
                   "duration": round(info.duration, 2)},
        "n_clips": len(paths),
        "clip_order": order_source,
        "pov_camera": pov,
        "options": opt,
        "pipeline": pipeline,
        "vision": {k: vision.get(k) for k in ("enabled", "status", "engine", "contract",
                                              "worker_version", "message", "models", "summary",
                                              "backend")},
        "coach": coach_result,
        "gemini_usage": gemini.usage_snapshot(),
        "elapsed_sec": round(time.time() - t_start, 1),
    }
    (workdir / "result.json").write_text(json.dumps(out, indent=2))
    note("stitch", f"done in {out['elapsed_sec']}s")
    return out


def remix(input_path, workdir: str | Path, order: list[int], mirror: bool = False,
          cb=None) -> dict:
    """Rebuild an existing job's reel: keep only the rallies in `order` (1-based
    indices into result['rallies']), in that sequence, optionally mirrored.
    Fast path (no mirror): re-stitch existing clips. Mirror: re-render each clip."""
    workdir = Path(workdir)
    result = json.loads((workdir / "result.json").read_text())
    # Non-destructive editing: always select from the full pool of rendered
    # rallies, so a rally dropped in one remix can return in the next.
    rallies = result.get("rally_pool") or result["rallies"]
    result["rally_pool"] = rallies
    proxy = workdir / "proxy.mp4"
    combined = workdir / "combined.mp4"
    src = combined if combined.exists() else Path(input_path)
    pov = bool(result.get("pov_camera"))

    def note(stage, msg=""):
        if cb:
            cb(stage, msg)
        print(f"[remix:{stage}] {msg}", flush=True)

    bad = [i for i in order if not 1 <= i <= len(rallies)]
    if bad or not order:
        raise RuntimeError(f"remix indices out of range: {bad or 'empty selection'}")
    chosen = [rallies[i - 1] for i in order]

    info = media.probe(src)
    clips = []
    for slot, r in enumerate(chosen, 1):
        clip = workdir / "clips" / r["clip"]
        if mirror:
            note("render", f"rally {slot}/{len(chosen)}: mirrored re-render")
            if r.get("trimmed"):
                t0, t1 = r["start"], r["end"]
            else:
                t0 = max(0.0, r["start"] - config.PAD_BEFORE)
                t1 = min(info.duration, r["end"] + config.PAD_AFTER)
            path = track.from_vision(proxy, t0, t1, r.get("vision")) if not pov else None
            if path is None:
                path = track.track(proxy, t0, t1, force_gentle=pov)
            clip = workdir / "clips" / f"mirror_{r['clip']}"
            render.render_rally(src, info, t0, t1, path, clip,
                                f"RALLY {slot}", f"{r['dur']:.0f}s · {r['note'] or 'match play'}",
                                mirror=True, annotations=r.get("vision"))
        clips.append(clip)

    note("stitch", "rebuilding reel")
    stitched = stitch.stitch(clips, workdir, log=lambda m: note("stitch", m))
    check = validate.heuristics(stitched["reel"])
    if not check["ok"]:
        raise RuntimeError(f"remixed reel failed frame checks: {check['issues'][:3]}")
    result["duration"] = stitched["duration"]
    result["rallies"] = chosen
    result["n_rallies_used"] = len(chosen)
    result["remix"] = {"order": order, "mirror": mirror}
    (workdir / "result.json").write_text(json.dumps(result, indent=2))
    note("stitch", "remix done")
    return result


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("input")
    ap.add_argument("--workdir", default=str(config.OUTPUTS / "cli_test"))
    args = ap.parse_args()
    res = process(args.input, args.workdir)
    print(json.dumps(res, indent=2))


if __name__ == "__main__":
    main()
