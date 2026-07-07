"""Per-job vision router.

Decides, from the job's selected options, which vision workers run and where:

  shuttle = tracknetv3  -> Runpod serverless GPU (bundles pose if also selected),
                           because TrackNetV3 on CPU is ~1 hour/reel. Falls back to
                           the CPU motion camera (or optional CPU TrackNet) if the
                           GPU endpoint is unavailable.
  pose only (no shuttle) -> configurable YOLO pose backend; GPU-first by default,
                            local CPU/MPS fallback when Runpod is unavailable.
  neither                -> disabled; the CPU motion centroid camera is used.

Returns the canonical ``baddy.vision.v1`` dict the rest of the pipeline consumes.
"""
from __future__ import annotations

from pathlib import Path

from .. import config
from . import gpu


def _local(proxy_path, rallies, tasks, log):
    """Run the on-device engine for `tasks` and canonicalize, or a disabled dict."""
    from . import vision_local

    ok, why = vision_local.available(need_shuttle="shuttle" in tasks)
    if not ok:
        return gpu._disabled(f"on-device vision unavailable: {why}")
    raw = vision_local.analyze_raw(proxy_path, "", rallies, tasks=tasks, log=log)
    out = gpu._canonicalize(raw, rallies)
    out["backend"] = "local"
    return out


def analyze(proxy_path: str | Path, workdir: str | Path, sport: str,
            rallies: list[dict], options: dict, log=print) -> dict:
    opt = config.normalize_options(options)
    shuttle, pose = opt["shuttle"], opt["pose"]
    pose_on = pose == "yolo11"

    if shuttle == "off" and not pose_on:
        out = gpu._disabled("no vision workers selected — CPU motion camera")
        out["options"] = opt
        return out

    if shuttle == "tracknetv3":
        tasks = ["shuttle"]
        if pose_on:
            tasks += ["players", "pose", "racquet"]   # racquet chain needs wrists (TASK-027)
        log(f"shuttle=TrackNetV3{' +pose' if pose_on else ''} → GPU worker")
        out = gpu.analyze(proxy_path, workdir, sport, rallies, log=log, tasks=tasks)
        out.setdefault("backend", "runpod")
        if out.get("status") in {"disabled", "failed"}:
            log(f"GPU shuttle unavailable ({out.get('message', '')[:80]})")
            if config.VISION_ALLOW_CPU_TRACKNET:
                log("falling back to on-device TrackNetV3 (slow CPU pass)")
                out = _local(proxy_path, rallies, tasks, log)
            elif pose_on:
                log("running pose on the VM CPU; shuttle camera falls back to motion")
                out = _local(proxy_path, rallies, ["players", "pose"], log)
        out["options"] = opt
        return out

    # pose only (no shuttle) → GPU-first when configured; local fallback.
    if pose_on and config.pose_prefers_gpu() and config.runpod_ready():
        log(f"pose=YOLO ({config.POSE_MODEL_GPU}) → GPU worker")
        out = gpu.analyze(proxy_path, workdir, sport, rallies, log=log,
                          tasks=["players", "pose", "racquet"])
        out.setdefault("backend", "runpod")
        if out.get("status") not in {"disabled", "failed"}:
            out["options"] = opt
            return out
        log(f"GPU pose unavailable ({out.get('message', '')[:80]}); falling back to local pose")

    log(f"pose=YOLO ({config.POSE_MODEL_LOCAL}) → on-device local")
    out = _local(proxy_path, rallies, ["players", "pose"], log)
    out["options"] = opt
    return out


# rally lookup is identical regardless of backend.
rally = gpu.rally
