# TASK-002: Rebuild the RunPod GPU worker from source

**Status:** image ready — deploy blocked (Cycle 3, 2026-06-21)
**Branch:** `feat/TASK-001-shuttle-follow-camera`
**PRD section:** §16 P0 (worker rebuild); §4a GPU pipeline

## Goal
The GPU worker never booted: every "clean" image was a re-wrap of the broken one
and inherited a multi-arch OCI attestation index the RunPod runtime can't run.
Build a true from-source single-arch image, deploy it, and verify GPU shuttle
tracking works on baddyai.com.

## Acceptance criteria
- [x] Clean from-source image built + pushed (single-arch docker v2 manifest).
      → `baddy-vision-worker:tracknet-src-20260621` (sha256:972b95f2…), verified.
- [x] RunPod endpoint `radst7uhhhl6q0` points at the new image and a worker boots
      healthy. → fresh key set; created template `lwjbpdx6qf`; PATCH endpoint
      templateId + `workersMax: 2` (was 0!). Health: `ready:2, unhealthy:0`.
- [x] Worker handler runs. → boot-test job FAILED only on the dummy proxy URL
      (`404 example.com/proxy.mp4` from `handler.py:498 _download`), executionTime
      257ms — proves container boots + RunPod SDK + handler execute.
- [ ] A real job returns TrackNetV3 shuttle points from the GPU. → do via
      baddyai.com (token-gated proxy hosting); public-bucket shortcut correctly
      blocked (don't expose user video).
- [ ] baddyai.com runs a `shuttle=tracknetv3` job end-to-end. → needs the SERVER's
      `.env` RUNPOD_API_KEY refreshed too (old key 401s) + redeploy.

## Deploy steps (once a valid RUNPOD_API_KEY is set, or via console)
- API: update endpoint template image → `…/baddy-runpod/baddy-vision-worker:tracknet-src-20260621`.
- Console: RunPod → Serverless → endpoint → New Release → set the image tag above.
- Then: send a test job; confirm worker `ready` + shuttle points returned.

## Verification commands
- `gcloud builds submit --config runpod_worker/cloudbuild.yaml runpod_worker/` (done)
- manifest: `curl …/manifests/tracknet-src-20260621` → docker v2, single-arch (done)

## Risks / rollback
- If the new image also fails health → pull worker logs (now that it's from-source,
  logs should appear) to diagnose.
- rollback: endpoint can point back at the previous tag.
