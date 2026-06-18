"""Signed URLs for large pipeline artifacts consumed by GPU workers."""
from __future__ import annotations

import hashlib
import hmac
import time
from pathlib import Path
from urllib.parse import urlencode

from . import config

GPU_ARTIFACTS = {"proxy.mp4"}


def _message(job_id: str, name: str, exp: int) -> bytes:
    return f"{job_id}:{name}:{exp}".encode("utf-8")


def sign(job_id: str, name: str, ttl: int | None = None) -> str:
    if not config.GPU_ARTIFACT_TOKEN:
        return ""
    exp = int(time.time()) + int(ttl or config.GPU_ARTIFACT_TTL_SEC)
    digest = hmac.new(
        config.GPU_ARTIFACT_TOKEN.encode("utf-8"),
        _message(job_id, name, exp),
        hashlib.sha256,
    ).hexdigest()
    return f"{exp}.{digest}"


def verify(job_id: str, name: str, token: str) -> bool:
    if name not in GPU_ARTIFACTS or not config.GPU_ARTIFACT_TOKEN:
        return False
    try:
        exp_s, digest = token.split(".", 1)
        exp = int(exp_s)
    except (ValueError, AttributeError):
        return False
    if exp < int(time.time()):
        return False
    expected = hmac.new(
        config.GPU_ARTIFACT_TOKEN.encode("utf-8"),
        _message(job_id, name, exp),
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, digest)


def url_for(job_id: str, name: str) -> str | None:
    if not config.PUBLIC_BASE_URL or not config.GPU_ARTIFACT_TOKEN:
        return None
    token = sign(job_id, name)
    qs = urlencode({"token": token})
    return f"{config.PUBLIC_BASE_URL}/api/gpu-artifacts/{job_id}/{name}?{qs}"


def path_for(job_id: str, name: str) -> Path:
    return config.OUTPUTS / job_id / name
