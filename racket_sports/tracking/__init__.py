"""
Object tracking module for shuttle/ball detection.

Supports multiple tracking backends:
- YOLO: Fast, lightweight detection
- TrackNetV3: Specialized for shuttlecock tracking
- SAM2: High-precision segmentation-based tracking
"""

from racket_sports.tracking.base import BaseTracker, TrackingResult
from racket_sports.tracking.yolo_tracker import YOLOTracker


def get_tracker(config: dict) -> BaseTracker:
    """
    Factory function to create appropriate tracker based on config.

    Args:
        config: Configuration dictionary

    Returns:
        Tracker instance
    """
    tracking_config = config.get("tracking", {})
    model_type = tracking_config.get("model", "yolo")

    if model_type == "yolo":
        return YOLOTracker(config)
    elif model_type == "tracknetv3":
        from racket_sports.tracking.tracknet import TrackNetTracker
        return TrackNetTracker(config)
    elif model_type == "sam2":
        from racket_sports.tracking.sam2_tracker import SAM2Tracker
        return SAM2Tracker(config)
    else:
        raise ValueError(f"Unknown tracker type: {model_type}")


__all__ = ["BaseTracker", "TrackingResult", "YOLOTracker", "get_tracker"]
