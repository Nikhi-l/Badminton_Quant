"""TASK-031: identity plumbing — softer worker-id acceptance and the spatial
guard on fragment merging (height-only merging fused same-height doubles
partners into one id). TASK-044 adds the slot-reuse distance gate: a
similarly sized detection must not inherit an old id across the court."""
from app.main import _ids_from_worker, _relabel_merged, _stable_ids


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


def test_sized_slot_reuse_requires_spatial_plausibility():
    """TASK-044: the fallback that reuses a same-height slot must not hand a
    cross-court detection the old id — that smuggled an identity switch past
    every consumer. A distant same-height detection gets a fresh id."""
    frames = []
    for i in range(6):                       # one player, bottom-left
        frames.append((i / 6.0, [(0.20, 0.70, 0.30)]))
    for i in range(6, 12):                   # same height, opposite corner
        frames.append((i / 6.0, [(0.88, 0.25, 0.30)]))
    ids = _stable_ids(frames)
    flat = [row[0] for row in ids]
    assert len(set(flat)) == 2, f"cross-court inheritance: {flat}"
    assert flat[5] != flat[6]                # the switch happens at the jump


def test_sized_slot_reuse_still_covers_a_fast_lunge():
    """The reuse path exists for real lunges that outrun the match gate —
    those must keep their id (TASK-021 churn regression, now with the gate)."""
    frames = []
    x = 0.30
    for i in range(12):
        x = 0.30 if (i // 3) % 2 == 0 else 0.66   # 0.36 jumps between samples
        frames.append((i / 6.0, [(x, 0.70, 0.30)]))
    ids = _stable_ids(frames)
    flat = {row[0] for row in ids}
    assert flat == {0}, f"lunge churned ids: {sorted(flat)}"
