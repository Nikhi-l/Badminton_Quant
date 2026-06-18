#!/usr/bin/env python3
"""Submit a small Baddy vision job to a configured Runpod endpoint.

The script intentionally prints only non-secret configuration and a compact
contract summary. Use it after creating a Runpod Serverless endpoint and setting
RUNPOD_API_KEY/RUNPOD_ENDPOINT_ID in the app environment.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import artifacts, config  # noqa: E402
from app.pipeline import gpu  # noqa: E402


def _num(v: Any, default: float = 0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _require_env() -> None:
    missing = [k for k, v in {
        "RUNPOD_API_KEY": config.RUNPOD_API_KEY,
        "RUNPOD_ENDPOINT_ID": config.RUNPOD_ENDPOINT_ID,
    }.items() if not v]
    if missing:
        raise SystemExit(
            "Missing required env: " + ", ".join(missing)
            + ". Add them to .env or export them before running this smoke."
        )


def _proxy_url(args: argparse.Namespace) -> str:
    if args.proxy_url:
        return args.proxy_url
    if not args.job_id:
        raise SystemExit("Provide either --proxy-url or --job-id")
    url = artifacts.url_for(args.job_id, "proxy.mp4")
    if not url:
        raise SystemExit(
            "--job-id requires PUBLIC_BASE_URL and GPU_ARTIFACT_TOKEN so Runpod can fetch proxy.mp4"
        )
    return url


def _payload(args: argparse.Namespace, proxy_url: str) -> tuple[dict, list[dict]]:
    start = max(0.0, _num(args.start))
    end = max(start + 0.5, _num(args.end, start + 8.0))
    rally = {
        "rally_index": 1,
        "start": round(start, 3),
        "end": round(end, 3),
        "dur": round(end - start, 3),
        "note": args.note,
        "intensity": args.intensity,
    }
    payload = {
        "contract": gpu.CONTRACT,
        "job_id": args.job_id or "runpod-smoke",
        "sport": args.sport,
        "proxy_url": proxy_url,
        "proxy_name": "proxy.mp4",
        "rallies": [rally],
        "tasks": ["players", "pose", "racquet", "shuttle"],
        "return_normalized_coordinates": True,
        "smoke": True,
    }
    return payload, [rally]


def _assert_contract(canon: dict) -> None:
    if canon.get("status") != "ok":
        raise RuntimeError(f"canonical status is not ok: {canon.get('status')}")
    if canon.get("contract") != gpu.CONTRACT:
        raise RuntimeError(f"unexpected contract: {canon.get('contract')}")
    rallies = canon.get("rallies") or []
    if len(rallies) != 1:
        raise RuntimeError(f"expected one rally result, got {len(rallies)}")
    rally = rallies[0]
    required = {
        "player_quality", "pose_quality", "racquet_quality", "racquet_candidate_quality",
        "shuttle_quality", "players", "shuttle", "pose_samples", "racquet_samples",
        "racquet_candidate_samples",
    }
    missing = sorted(k for k in required if k not in rally)
    if missing:
        raise RuntimeError("canonical rally missing keys: " + ", ".join(missing))


def _safe_endpoint() -> str:
    endpoint = config.RUNPOD_ENDPOINT_ID
    if len(endpoint) <= 8:
        return endpoint
    return endpoint[:4] + "..." + endpoint[-4:]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--proxy-url", help="Public or signed URL to a proxy.mp4 Runpod can fetch")
    parser.add_argument("--job-id", help="Existing app job id; derives a signed /api/gpu-artifacts URL")
    parser.add_argument("--sport", default="badminton")
    parser.add_argument("--start", type=float, default=0.0)
    parser.add_argument("--end", type=float, default=8.0)
    parser.add_argument("--note", default="runpod smoke rally")
    parser.add_argument("--intensity", type=int, default=3)
    parser.add_argument("--timeout-sec", type=float, help="Override RUNPOD_TIMEOUT_SEC for this smoke")
    parser.add_argument("--save", type=Path, help="Write canonicalized JSON output to this path")
    args = parser.parse_args()

    _require_env()
    if args.timeout_sec:
        config.RUNPOD_TIMEOUT_SEC = args.timeout_sec

    proxy_url = _proxy_url(args)
    payload, rallies = _payload(args, proxy_url)

    print(f"Runpod endpoint: {_safe_endpoint()}")
    print(f"Submitting {payload['sport']} smoke rally {payload['rallies'][0]['start']}s-"
          f"{payload['rallies'][0]['end']}s")
    raw = gpu._runpod_request(payload, log=lambda msg: print(msg, flush=True))
    canon = gpu._canonicalize(raw, rallies)
    _assert_contract(canon)
    if args.save:
        args.save.parent.mkdir(parents=True, exist_ok=True)
        args.save.write_text(json.dumps(canon, indent=2))
    rally = canon["rallies"][0]
    summary = {
        "status": canon["status"],
        "engine": canon["engine"],
        "worker_version": canon.get("worker_version") or "",
        "player_quality": rally["player_quality"],
        "pose_quality": rally["pose_quality"],
        "racquet_quality": rally["racquet_quality"],
        "racquet_candidate_quality": rally["racquet_candidate_quality"],
        "shuttle_quality": rally["shuttle_quality"],
        "player_samples": len(rally.get("players") or []),
        "pose_samples": rally.get("pose_samples", 0),
        "racquet_samples": rally.get("racquet_samples", 0),
        "racquet_candidate_samples": rally.get("racquet_candidate_samples", 0),
        "shuttle_samples": len(rally.get("shuttle") or []),
    }
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
