"""TASK-041: Gemini frame evaluator (verdict application) + annotated drawing.

The evaluator prunes stored player/pose tracks to the confirmed main-court
players BEFORE the camera plans its path; it must fail open (implausible or
wrong-shaped verdicts change nothing). Drawing primitives must render onto
raw frames without touching geometry they weren't given.
"""
import numpy as np

from app.pipeline import annotate, evaluate


def _rally(track_ids_per_frame):
    frames = []
    for i, ids in enumerate(track_ids_per_frame):
        frames.append({"t": i / 6, "boxes": [
            {"x1": 0.1 * t, "y1": 0.2, "x2": 0.1 * t + 0.08, "y2": 0.5,
             "confidence": 0.8, "track_id": t} for t in ids]})
    poses = [{"t": f["t"], "people": [
        {"track_id": b["track_id"], "confidence": 0.8,
         "keypoints": [{"x": 0.5, "y": 0.5, "confidence": 0.9}] * 17}
        for b in f["boxes"]]} for f in frames]
    return {"players": frames, "poses": poses, "player_quality": 0.8}


def test_apply_verdict_prunes_judged_and_other_rallies():
    # Judged rally: players 1,2 + background 7. Other rally (fresh id space):
    # persistent 3,4 + intermittent background 9.
    judged = _rally([[1, 2, 7]] * 10)
    other = _rally([[3, 4, 9] if i % 4 == 0 else [3, 4] for i in range(12)])
    vision = {"rallies": [judged, other]}

    stats = evaluate.apply_verdict(vision, {
        "main_court_players": 2, "keep_track_ids": [1, 2], "boxes_correct": True,
    }, judged_index=0)

    assert stats["applied"] and stats["removed_boxes"] > 0
    assert all({b["track_id"] for b in f["boxes"]} == {1, 2} for f in judged["players"])
    assert all({p["track_id"] for p in f["people"]} == {1, 2} for f in judged["poses"])
    # Unevaluated rally keeps its 2 most-persistent ids — 9 is gone.
    kept_other = {b["track_id"] for f in other["players"] for b in f["boxes"]}
    assert kept_other == {3, 4}


def test_apply_verdict_fails_open():
    rally = _rally([[1, 2, 7]] * 4)
    before = sum(len(f["boxes"]) for f in rally["players"])
    for bad in (
        {"main_court_players": 2, "keep_track_ids": [1, 2], "boxes_correct": False},
        {"main_court_players": 9, "keep_track_ids": [1, 2], "boxes_correct": True},
        {"main_court_players": 2, "keep_track_ids": [], "boxes_correct": True},
    ):
        stats = evaluate.apply_verdict({"rallies": [rally]}, bad, judged_index=0)
        assert not stats["applied"]
    assert sum(len(f["boxes"]) for f in rally["players"]) == before


def test_annotate_frame_draws_all_three_layers():
    frame = np.zeros((240, 320, 3), dtype=np.uint8)
    vision = {
        "players": [{"t": 5.0, "boxes": [
            {"x1": 0.1, "y1": 0.2, "x2": 0.35, "y2": 0.8, "confidence": 0.9, "track_id": 1}]}],
        "poses": [{"t": 5.0, "people": [
            {"track_id": 1, "keypoints": [
                {"x": 0.2 + 0.005 * i, "y": 0.3 + 0.02 * i, "confidence": 0.9}
                for i in range(17)]}]}],
        "shuttle": [{"t": 4.7 + i * 0.05, "x": 0.5 + i * 0.01, "y": 0.4,
                     "confidence": 0.9} for i in range(7)],
    }
    out = annotate.annotate_frame(frame, vision, 5.0)
    assert out.any()                                   # something was drawn
    # shuttle marker lands near (0.5+0.3, 0.4) → white core pixel present
    assert (out[:, :, :] == 255).any()


def test_annotate_frame_skips_stale_tracks():
    frame = np.zeros((120, 160, 3), dtype=np.uint8)
    vision = {"players": [{"t": 1.0, "boxes": [
        {"x1": 0.1, "y1": 0.1, "x2": 0.3, "y2": 0.5, "confidence": 0.9, "track_id": 0}]}],
        "poses": [], "shuttle": [{"t": 1.0, "x": 0.5, "y": 0.5, "confidence": 0.9}]}
    out = annotate.annotate_frame(frame, vision, 9.0)   # 8s from any data
    assert not out.any()                                # honest blank, no stale marker

def test_render_annotated_unpacks_iter_frames_pairs(monkeypatch, tmp_path):
    """Regression: media.iter_frames yields (index, frame) PAIRS; wrapping it
    in enumerate fed tuples to numpy and crashed the first annotated bake
    ('inhomogeneous shape'). Pin the generator contract end-to-end with the
    media layer mocked."""
    from types import SimpleNamespace
    from app.pipeline import annotate as ann, media

    written = []

    class _FakeWriter:
        def __init__(self, dst, w, h, fps, audio_src, a0, a1):
            self.dst = dst
        def write(self, frame):
            assert isinstance(frame, np.ndarray) and frame.ndim == 3
            written.append(frame.shape)
        def close(self):
            Path(self.dst).write_bytes(b"x")

    def _fake_iter(path, t0, t1, *, fps, gray=False):
        for i in range(5):
            # exactly what media.iter_frames yields: a READ-ONLY frombuffer
            # view (cv2 refuses to draw on it — the second bake crash)
            frame = np.frombuffer(bytes(120 * 160 * 3), dtype=np.uint8).reshape(120, 160, 3)
            yield i, frame

    from pathlib import Path
    (tmp_path / "proxy.mp4").write_bytes(b"x")
    monkeypatch.setattr(media, "probe", lambda p: SimpleNamespace(
        width=160, height=120, fps=30.0, duration=100.0))
    monkeypatch.setattr(media, "iter_frames", _fake_iter)
    monkeypatch.setattr(media, "FrameWriter", _FakeWriter)

    result = {"rallies": [{"start": 10.0, "end": 12.0, "vision": {
        # a real box so cv2 actually DRAWS on the read-only-derived frame
        "players": [{"t": 10.5, "boxes": [{"x1": 0.2, "y1": 0.2, "x2": 0.5,
                                           "y2": 0.8, "confidence": 0.9, "track_id": 1}]}],
        "poses": [], "shuttle": []}}]}
    out = ann.render_annotated(tmp_path, result, log=lambda m: None)

    assert out is not None and out.name == "annotated.mp4"
    assert len(written) == 5 and all(s == (120, 160, 3) for s in written)


def test_post_gate_quality_recovers_cleaned_track():
    """Regression: the worker scores its RAW track — a rally that was mostly
    background-court junk reads 0.0 even after the court gate cleaned it,
    starving the shuttle-follow camera. The post-gate recompute must score
    the surviving main-court flight on its own cadence."""
    from app.pipeline.track import shuttle_track_quality
    clean = [{"t": 5.0 + i / 30, "x": 0.4 + 0.003 * i, "y": 0.5, "confidence": 0.9}
             for i in range(150)]          # 5s of clean 30Hz flight in a 12s rally
    assert shuttle_track_quality(clean, 12.0) > 0.3
    assert shuttle_track_quality([], 12.0) == 0.0
    # teleporty leftovers still score low
    jerky = list(clean)
    for i in range(0, len(jerky), 6):
        jerky[i] = {**jerky[i], "x": 0.95, "y": 0.05}
    assert shuttle_track_quality(jerky, 12.0) < 0.1
