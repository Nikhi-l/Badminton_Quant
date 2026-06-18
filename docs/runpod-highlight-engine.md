# Runpod highlight engine contract

This repo now treats GPU vision as an optional enrichment stage. The existing CPU
pipeline still finishes a reel if Runpod is not configured, queues too long, or
returns weak detections.

## Serverless API

Baddy submits long-running GPU work with Runpod Serverless async requests:

- `POST https://api.runpod.ai/v2/{RUNPOD_ENDPOINT_ID}/run`
- poll `GET https://api.runpod.ai/v2/{RUNPOD_ENDPOINT_ID}/status/{run_id}`

Runpod's docs describe `/run` as the async path and `/status` as the result
retrieval path for queue-based endpoints.

## Required app environment

```bash
PUBLIC_BASE_URL=https://136-113-208-173.sslip.io
GPU_ARTIFACT_TOKEN=<long random secret>
RUNPOD_ENDPOINT_ID=<endpoint id>
RUNPOD_API_KEY=<runpod api key>
RUNPOD_TIMEOUT_SEC=1200
RUNPOD_POLL_SEC=5
SHUTTLE_MASK_MIN_QUALITY=0.65
SHUTTLE_MASK_MIN_CONF=0.55
COACH_ENABLED=1
COACH_MODEL=gemini-3.5-flash
COACH_FRAME_COUNT=4
COACH_FRAME_HEIGHT=360
```

The GCP VM deploy copies the repo `.env` into `/opt/baddy/.env`, and
`app/config.py` loads that file on service start. After setting the Runpod vars,
redeploy or restart `baddy.service`.

`PUBLIC_BASE_URL` and `GPU_ARTIFACT_TOKEN` are required because the worker pulls
the proxy from a signed, short-lived URL:

```text
/api/gpu-artifacts/{job_id}/proxy.mp4?token=...
```

Only `proxy.mp4` is exposed, and only when the HMAC token is valid.

## Worker image

The Runpod worker lives in `runpod_worker/`:

```bash
cd runpod_worker
docker build -t baddy-vision-worker:latest .
docker tag baddy-vision-worker:latest <registry>/baddy-vision-worker:latest
docker push <registry>/baddy-vision-worker:latest
```

For shuttle-precise tracking, build the image with TrackNetV3 cloned in:

```bash
docker build \
  --build-arg INSTALL_TRACKNET=1 \
  -t baddy-vision-worker:tracknet .
```

TrackNetV3 checkpoints are distributed separately by the upstream project via
the checkpoints link in the
[TrackNetV3 README](https://github.com/qaz812345/TrackNetV3). Place
`TrackNet_best.pt` and optionally `InpaintNet_best.pt` in
`runpod_worker/models/tracknet/`; the Docker image copies that directory to
`/models/tracknet`.

Use the preflight and guarded build helper before spending Runpod credits:

```bash
bash scripts/runpod_preflight.sh
cd runpod_worker
BADDY_WORKER_IMAGE=<registry>/baddy-vision-worker:tracknet ./build_and_push.sh
PUSH=1 BADDY_WORKER_IMAGE=<registry>/baddy-vision-worker:tracknet ./build_and_push.sh
```

After pushing a new image, update the existing endpoint template with a
management-scoped Runpod API key:

```bash
RUNPOD_MANAGEMENT_API_KEY=... \
  python scripts/runpod_update_endpoint_image.py \
  --image <registry>/baddy-vision-worker:tracknet \
  --apply
```

The ordinary endpoint `/run` key is not enough for this management operation.

Create a Runpod Serverless queue endpoint from that image. Use a GPU with enough
VRAM for the chosen YOLO pose/racquet models; a T4/L4 class worker is enough for
the current sampling path.

Registry auth must survive cold starts. Do not rely on a short-lived local GCP
OAuth token for Runpod pulls. Use one of these durable options:

- Public read-only pulls for the Artifact Registry repo, if the worker image is
  acceptable to distribute publicly.
- A private registry credential that Runpod can store and refresh safely.
- A registry that already has durable Runpod pull credentials, then update the
  endpoint image to that tag.

Worker environment:

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
# Optional; set only if the file is present.
TRACKNET_INPAINTNET_FILE=/models/tracknet/InpaintNet_best.pt
TRACKNET_BATCH_SIZE=8
TRACKNET_TIMEOUT_SEC=900
```

`RACQUET_MODEL` is optional until we train or source a badminton racquet detector.
Without it, the worker still returns player pose, TrackNet/motion shuttle
signals, and weak pose-guided racquet candidates for Gemini context. Without
Ultralytics model loading, it returns a valid low-confidence fallback payload so
the CPU camera path still completes.

## Endpoint smoke test

After the endpoint is created and the app `.env` has `RUNPOD_ENDPOINT_ID`,
`RUNPOD_API_KEY`, `PUBLIC_BASE_URL`, and `GPU_ARTIFACT_TOKEN`, verify the real
queue before trusting production jobs:

```bash
# On the GCP VM, use an existing completed/processing job id that has proxy.mp4.
cd /opt/baddy
sudo -u baddy ./venv/bin/python scripts/runpod_smoke.py \
  --job-id <app_job_id> \
  --start 0 \
  --end 8 \
  --timeout-sec 600 \
  --save /tmp/baddy-runpod-smoke.json
```

For a one-off public proxy URL, skip signed artifact generation:

```bash
./venv/bin/python scripts/runpod_smoke.py \
  --proxy-url "https://.../proxy.mp4" \
  --start 0 \
  --end 8
```

The smoke submits the same `baddy.vision.v1` shape as the app, polls Runpod
`/status`, canonicalizes the output with `app.pipeline.gpu`, and fails if the
worker response is missing player, pose, racquet, or shuttle fields. It prints a
compact quality/sample summary and never prints the Runpod API key.

## Request sent to the worker

```json
{
  "input": {
    "contract": "baddy.vision.v1",
    "job_id": "abc123",
    "sport": "badminton",
    "proxy_url": "https://.../api/gpu-artifacts/abc123/proxy.mp4?token=...",
    "proxy_name": "proxy.mp4",
    "rallies": [
      {
        "rally_index": 1,
        "start": 12.0,
        "end": 28.0,
        "dur": 16.0,
        "note": "long rally",
        "intensity": 4
      }
    ],
    "tasks": ["players", "pose", "racquet", "shuttle"],
    "return_normalized_coordinates": true
  }
}
```

All returned coordinates should be normalized to the proxy frame: `0..1` for x/y.
Timestamps should be absolute source seconds. Relative rally timestamps are also
tolerated; the app converts values inside the rally duration back to source time.

## Expected worker output

The app accepts a few aliases, but this is the preferred shape:

```json
{
  "contract": "baddy.vision.v1",
  "engine": "runpod-yolo-tracknetv3-gemini-flash-ready-v1",
  "message": "ok",
  "rallies": [
    {
      "rally_index": 1,
      "player_quality": 0.88,
      "pose_quality": 0.74,
      "racquet_quality": 0.63,
      "shuttle_quality": 0.81,
      "frames": [
        {
          "t": 12.3,
          "players": [
            {"box": [0.18, 0.22, 0.36, 0.92], "confidence": 0.94},
            {"box": [0.62, 0.18, 0.78, 0.86], "confidence": 0.91}
          ],
          "shuttle": {"x": 0.51, "y": 0.34, "confidence": 0.83}
        }
      ],
      "shuttle": [
        {"t": 12.3, "x": 0.51, "y": 0.34, "confidence": 0.82, "source": "tracknetv3"}
      ],
      "tracknet": {"enabled": true, "status": "ok", "points": 128, "quality": 0.78}
    }
  ]
}
```

## How Baddy uses it

- Player boxes with enough coverage drive a vision-assisted crop that tries to
  keep both players visible.
- Shuttle points are included in that crop only when `shuttle_quality` passes the
  configured quality threshold.
- When TrackNetV3 succeeds, the app marks `summary.shuttle_engine=tracknetv3`
  and Studio displays the TrackNetV3 shuttle signal.
- The renderer draws a shuttle halo only when the rally has `mask_enabled=true`
  after quality checks.
- Pose and racquet scores are surfaced in Studio, and pose/racquet sample counts
  are carried into the coach prompt so Gemini can distinguish a real measured
  signal from a sparse detector guess.
- Until `RACQUET_MODEL` is configured, the worker can emit weak
  `racquet_candidates` from YOLO wrist keypoints plus nearby line evidence.
  These candidates are labeled separately and never upgrade `racquet_quality`.
- Completed jobs preserve sanitized worker `models` status so Studio can show
  YOLO pose, TrackNetV3, and whether the racquet detector is still pending.
- Gemini Flash coach notes consume the same measured features plus a small set
  of representative proxy frames after clip validation. The coach prompt is
  intentionally "measure then verbalize": frames provide visible context, but it
  avoids stroke, contact, grip, shuttle-flight, and body-mechanics claims when
  the corresponding Runpod quality scores are low.
- `GET /api/vision/status` reports non-secret Runpod/Gemini readiness without
  submitting a GPU job or consuming Runpod credits.

## Suggested worker stack

- People and racquet: YOLO/RF-DETR style detector, returning normalized boxes.
- Pose: MediaPipe/RTMPose style landmarks, summarized into quality and metrics.
- Shuttle: temporal tracker such as TrackNetV3 or equivalent; avoid single-frame
  shuttle-only YOLO as the primary signal.
- Gemini Flash multimodal: use measured CV features plus selected frames to
  verbalize coaching observations, not raw video alone. Keep frame count low so
  the coach pass stays cheap and reviewable.

## Console checklist

1. Open Runpod Console -> Serverless.
2. Create or select the Baddy vision endpoint.
3. Set the container image to the pushed `baddy-vision-worker` image.
4. Set worker env vars above.
5. In the Requests tab, submit a test payload using a fresh signed `proxy_url`
   from the app.
6. Copy the endpoint ID into the app `.env` as `RUNPOD_ENDPOINT_ID`.
7. Run `scripts/runpod_smoke.py` from the VM and keep the saved canonical output
   as endpoint evidence.
8. Confirm the app job status reaches `vision`, `tracking`, and `coach` without
   falling back to `GPU coach engine failed`.
