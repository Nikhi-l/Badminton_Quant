#!/usr/bin/env python3
"""
Quick test script to verify installation and basic functionality.

This script tests each component without requiring a full video.
"""

import logging
import numpy as np

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def test_config():
    """Test configuration loading."""
    print("\n1. Testing Configuration...")
    from racket_sports.config import load_config

    # Test badminton config
    config = load_config("badminton")
    assert config["sport"] == "badminton"
    assert "court" in config
    print("   ✓ Badminton config loaded")

    # Test table tennis config
    config = load_config("table_tennis")
    assert config["sport"] == "table_tennis"
    assert "table" in config
    print("   ✓ Table tennis config loaded")


def test_tracker():
    """Test YOLO tracker initialization."""
    print("\n2. Testing Tracker...")
    from racket_sports.tracking import get_tracker
    from racket_sports.config import load_config

    config = load_config("badminton")

    # Get tracker (this will download YOLO weights on first run)
    tracker = get_tracker(config)
    print(f"   ✓ Tracker initialized: {type(tracker).__name__}")

    # Test with dummy frame
    dummy_frame = np.zeros((480, 640, 3), dtype=np.uint8)
    result = tracker.track(dummy_frame)
    assert "frame" in result
    print("   ✓ Tracker inference works")


def test_pose():
    """Test pose estimation."""
    print("\n3. Testing Pose Estimation...")
    from racket_sports.pose import PoseEstimator
    from racket_sports.config import load_config

    config = load_config("badminton")
    pose = PoseEstimator(config)
    print(f"   ✓ Pose estimator initialized")

    # Test with dummy frame
    dummy_frame = np.zeros((480, 640, 3), dtype=np.uint8)
    result = pose.estimate(dummy_frame)
    assert "detected" in result
    print("   ✓ Pose estimation works")


def test_analytics():
    """Test analytics modules."""
    print("\n4. Testing Analytics...")
    from racket_sports.analytics import SpeedDetector, HeatmapGenerator
    from racket_sports.config import load_config

    config = load_config("badminton")

    # Speed detector
    speed = SpeedDetector(config)
    positions = [(100, 100), (120, 110), (140, 120), (160, 130)]
    speeds = speed.calculate_speeds(positions, fps=30)
    assert len(speeds) > 0
    print("   ✓ Speed detection works")

    # Heatmap generator
    heatmap = HeatmapGenerator(config)
    heatmap.set_frame_dimensions(640, 480)
    print("   ✓ Heatmap generator initialized")


def test_video_acquisition():
    """Test video acquisition module."""
    print("\n5. Testing Video Acquisition...")
    from racket_sports.video_acquisition.instagram import extract_instagram_id

    # Test URL parsing
    test_url = "https://www.instagram.com/reel/DSi1n47E0_Y/"
    video_id = extract_instagram_id(test_url)
    assert video_id == "DSi1n47E0_Y"
    print(f"   ✓ Instagram URL parsing works: {video_id}")


def test_pipeline():
    """Test pipeline initialization."""
    print("\n6. Testing Pipeline...")
    from racket_sports.pipeline import AnalysisPipeline

    pipeline = AnalysisPipeline(sport="badminton")
    assert pipeline.sport == "badminton"
    print("   ✓ Pipeline initialized")


def main():
    """Run all tests."""
    print("=" * 50)
    print("RACKET SPORTS ANALYTICS - QUICK TEST")
    print("=" * 50)

    tests = [
        test_config,
        test_video_acquisition,
        test_tracker,
        test_pose,
        test_analytics,
        test_pipeline,
    ]

    passed = 0
    failed = 0

    for test in tests:
        try:
            test()
            passed += 1
        except Exception as e:
            failed += 1
            print(f"   ✗ FAILED: {e}")

    print("\n" + "=" * 50)
    print(f"RESULTS: {passed} passed, {failed} failed")
    print("=" * 50)

    if failed == 0:
        print("\n✓ All tests passed! Ready to analyze videos.")
    else:
        print("\n✗ Some tests failed. Please check dependencies.")

    return failed == 0


if __name__ == "__main__":
    import sys
    success = main()
    sys.exit(0 if success else 1)
