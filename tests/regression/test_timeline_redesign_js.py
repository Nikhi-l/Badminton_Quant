"""TASK-033: structural guards for the Studio timeline redesign.

Same pattern as test_studio_pose_overlay_js.py: cheap greps that pin the
load-bearing pieces of the redesign so a refactor can't silently regress them.
"""
from pathlib import Path

WEB = Path(__file__).resolve().parents[2] / "web"


def test_zoom_has_no_dead_subunity_range():
    html = (WEB / "index.html").read_text()
    js = (WEB / "app.js").read_text()
    # slider floor is 1x — 80..99 was a no-op zone that desynced the playhead
    assert 'id="timelineZoom" min="100"' in html
    assert "function tlScale()" in js
    # the old %*scale playhead math is gone; playhead is pixel-positioned
    assert "timelineScale * 100}%`" not in js.split("function studioTick")[1].split("function ")[1]


def test_playhead_is_pixel_positioned_with_edge_flip():
    js = (WEB / "app.js").read_text()
    assert 'head.style.left = `${px}px`' in js
    assert 'classList.toggle("flip"' in js
    css = (WEB / "style.css").read_text()
    assert ".playhead.flip .ph-time" in css


def test_lanes_fit_the_timeline_row():
    js = (WEB / "app.js").read_text()
    css = (WEB / "style.css").read_text()
    # TRACK_META heights must fit the 170px lane budget (236px row - 38 header
    # - 28 ruler) — pose + soundtrack used to render clipped and invisible.
    # reel and source lanes never coexist, so budget the reel-mode set.
    import re
    heights = dict(re.findall(r'(\w+):\s*\{ ico: "[^"]+", h: (\d+)', js))
    reel_mode = ["reel", "caption", "camera", "shuttle", "pose", "soundtrack"]
    assert all(k in heights for k in reel_mode)
    assert sum(int(heights[k]) for k in reel_mode) <= 170
    assert "52px 236px" in css


def test_dead_lanes_removed_from_source_mode():
    js = (WEB / "app.js").read_text()
    assert 'label: "Ambient"' not in js       # permanently-empty audio lane
    # camera lane only exists in reel mode where its keyframe marks can draw
    assert js.count('{ id: "camera", label: "Camera"') == 1


def test_hover_ghost_and_adaptive_ruler_exist():
    js = (WEB / "app.js").read_text()
    html = (WEB / "index.html").read_text()
    assert 'id="tlGhost"' in html
    assert "initTimelineHover" in js
    assert "STEPS.find(s => s * pps >= 70)" in js
    assert "setTimelineZoom" in js
