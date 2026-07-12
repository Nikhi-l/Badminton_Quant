# Future vision — school sports streaming (owner, 2026-07-12)

> Recorded so it's easy to remember and steer toward. **Not planned work** —
> nothing here enters the remediation queue until the owner promotes it.
> Near-term execution stays in `PRIMARY_PRD.md` §16.

## The end state

Baddy becomes a **sports streaming solution for schools**:

- We partner with a school: cameras installed on their courts, video-feed
  access secured (hardware expected soon).
- Students install the **Baddy app**; their matches stream live,
  professionally produced, to parents and their social circle — a premium
  offering for the school community.
- "Professionally produced" means:
  - **multiple views** of the court with proper live camera cuts,
  - strong **clipping** (in-play only — the rally-break/in-play work is the
    foundation), smart **camera positioning**,
  - **player identification** (shirt/jersey tracking) so the stream follows
    and labels the right student,
  - a live **scoreboard** overlaid on the stream.

## How current work ladders into it

| Today's module | Becomes |
|---|---|
| Rally/in-play index (TASK-040) | live clipping + auto camera-cut triggers |
| Virtual camera + validation | multi-view director logic |
| Court homography / interpolation layer | per-camera calibration for the multi-view rig (canonical single-cam: behind players, ~10 ft up, full court visible) |
| Player ids (BoT-SORT + identity map) | shirt/jersey-level student identification |
| analysis.json signals (hits, speeds, movement, audio) | live match stats + scoreboard inputs |
| Schools platform (TASK-026 auth/tenancy/roster) | the account + distribution layer for students, coaches, parents |

## Also on deck

- **UI revamp** task is ongoing — fold it into this direction.
- **App design** for the student streaming app (to be designed).
- Hardware selection/procurement once a pilot school is confirmed.
