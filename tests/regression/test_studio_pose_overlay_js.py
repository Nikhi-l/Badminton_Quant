from pathlib import Path


APP_JS = Path(__file__).resolve().parents[2] / "web" / "app.js"


def test_studio_pose_overlay_uses_pose_track_not_null_stub():
    js = APP_JS.read_text()

    assert 'function currentPose() {\n  return null;' not in js
    assert "pose_track" in js
    assert "const POSE_LIMBS" in js
    assert "renderPoseOverlay(pose, po)" in js


def test_source_pose_lane_respects_pose_toggle():
    js = APP_JS.read_text()

    assert 'track.id === "pose" && studio.mode === "source" && studio.editorState.overlays.pose.enabled' in js
    assert 'count: studio.editorState.overlays.pose.enabled ? poseReadyCount() : 0' in js
