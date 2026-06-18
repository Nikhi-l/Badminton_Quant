"""Per-job vision router.

Decides, from the job's selected options, which vision workers run and where:

  shuttle = tracknetv3  -> Runpod serverless GPU (bundles pose if also selected),
                           because TrackNetV3 on CPU is ~1 hour/reel. Falls back to
                           the CPU motion camera (or optional CPU TrackNet) if the
                           GPU endpoint is unavailable.
  pose only (no shuttle) -> YOLO11 on the VM CPU (cheap), no GPU spin-up.
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

    ok, why = vision_local.available()
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

    if shuttle == "off" and pose == "off":
        out = gpu._disabled("no vision workers selected — CPU motion camera")
        out["options"] = opt
        return out

    if shuttle == "tracknetv3":
        tasks = ["shuttle"]
        if pose == "yolo11":
            tasks += ["players", "pose"]
        log(f"shuttle=TrackNetV3{' +pose' if pose == 'yolo11' else ''} → GPU worker")
        out = gpu.analyze(proxy_path, workdir, sport, rallies, log=log, tasks=tasks)
        out.setdefault("backend", "runpod")
        if out.get("status") in {"disabled", "failed"}:
            log(f"GPU shuttle unavailable ({out.get('message', '')[:80]})")
            if config.VISION_ALLOW_CPU_TRACKNET:
                log("falling back to on-device TrackNetV3 (slow CPU pass)")
                out = _local(proxy_path, rallies, tasks, log)
            elif pose == "yolo11":
                log("running pose on the VM CPU; shuttle camera falls back to motion")
                out = _local(proxy_path, rallies, ["players", "pose"], log)
        out["options"] = opt
        return out

    # pose only (no shuttle) → CPU on the VM
    log("pose=YOLO11 → on-device CPU (no GPU)")
    out = _local(proxy_path, rallies, ["players", "pose"], log)
    out["options"] = opt
    return out


# rally lookup is identical regardless of backend.
rally = gpu.rally
