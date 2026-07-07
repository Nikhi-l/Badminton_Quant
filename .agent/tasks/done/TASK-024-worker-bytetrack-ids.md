# TASK-024: Worker-side player identity via ByteTrack

**Status:** done (implemented; worker image rollout tracked in ledger)
**Branch:** `feat/TASK-024-worker-bytetrack-ids`
**Base SHA:** `7137bcb`
**PRD section:** §16 remediation (review 2026-07-07: "proper pose data of both
the players")

## Goal
Move player identity into the RunPod worker: use ultralytics tracking
(`model.track(..., persist=True, tracker="bytetrack.yaml")`) per rally so each
box/pose carries a tracker id from the source, instead of the serve-time
`_stable_ids` heuristic re-deriving identity from sampled centroids. Keeps
`_stable_ids` as the fallback for payloads without ids (legacy + CPU path).

## Why
Server-side matching is provably stable on the fixture but real footage still
fragments identity across long occlusions (a P3 appears when a player re-enters
with a different apparent height). The tracker sees every frame at full rate
and motion-models the gap.

## Plan
1. `runpod_worker/handler.py`: switch `_detect_pose` to `model.track` with
   per-rally tracker reset; emit `track_id` on each player box and pose person.
2. `gpu.py` `_frames_from`/`_pose_people`: carry `track_id` through canonical
   `players`/`poses`; `main.py` samplers prefer worker ids when present
   (relabel near-player-first still applies for P1 semantics).
3. Bump WORKER_VERSION, rebuild via Cloud Build, patch template, verify
   `worker_version` + two stable ids on a real GPU job.

## Acceptance criteria
- [ ] Real GPU job: exactly 2 player ids across every rally of a singles game (pending image rollout)
- [x] Fixture + unit tests still pass (fallback path untouched) → tests/unit/test_worker_track_ids.py (4 tests)

## Risks / rollback
- model.track adds per-frame state; verify worker latency budget holds.
- rollback: previous worker template remains deployable.
