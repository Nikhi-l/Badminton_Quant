"""TASK-029 regressions: the render crash that failed job 9cca230f32a6
(ValueError: operands could not be broadcast together with shapes
(138,1024,3) (138,1056,1)) and the doubles player caps."""
import numpy as np

from app import config
from app.pipeline import render
from app.pipeline.gpu import _canonicalize


def test_blend_clips_overlay_wider_than_frame():
    # Exact failing geometry: badge 1056px wide at x=56 on a 1080px frame.
    frame = np.zeros((1920, 1080, 3), dtype=np.uint8)
    overlay = np.full((138, 1056, 4), 200, dtype=np.uint8)
    render._blend(frame, overlay, 56, 1718)          # must not raise
    assert frame[1720, 1000].sum() > 0               # blended inside the frame
    # fully outside is a clean no-op
    render._blend(frame, overlay, 2000, 0)
    render._blend(frame, overlay, -2000, 0)


def test_blend_clips_negative_origin():
    frame = np.zeros((100, 100, 3), dtype=np.uint8)
    overlay = np.full((40, 40, 4), 255, dtype=np.uint8)
    render._blend(frame, overlay, -20, -20)
    assert frame[5, 5].sum() > 0 and frame[50, 50].sum() == 0


def test_badge_width_capped_for_long_rally_notes():
    long_note = ("71-shot rally ending with both players collapsing after an "
                 "extraordinary sequence of cross-court smashes, dives, and "
                 "net kills that brought the whole arena to its feet")
    badge = render._badge("RALLY 1", f"73s · {long_note}")
    assert badge.shape[1] <= config.OUT_W - 112
    # and it still renders (blend at the real badge position)
    frame = np.zeros((config.OUT_H, config.OUT_W, 3), dtype=np.uint8)
    render._blend(frame, badge, 56, config.OUT_H - 130 - 72)


def test_canonical_rallies_keep_four_players_for_doubles():
    def box(cx, cy):
        return {"box": [cx - 0.05, cy - 0.12, cx + 0.05, cy + 0.12], "confidence": 0.7}
    raw = {"rallies": [{
        "rally_index": 1,
        "frames": [{"t": 1.0, "players": [box(0.3, 0.7), box(0.7, 0.7),
                                          box(0.35, 0.3), box(0.65, 0.3)]}],
    }]}
    out = _canonicalize(raw, [{"start": 0.0, "end": 4.0, "dur": 4.0}])
    assert len(out["rallies"][0]["players"][0]["boxes"]) == 4
