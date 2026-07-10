"""TASK-031: camera player tracks — id grouping, interpolation, ghost expiry,
near/far hysteresis. The old 2-slot heuristic nearest-held ~6 Hz samples (the
camera stair-stepped behind players), never expired slots (ghost players
constrained pan/zoom forever), and ignored worker tracker ids entirely."""
import numpy as np

from app.pipeline.track import _group_player_tracks, _track_at, _two_player_tracks


def _frame(t, boxes):
    out = []
    for cx, cy, tid in boxes:
        b = {"x1": cx - 0.05, "y1": cy - 0.15, "x2": cx + 0.05, "y2": cy + 0.15,
             "confidence": 0.9}
        if tid is not None:
            b["track_id"] = tid
        out.append(b)
    return {"t": t, "boxes": out}


def test_worker_ids_group_crossing_players():
    # Two players crossing paths at the same height: id-blind matching swaps
    # them at the crossover, track_id grouping must not.
    frames = []
    for i in range(13):
        t = i / 6.0
        k = i / 12.0
        frames.append(_frame(t, [(0.2 + 0.6 * k, 0.6, 7), (0.8 - 0.6 * k, 0.6, 9)]))
    tracks = _group_player_tracks(frames)
    assert len(tracks) == 2
    for tr in tracks:
        dx = np.diff(tr["cx"])
        # each grouped track moves monotonically — no identity swap mid-cross
        assert (dx > 0).all() or (dx < 0).all()


def test_interpolation_between_samples():
    frames = [_frame(0.0, [(0.2, 0.7, 1)]), _frame(1.0, [(0.4, 0.7, 1)])]
    tracks = _group_player_tracks(frames)
    assert len(tracks) == 1
    pos = _track_at(tracks[0], 0.5)
    assert pos is not None
    assert abs(pos[0] - 0.3) < 1e-6      # linear midpoint, not nearest-hold


def test_track_expires_instead_of_ghosting():
    # Track vanishes at t=1.0; by t=3.0 it must contribute nothing.
    frames = [_frame(0.0, [(0.2, 0.7, 1)]), _frame(1.0, [(0.25, 0.7, 1)])]
    tracks = _group_player_tracks(frames)
    assert _track_at(tracks[0], 1.2) is not None      # short hold is fine
    assert _track_at(tracks[0], 3.0) is None          # ghost expired
    res = _two_player_tracks(frames, np.array([3.0]))
    assert res[0] == (None, None)


def test_near_far_assignment_and_hysteresis():
    # Near player (cy 0.75) and far player (cy 0.35), stable across frames.
    frames = [_frame(i / 6.0, [(0.4, 0.75, 1), (0.6, 0.35, 2)]) for i in range(13)]
    times = np.arange(0.0, 2.0, 1 / 30)
    res = _two_player_tracks(frames, times)
    for near, far in res:
        assert near is not None and far is not None
        assert near[1] > far[1]           # near = larger cy

    # Two players briefly swapping depth by a hair must NOT swap the anchor:
    # cy difference stays under the 0.05 hysteresis margin.
    frames = []
    for i in range(13):
        t = i / 6.0
        wob = 0.02 if i % 2 else -0.02
        frames.append(_frame(t, [(0.4, 0.60 + wob, 1), (0.6, 0.60 - wob, 2)]))
    res = _two_player_tracks(frames, np.arange(0.2, 1.8, 1 / 30))
    # anchor identity is stable: the near slot x stays on one player's side
    xs = [near[0] for near, _ in res if near]
    assert max(xs) - min(xs) < 0.15


def test_anonymous_boxes_group_by_proximity():
    frames = [_frame(i / 6.0, [(0.2 + 0.01 * i, 0.7, None)]) for i in range(6)]
    tracks = _group_player_tracks(frames)
    assert len(tracks) == 1
    assert len(tracks[0]["ts"]) == 6
