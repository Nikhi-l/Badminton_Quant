"""TASK-045: retroactive track hygiene for broadcast job 713a86e5db5a.

A July-10 job (worker `doubles-20260708`, pre tracker-persist fix; stored
before the TASK-042 court gate) showed 4 tracked "players" in a singles match
with poses juggling between them. Two root causes, each with a guard here:

1. Worker track ids were reborn every frame, degrading to CONFIDENCE-RANK
   aliases: "id 2" chained different humans (far player, line judges) into one
   track teleporting across the frame (31% of same-id steps physically
   impossible vs 4% for the one real track). Coverage alone can't see this —
   `_ids_from_worker` now checks same-id step plausibility and falls back to
   the motion+size heuristic when ids are incoherent.

2. Results stored before TASK-042 keep ungated staff boxes forever (48% of
   this job's boxes had feet outside even the expanded quad). The court gate
   now ALSO retro-applies at the public samplers, fixing stored jobs without
   a reprocess. Pose gating uses the bbox bottom (hallucinated ankles of
   board-cut spectators landed inside the quad), and a pose-only gate call now
   gets the same fail-open protection as boxes.

Fixture `tests/fixtures/job713_tracks.json` is a trimmed slice of the real
job's stored tracks (reconstructed canonical shapes) with its cv-detected
corners.
"""
import json
import math
from pathlib import Path

from app.main import _ids_from_worker, _sample_player_track, _sample_pose_track
from app.pipeline.track import court_player_gate

FIXTURE = json.loads(
    (Path(__file__).resolve().parents[1] / "fixtures" / "job713_tracks.json").read_text())

DT = 0.408   # the job's real sample spacing (73s rally under the 180-frame cap)

NEAR = (0.516, 0.689, 0.234)
FAR = (0.473, 0.421, 0.162)
STAFF_R = (0.850, 0.545, 0.157)
STAFF_T = (0.380, 0.300, 0.120)


def _frames_ids(assignments):
    """Build (frames, worker_ids) for _ids_from_worker from per-frame
    [(det, worker_id), ...] assignments."""
    frames, ids = [], []
    for i, row in enumerate(assignments):
        frames.append((round(i * DT, 3), [d for d, _ in row]))
        ids.append([wid for _, wid in row])
    return frames, ids


def test_coherent_worker_ids_survive_the_guard():
    rows = []
    for i in range(12):
        drift = 0.01 * (i % 3)
        rows.append([((NEAR[0] + drift, NEAR[1], NEAR[2]), 1),
                     ((FAR[0] - drift, FAR[1], FAR[2]), 2),
                     ((STAFF_R[0], STAFF_R[1] + drift, STAFF_R[2]), 3),
                     ((STAFF_T[0], STAFF_T[1], STAFF_T[2]), 4)])
    frames, ids = _frames_ids(rows)
    assert _ids_from_worker(ids, frames) is not None


def test_rank_alias_worker_ids_rejected():
    """The rebirth bug: ids restart every frame, so 'id 2' means '2nd most
    confident detection', hopping between the far player and two judges."""
    others = [FAR, STAFF_R, STAFF_T]
    rows = []
    for i in range(12):
        row = [((NEAR[0], NEAR[1], NEAR[2]), 1)]   # near always outranks
        for slot, person in enumerate(others[i % 3:] + others[:i % 3]):
            row.append(((person[0], person[1], person[2]), 2 + slot))
        rows.append(row)
    frames, ids = _frames_ids(rows)
    assert _ids_from_worker(ids, frames) is None   # heuristic takes over


def test_guard_needs_geometry_and_keeps_legacy_signature():
    rows = [[1, 2] for _ in range(10)]
    assert _ids_from_worker(rows) is not None      # no frames -> old behavior


def test_sampler_recovers_stable_ids_from_alias_tracks():
    """End to end through _sample_player_track: with rank-alias track_ids the
    guard rejects them and the heuristic yields ids that do NOT teleport
    (the stored job's chained ids spanned x_range 0.63)."""
    others = [FAR, STAFF_R, STAFF_T]
    players = []
    for i in range(24):
        boxes = [{"x1": NEAR[0] - 0.06, "y1": NEAR[1] - NEAR[2] / 2,
                  "x2": NEAR[0] + 0.06, "y2": NEAR[1] + NEAR[2] / 2,
                  "confidence": 0.9, "track_id": 1}]
        for slot, (cx, cy, h) in enumerate(others[i % 3:] + others[:i % 3]):
            boxes.append({"x1": cx - 0.04, "y1": cy - h / 2,
                          "x2": cx + 0.04, "y2": cy + h / 2,
                          "confidence": 0.6 - 0.05 * slot, "track_id": 2 + slot})
        players.append({"t": round(i * DT, 3), "boxes": boxes})
    track = _sample_player_track(players)
    span = {}
    for f in track:
        for b in f["boxes"]:
            xs = span.setdefault(b["id"], [])
            xs.append(b["x"])
    worst = max(max(xs) - min(xs) for xs in span.values())
    assert worst < 0.2, f"an id still teleports (x_range {worst:.2f})"


def test_job713_retro_court_gate_keeps_only_the_two_players():
    players = FIXTURE["players"]
    track = _sample_player_track(players, corners=FIXTURE["corners"])
    assert track
    counts = [len(f["boxes"]) for f in track]
    assert sum(c == 2 for c in counts) >= 0.9 * len(counts)
    total_in = sum(len(f["boxes"]) for f in players)
    total_out = sum(counts)
    assert total_out <= 0.65 * total_in       # the staff boxes are gone
    ids = {b["id"] for f in track for b in f["boxes"]}
    assert ids <= {0, 1, 2}                   # 2 players + at most a transient


def test_job713_pose_gate_agrees_with_box_gate():
    qt = _sample_pose_track(FIXTURE["poses"], corners=FIXTURE["corners"])
    counts = [len(f["people"]) for f in qt]
    assert sum(c == 2 for c in counts) >= 0.9 * len(counts)


def test_job713_without_corners_is_unchanged_legacy():
    track = _sample_player_track(FIXTURE["players"])
    ids = {b["id"] for f in track for b in f["boxes"]}
    assert len(ids) == 4                      # old jobs keep old behavior


def test_pose_only_gate_fails_open_on_a_wrong_quad():
    """A quad that excludes every person means the geometry is wrong, not the
    people — the pose-only path used to skip this check and blank everything."""
    tiny = [[0.90, 0.05], [0.99, 0.05], [0.99, 0.15], [0.90, 0.15]]
    _, gated = court_player_gate([], FIXTURE["poses"], tiny)
    assert sum(len(f["people"]) for f in gated) == \
        sum(len(f["people"]) for f in FIXTURE["poses"])


def test_gate_math_on_the_real_job_numbers():
    """Direct check with the measured geometry: feet of every surviving box
    are inside the expanded quad; the line-judge box is not."""
    gp, _ = court_player_gate(FIXTURE["players"], [], FIXTURE["corners"])
    judge = sum(1 for f in gp for b in f["boxes"]
                if math.hypot((b["x1"] + b["x2"]) / 2 - STAFF_R[0],
                              b["y2"] - (STAFF_R[1] + STAFF_R[2] / 2)) < 0.05)
    assert judge == 0
