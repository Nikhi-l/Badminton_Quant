# Baddy Runpod worker

This folder is the containerized GPU worker for Baddy's optional `vision` stage.
It returns the `baddy.vision.v1` payload consumed by the web app.

## Local smoke

Runpod supports local handler tests with `--test_input`. Replace the sample
`proxy_url` with a signed URL from the app first:

```bash
cd runpod_worker
python handler.py --test_input "$(cat test_input.json)"
```

## Build

```bash
cd runpod_worker
docker build -t baddy-vision-worker:latest .
```

Build with the TrackNetV3 repo baked into the image:

```bash
docker build \
  --build-arg INSTALL_TRACKNET=1 \
  -t baddy-vision-worker:tracknet .
```

TrackNetV3 still needs checkpoints. Download `TrackNetV3_ckpts.zip` from the
upstream [TrackNetV3 README](https://github.com/qaz812345/TrackNetV3), unzip it,
and place:

```text
runpod_worker/models/tracknet/TrackNet_best.pt
runpod_worker/models/tracknet/InpaintNet_best.pt
```

The Docker image copies `runpod_worker/models` to `/models`. The default worker
env enables `/models/tracknet/TrackNet_best.pt`; set `TRACKNET_INPAINTNET_FILE`
only when `InpaintNet_best.pt` is also present.

The guarded build helper checks the model file first:

```bash
BADDY_WORKER_IMAGE=<registry>/baddy-vision-worker:tracknet \
  ./build_and_push.sh
```

For Runpod, push the image to a registry the endpoint can pull:

```bash
docker tag baddy-vision-worker:latest <registry>/baddy-vision-worker:latest
docker push <registry>/baddy-vision-worker:latest
# or:
PUSH=1 BADDY_WORKER_IMAGE=<registry>/baddy-vision-worker:tracknet ./build_and_push.sh
```

## Environment

```bash
BADDY_SAMPLE_FPS=6
BADDY_MAX_FRAMES_PER_RALLY=180
YOLO_POSE_MODEL=yolo11n-pose.pt
RACQUET_MODEL=/models/racquet.pt
YOLO_CONF=0.25
YOLO_IMGSZ=640
YOLO_DEVICE=0
TRACKNET_REPO=/opt/TrackNetV3
TRACKNET_TRACKNET_FILE=/models/tracknet/TrackNet_best.pt
TRACKNET_INPAINTNET_FILE=/models/tracknet/InpaintNet_best.pt
TRACKNET_BATCH_SIZE=8
TRACKNET_TIMEOUT_SEC=900
```

`YOLO_POSE_MODEL` can point to a local model file baked into the image or a
model name supported by Ultralytics. `RACQUET_MODEL` is optional until a
badminton racquet detector is trained. When `RACQUET_MODEL` is absent, the
worker emits low-confidence `racquet_candidates` from wrist-adjacent line
evidence; these are experimental context for Gemini, not measured racquet boxes.

`TRACKNET_TRACKNET_FILE` enables TrackNetV3 shuttle tracking. If the repo or
checkpoint is missing, the worker falls back to the classical small-motion
shuttle candidate and reports `tracknet.status=not_configured`.

## Output

The worker samples the selected rally windows only. Each output frame includes:

- `t`: absolute source timestamp in seconds
- `players`: up to two normalized player boxes
- `poses`: optional YOLO pose keypoints
- `racquets`: optional racquet boxes
- `racquet_candidates`: optional weak pose-guided line candidates
- `shuttle`: optional small-motion shuttle candidate
- top-level `shuttle`: TrackNetV3 points when `TRACKNET_TRACKNET_FILE` is
  configured and inference succeeds
- `tracknet`: status/quality/point-count metadata for the shuttle tracker

The app uses `player_quality` to choose the GPU crop path and
`shuttle_quality` to decide whether the final render should draw the shuttle
halo.
