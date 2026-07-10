"""TASK-031: identity plumbing — softer worker-id acceptance and the spatial
guard on fragment merging (height-only merging fused same-height doubles
partners into one id)."""
from app.main import _ids_from_worker, _relabel_merged


def test_worker_ids_accepted_at_70_percent_coverage():
    rows = []
    for i in range(10):
        rows.append([1 if i < 7 else None, 2 if i < 7 else None])
    out = _ids_from_worker(rows)
    assert out is not None            # old 0.9 cliff discarded these


def test_worker_ids_rejected_below_60_percent():
    rows = [[1 if i < 5 else None] for i in range(10)]
    assert _ids_from_worker(rows) is None


def _fragment_frames(second_start_x):
    """One track at x=0.2 for t 0..1, then a second same-height track appearing
    at t=2 at ``second_start_x``. Both apparent height 0.3."""
    frames, ids = [], []
    for i in range(6):
        frames.append((i / 5.0, [(0.2, 0.7, 0.3)]))
        ids.append([0])
    for i in range(6):
        frames.append((2.0 + i / 5.0, [(second_start_x, 0.7, 0.3)]))
        ids.append([1])
    return frames, ids


def test_fragments_merge_when_spatially_continuous():
    frames, ids = _fragment_frames(second_start_x=0.25)
    out = _relabel_merged(frames, ids)
    flat = {i for row in out for i in row}
    assert flat == {0}                # re-acquired player folds into one id


def test_fragments_stay_separate_across_the_court():
    # Same height, non-overlapping in time, but half a court apart: this is the
    # doubles-partner case that height-only merging got wrong.
    frames, ids = _fragment_frames(second_start_x=0.85)
    out = _relabel_merged(frames, ids)
    flat = {i for row in out for i in row}
    assert len(flat) == 2
