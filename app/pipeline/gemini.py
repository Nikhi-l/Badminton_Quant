"""Minimal Gemini REST client (Files API upload + generateContent). No SDK dependency."""
import json
import time
from pathlib import Path

import requests

from .. import config

BASE = "https://generativelanguage.googleapis.com"


class GeminiError(RuntimeError):
    pass


# Per-job token accounting (the worker runs one job at a time).
USAGE = {"prompt_tokens": 0, "output_tokens": 0, "calls": 0}


def reset_usage():
    USAGE.update(prompt_tokens=0, output_tokens=0, calls=0)


def usage_snapshot() -> dict:
    cost = (USAGE["prompt_tokens"] / 1e6 * config.GEMINI_IN_RATE
            + USAGE["output_tokens"] / 1e6 * config.GEMINI_OUT_RATE)
    return {**USAGE, "est_cost_usd": round(cost, 4)}


def _key() -> str:
    if not config.GEMINI_API_KEY:
        raise GeminiError("GEMINI_API_KEY is not set")
    return config.GEMINI_API_KEY


def upload_file(path: str | Path, mime: str = "video/mp4", timeout: int = 600) -> dict:
    """Resumable upload to the Gemini Files API. Returns the file resource dict."""
    path = Path(path)
    size = path.stat().st_size
    start = requests.post(
        f"{BASE}/upload/v1beta/files?key={_key()}",
        headers={
            "X-Goog-Upload-Protocol": "resumable",
            "X-Goog-Upload-Command": "start",
            "X-Goog-Upload-Header-Content-Length": str(size),
            "X-Goog-Upload-Header-Content-Type": mime,
            "Content-Type": "application/json",
        },
        json={"file": {"display_name": path.name}},
        timeout=60,
    )
    start.raise_for_status()
    upload_url = start.headers.get("X-Goog-Upload-URL")
    if not upload_url:
        raise GeminiError(f"no upload URL returned: {start.text[:300]}")

    with open(path, "rb") as f:
        up = requests.post(
            upload_url,
            headers={
                "X-Goog-Upload-Command": "upload, finalize",
                "X-Goog-Upload-Offset": "0",
                "Content-Length": str(size),
            },
            data=f,
            timeout=timeout,
        )
    up.raise_for_status()
    return up.json()["file"]


def wait_active(file: dict, timeout: float = 600) -> dict:
    """Poll until the uploaded file finishes server-side processing."""
    name = file["name"]
    deadline = time.time() + timeout
    while time.time() < deadline:
        if file.get("state") == "ACTIVE":
            return file
        if file.get("state") == "FAILED":
            raise GeminiError(f"file processing failed: {file}")
        time.sleep(4)
        r = requests.get(f"{BASE}/v1beta/files/{name.split('/')[-1]}?key={_key()}", timeout=30)
        r.raise_for_status()
        file = r.json()
    raise GeminiError("timed out waiting for file to become ACTIVE")


def generate(model: str, parts: list[dict], *, json_schema: dict | None = None,
             temperature: float = 0.2, max_tokens: int = 16384, retries: int = 4) -> str:
    """generateContent with retry/backoff. Returns concatenated text of the first candidate."""
    body: dict = {
        "contents": [{"role": "user", "parts": parts}],
        "generationConfig": {"temperature": temperature, "maxOutputTokens": max_tokens},
    }
    if json_schema is not None:
        body["generationConfig"]["responseMimeType"] = "application/json"
        body["generationConfig"]["responseSchema"] = json_schema

    url = f"{BASE}/v1beta/models/{model}:generateContent?key={_key()}"
    delay = 5.0
    last = ""
    for attempt in range(retries):
        r = requests.post(url, json=body, timeout=600)
        if r.status_code in (429, 500, 502, 503, 504):
            last = r.text[:500]
            time.sleep(delay)
            delay *= 2
            continue
        if not r.ok:
            raise GeminiError(f"{model} HTTP {r.status_code}: {r.text[:500]}")
        data = r.json()
        um = data.get("usageMetadata") or {}
        USAGE["prompt_tokens"] += um.get("promptTokenCount", 0)
        USAGE["output_tokens"] += (um.get("candidatesTokenCount", 0)
                                   + um.get("thoughtsTokenCount", 0))
        USAGE["calls"] += 1
        try:
            cand = data["candidates"][0]
            texts = [p.get("text", "") for p in cand.get("content", {}).get("parts", [])]
            out = "".join(texts).strip()
        except (KeyError, IndexError):
            raise GeminiError(f"unexpected response shape: {json.dumps(data)[:500]}")
        if not out:
            raise GeminiError(f"empty response (finishReason={data['candidates'][0].get('finishReason')})")
        return out
    raise GeminiError(f"{model} kept failing after {retries} retries: {last}")


def parse_json(text: str):
    """Parse model JSON output, tolerating markdown fences."""
    t = text.strip()
    if t.startswith("```"):
        t = t.split("\n", 1)[1] if "\n" in t else t
        t = t.rsplit("```", 1)[0].strip()
        if t.startswith("json"):
            t = t[4:].strip()
    return json.loads(t)
