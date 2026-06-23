# Review intake — Studio camera + editor feedback (2026-06-21)

Source: user (product owner) review of the live Studio editor on baddyai.com, with
two screenshots (Reel + Source rallies framing views). Per the harness external-input
rule, this is a learning input; accepted items are queued in PRIMARY_PRD §16 and
become `.agent/tasks` files.

## Questions answered (not work items)
- **"Is the video cropped before shuttle tracking?"** No. Order (`run.py`): combine →
  probe → **proxy (downscale to 480p, not a crop)** → Gemini rallies → **vision /
  TrackNetV3 on the full proxy frame** → tracking (virtual camera) → **render (crop
  from the original full-res)** → validate → stitch. Tracking sees the whole frame;
  the 9:16 crop is a post-process at render. → a user-controlled camera can be a
  render-time transform; no re-tracking needed.
- **"What's the use of the Captions / Shuttle / Pose timeline lanes if not editable?"**
  Valid — today they are display-only. Accepted → make them interactive (TASK-012).

## Triaged into the remediation queue
| Item (from feedback) | Decision | Task |
|---|---|---|
| "Weird circle appears at random places" — shuttle overlay sits at a fixed/last position when there is no tracked point at the current time; remove it when untracked (same for pose). | Accept (bug) | TASK-011 |
| Pose overlay shows a static decorative figure, not real keypoints ("I don't see any pose data generated"). | Accept | TASK-011 |
| Timeline lanes (Shuttle/Pose/Captions) must be configurable — toggle overlays from the timeline; in Source mode show the shuttle track across the WHOLE video timeline. | Accept | TASK-012 |
| Add a landscape view (original 16:9), not only the 9:16 portrait crop; and let the user manually reframe in **Source rallies** to pick which portions of the original landscape video to highlight. | Accept | TASK-013 |
| Configurable virtual camera: choose target = **track shuttle / track a player / fixed point**; plus the existing zoom + pan X/Y; and **keyframes** so the user can switch (e.g. shuttle→player) over time. Bake the camera plan into the exported reel. | Accept (major) | TASK-014 |
| **Person/player tracking** — detect + track players; expose as a camera follow-target and a timeline lane/overlay (also feeds TASK-014's "player" target). | Accept | TASK-015 |

## Notes / dependencies
- TASK-014 (camera targets + keyframes) depends on TASK-015 (player tracks for the
  "player" target) and a **backend render contract** that accepts a per-job camera
  plan (the render already builds a `FocusPath`; extend it to consume a
  user-authored keyframed plan). TASK-011/012/013 are front-end-leaning slices.
- Overlay correctness (TASK-011) is the cheapest visible win; do it first.
