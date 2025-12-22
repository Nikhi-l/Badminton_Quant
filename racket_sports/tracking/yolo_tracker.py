"""
YOLO-based object tracker for shuttle/ball detection.

Uses Ultralytics YOLO for fast, lightweight detection.
Suitable for real-time applications and quick testing.
"""

import logging
from typing import Any, Optional

import numpy as np

from racket_sports.tracking.base import BaseTracker, KalmanTracker

logger = logging.getLogger(__name__)


# Object classes we care about for racket sports
SPORT_CLASSES = {
    "badminton": ["sports ball", "frisbee"],  # Shuttlecock often detected as these
    "table_tennis": ["sports ball"],
}

# Custom class names if using fine-tuned model
CUSTOM_CLASSES = {
    0: "shuttlecock",
    1: "player",
    2: "racket",
}


class YOLOTracker(BaseTracker):
    """
    YOLO-based tracker for detecting and tracking sports objects.

    Features:
    - Uses YOLOv8/v11 for detection
    - Kalman filtering for trajectory smoothing
    - Supports both pretrained and custom models
    """

    def __init__(self, config: dict[str, Any]):
        """
        Initialize YOLO tracker.

        Args:
            config: Configuration dictionary
        """
        super().__init__(config)

        yolo_config = self.tracking_config.get("yolo", {})
        self.model_size = yolo_config.get("model_size", "n")
        self.confidence_threshold = yolo_config.get("confidence_threshold", 0.3)
        self.iou_threshold = yolo_config.get("iou_threshold", 0.5)

        self.sport = config.get("sport", "badminton")
        self.target_classes = SPORT_CLASSES.get(self.sport, ["sports ball"])

        # Lazy load model
        self._model = None
        self._custom_model_path = yolo_config.get("custom_model", None)

        # Kalman filter for smoothing
        self.use_kalman = yolo_config.get("kalman_filter", True)
        self._kalman = None

    @property
    def model(self):
        """Lazy load YOLO model."""
        if self._model is None:
            self._load_model()
        return self._model

    def _load_model(self) -> None:
        """Load YOLO model."""
        try:
            from ultralytics import YOLO
        except ImportError:
            raise ImportError("ultralytics is required. Install with: pip install ultralytics")

        if self._custom_model_path:
            logger.info(f"Loading custom YOLO model: {self._custom_model_path}")
            self._model = YOLO(self._custom_model_path)
        else:
            model_name = f"yolo11{self.model_size}.pt"
            logger.info(f"Loading pretrained YOLO model: {model_name}")
            self._model = YOLO(model_name)

        logger.info("YOLO model loaded successfully")

    @property
    def kalman(self) -> Optional[KalmanTracker]:
        """Lazy load Kalman filter."""
        if self.use_kalman and self._kalman is None:
            self._kalman = KalmanTracker()
        return self._kalman

    def track(self, frame: np.ndarray) -> dict[str, Any]:
        """
        Detect and track objects in frame.

        Args:
            frame: BGR image frame

        Returns:
            Tracking results dictionary
        """
        self.frame_count += 1

        try:
            # Run YOLO detection
            results = self.model(
                frame,
                conf=self.confidence_threshold,
                iou=self.iou_threshold,
                verbose=False,
            )
        except Exception as e:
            logger.error(f"YOLO inference failed on frame {self.frame_count}: {e}")
            return {"frame": self.frame_count, "error": str(e)}

        # Process results
        best_detection = None
        best_confidence = 0.0

        for result in results:
            boxes = result.boxes
            if boxes is None:
                continue

            for i, box in enumerate(boxes):
                cls_id = int(box.cls[0])
                cls_name = self.model.names.get(cls_id, "unknown")
                conf = float(box.conf[0])

                # Check if this is a class we're interested in
                is_target = any(
                    target.lower() in cls_name.lower()
                    for target in self.target_classes
                )

                if is_target and conf > best_confidence:
                    best_confidence = conf
                    xyxy = box.xyxy[0].cpu().numpy()
                    center_x = (xyxy[0] + xyxy[2]) / 2
                    center_y = (xyxy[1] + xyxy[3]) / 2

                    best_detection = {
                        "position": (float(center_x), float(center_y)),
                        "bbox": tuple(map(float, xyxy)),
                        "confidence": conf,
                        "class_id": cls_id,
                        "class_name": cls_name,
                    }

        # Apply Kalman filtering if we have a detection
        if best_detection and self.kalman:
            smoothed_pos = self.kalman.update(best_detection["position"])
            best_detection["position_raw"] = best_detection["position"]
            best_detection["position"] = smoothed_pos
            best_detection["velocity"] = self.kalman.get_velocity()

            # Add to trajectory
            self.add_to_trajectory(smoothed_pos)

        elif self.kalman and self.kalman.initialized:
            # Predict position when no detection
            predicted_pos = self.kalman.predict()
            best_detection = {
                "position": predicted_pos,
                "confidence": 0.0,
                "predicted": True,
            }

        result = best_detection or {}
        result["frame"] = self.frame_count
        result["trajectory"] = self.get_trajectory()[-10:]  # Last 10 points

        return result

    def reset(self) -> None:
        """Reset tracker state."""
        self.trajectory.clear()
        self.frame_count = 0
        if self._kalman:
            self._kalman.reset()

    def detect_all(self, frame: np.ndarray) -> list[dict[str, Any]]:
        """
        Detect all objects in frame (not just target class).

        Useful for detecting players, rackets, etc.

        Args:
            frame: BGR image frame

        Returns:
            List of all detections
        """
        results = self.model(
            frame,
            conf=self.confidence_threshold,
            iou=self.iou_threshold,
            verbose=False,
        )

        detections = []

        for result in results:
            boxes = result.boxes
            if boxes is None:
                continue

            for i, box in enumerate(boxes):
                cls_id = int(box.cls[0])
                cls_name = self.model.names.get(cls_id, "unknown")
                conf = float(box.conf[0])
                xyxy = box.xyxy[0].cpu().numpy()

                detections.append({
                    "position": (
                        float((xyxy[0] + xyxy[2]) / 2),
                        float((xyxy[1] + xyxy[3]) / 2),
                    ),
                    "bbox": tuple(map(float, xyxy)),
                    "confidence": conf,
                    "class_id": cls_id,
                    "class_name": cls_name,
                })

        return detections
