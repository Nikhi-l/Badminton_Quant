"""TASK-021: the renderer exports the crop window it actually used, so the Studio
can invert the virtual camera and align overlays on the cropped (portrait) reel."""
import math

from app import config
from app.main import _public_rally, _sample_camera_path
from app.pipeline.render import crop_rect


def test_crop_rect_full_zoom_is_max_916_window():
    # Landscape source: the z=1 crop is the tallest 9:16 window, clamped in-frame.
    W, H = 1920, 1080
    x0, y0, x1, y1 = crop_rect(0.5, 0.5, 1.0, W, H)
    assert (y0, y1) == (0, H)
    expected_w = int(H * config.OUT_W / config.OUT_H)
    assert math.isclose(x1 - x0, expected_w, abs_tol=1.5)
    # Centered focus → centered crop.
    assert math.isclose((x0 + x1) / 2, W / 2, abs_tol=1.5)


def test_crop_rect_clamps_at_frame_edges():
    W, H = 1920, 1080
    x0, _, x1, _ = crop_rect(0.0, 0.5, 1.3, W, H)
    assert x0 == 0 and x1 < W          # pinned to the left edge
    x0, _, x1, _ = crop_rect(1.0, 0.5, 1.3, W, H)
    assert x1 == W and x0 > 0          # pinned to the right edge


def test_crop_rect_inverts_source_points_to_reel_space():
    # A tracked source point inside the crop maps to crop-normalized coordinates —
    # exactly the projection app.js uses for portrait-reel overlays.
    W, H = 1920, 1080
    fx, fy, z = 0.62, 0.48, 1.25
    x0, y0, x1, y1 = crop_rect(fx, fy, z, W, H)
    sx, sy = 0.60, 0.50   # a source-normalized track point
    nx = (sx * W - x0) / (x1 - x0)
    ny = (sy * H - y0) / (y1 - y0)
    assert 0.0 <= nx <= 1.0 and 0.0 <= ny <= 1.0
    # The focus center itself lands mid-crop.
    cx = (fx * W - x0) / (x1 - x0)
    assert math.isclose(cx, 0.5, abs_tol=0.02)


def test_public_rally_passes_camera_path_and_render_window():
    dense = [{"t": 10.0 + i / 10, "x": 0.2, "y": 0.0, "w": 0.316, "h": 1.0}
             for i in range(600)]
    out = _public_rally({
        "start": 11.0, "end": 29.0, "dur": 18.0,
        "render_window": [10.0, 30.6],
        "camera_path": dense,
    })
    assert out["render_window"] == [10.0, 30.6]
    assert 0 < len(out["camera_path"]) <= 240
    assert set(out["camera_path"][0]) == {"t", "x", "y", "w", "h"}


def test_sample_camera_path_skips_malformed_points():
    path = [{"t": 0.0, "x": 0.1, "y": 0.0, "w": 0.5, "h": 1.0},
            {"t": "bad"}, None, {"x": 0.2}]
    out = _sample_camera_path(path)  # type: ignore[arg-type]
    assert len(out) == 1
