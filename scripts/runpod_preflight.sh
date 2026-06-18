#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORKER="$ROOT/runpod_worker"
TRACKNET_DIR="$WORKER/models/tracknet"

ok() { printf 'ok: %s\n' "$1"; }
warn() { printf 'warn: %s\n' "$1"; }
fail() { printf 'missing: %s\n' "$1"; }

echo "Baddy Runpod preflight"
echo "repo: $ROOT"
echo

if command -v docker >/dev/null 2>&1; then
  ok "docker client found ($(command -v docker))"
  if docker info >/dev/null 2>&1; then
    ok "docker daemon reachable"
  else
    fail "docker daemon is not running"
  fi
else
  fail "docker client"
fi

if [ -f "$TRACKNET_DIR/TrackNet_best.pt" ]; then
  ok "TrackNet_best.pt present"
else
  fail "$TRACKNET_DIR/TrackNet_best.pt"
fi

if [ -f "$TRACKNET_DIR/InpaintNet_best.pt" ]; then
  ok "InpaintNet_best.pt present"
else
  warn "InpaintNet_best.pt absent; TrackNet can still run without rectification"
fi

if [ -n "${BADDY_WORKER_IMAGE:-}" ]; then
  ok "BADDY_WORKER_IMAGE set"
else
  fail "BADDY_WORKER_IMAGE, for example ghcr.io/<owner>/baddy-vision-worker:tracknet"
fi

if [ -n "${RUNPOD_REGISTRY_AUTH_DURABLE:-}" ]; then
  ok "durable registry pull auth acknowledged"
else
  warn "durable registry pull auth not confirmed; short-lived GCP tokens can break cold pulls"
fi

if [ -n "${RUNPOD_ENDPOINT_ID:-}" ]; then
  ok "RUNPOD_ENDPOINT_ID set"
else
  warn "RUNPOD_ENDPOINT_ID not set yet"
fi

if [ -n "${RUNPOD_API_KEY:-}" ]; then
  ok "RUNPOD_API_KEY set"
else
  warn "RUNPOD_API_KEY not set; needed for scripts/runpod_smoke.py"
fi

if [ -n "${RUNPOD_MANAGEMENT_API_KEY:-}" ]; then
  ok "RUNPOD_MANAGEMENT_API_KEY set"
else
  warn "RUNPOD_MANAGEMENT_API_KEY not set; needed to update endpoint/template image"
fi

if [ -n "${PUBLIC_BASE_URL:-}" ] && [ -n "${GPU_ARTIFACT_TOKEN:-}" ]; then
  ok "public signed artifact config set"
else
  warn "PUBLIC_BASE_URL/GPU_ARTIFACT_TOKEN not both set; Runpod needs signed proxy URLs"
fi

echo
echo "Smallest practical GPU target: T4 or L4, serverless max workers 1 while testing."
