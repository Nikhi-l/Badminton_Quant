#!/usr/bin/env python3
"""Update the existing Runpod endpoint template image.

This uses Runpod's management REST API, not the endpoint-scoped `/run` API key.
Set RUNPOD_MANAGEMENT_API_KEY when available; RUNPOD_API_KEY is accepted only if
it has management scope.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Any

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import config

REST_BASE = "https://rest.runpod.io/v1"


def _redact(v: str | None) -> str:
    if not v:
        return ""
    return v if len(v) <= 8 else f"{v[:4]}...{v[-4:]}"


def _die(message: str, code: int = 1) -> int:
    print(message, file=sys.stderr)
    return code


def _request(method: str, path: str, api_key: str, **kwargs: Any) -> dict:
    resp = requests.request(
        method,
        f"{REST_BASE}{path}",
        headers={"Authorization": f"Bearer {api_key}", "content-type": "application/json"},
        timeout=45,
        **kwargs,
    )
    if resp.status_code in {401, 403}:
        raise PermissionError(
            f"Runpod management API returned {resp.status_code}; use a management-scoped key"
        )
    resp.raise_for_status()
    data = resp.json()
    return data if isinstance(data, dict) else {"data": data}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--endpoint-id", default=config.RUNPOD_ENDPOINT_ID)
    parser.add_argument("--image", required=True, help="New Docker image tag for the endpoint template")
    parser.add_argument("--apply", action="store_true", help="Actually patch the template image")
    args = parser.parse_args()

    api_key = os.environ.get("RUNPOD_MANAGEMENT_API_KEY") or config.RUNPOD_API_KEY
    if not args.endpoint_id:
        return _die("RUNPOD_ENDPOINT_ID or --endpoint-id is required")
    if not api_key:
        return _die("RUNPOD_MANAGEMENT_API_KEY is required")

    try:
        endpoint = _request("GET", f"/endpoints/{args.endpoint_id}", api_key)
    except PermissionError as exc:
        return _die(str(exc))

    template = endpoint.get("template") if isinstance(endpoint.get("template"), dict) else {}
    template_id = endpoint.get("templateId") or template.get("id")
    current_image = template.get("imageName")
    if not template_id:
        return _die("Could not find templateId on endpoint response")

    print(f"endpoint: {_redact(args.endpoint_id)}")
    print(f"template: {template_id}")
    print(f"current image: {current_image or '(unknown)'}")
    print(f"new image: {args.image}")

    if not args.apply:
        print("dry run only; add --apply to patch the template image")
        return 0

    patched = _request("PATCH", f"/templates/{template_id}", api_key, json={"imageName": args.image})
    patched_image = (patched.get("imageName")
                     or (patched.get("template") if isinstance(patched.get("template"), dict) else {}).get("imageName")
                     or args.image)
    print(f"updated template image: {patched_image}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
