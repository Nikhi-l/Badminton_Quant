#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")"

IMAGE="${BADDY_WORKER_IMAGE:-baddy-vision-worker:tracknet}"
INSTALL_TRACKNET="${INSTALL_TRACKNET:-1}"
PLATFORM="${DOCKER_PLATFORM:-linux/amd64}"
PUSH="${PUSH:-0}"

if ! docker info >/dev/null 2>&1; then
  echo "Docker daemon is not reachable. Start Docker Desktop, then retry." >&2
  exit 1
fi

if [ ! -f "models/tracknet/TrackNet_best.pt" ]; then
  echo "models/tracknet/TrackNet_best.pt is missing." >&2
  echo "Download TrackNetV3_ckpts.zip from the upstream TrackNetV3 README and unzip it here." >&2
  exit 1
fi

docker build \
  --platform "$PLATFORM" \
  --build-arg INSTALL_TRACKNET="$INSTALL_TRACKNET" \
  -t "$IMAGE" \
  .

if [ "$PUSH" = "1" ]; then
  docker push "$IMAGE"
else
  echo "Built $IMAGE"
  echo "Set PUSH=1 BADDY_WORKER_IMAGE=<registry/image:tag> to push for Runpod."
fi
