"""
MediaPipe-based pose estimation.

MediaPipe Pose provides 33 body landmarks in 2D and 3D coordinates,
suitable for real-time pose analysis in sports applications.
"""

import logging
from dataclasses import dataclass, field
from typing import Any, Optional

import numpy as np

logger = logging.getLogger(__name__)


# MediaPipe landmark indices
class PoseLandmark:
    """MediaPipe pose landmark indices."""
    NOSE = 0
    LEFT_EYE_INNER = 1
    LEFT_EYE = 2
    LEFT_EYE_OUTER = 3
    RIGHT_EYE_INNER = 4
    RIGHT_EYE = 5
    RIGHT_EYE_OUTER = 6
    LEFT_EAR = 7
    RIGHT_EAR = 8
    MOUTH_LEFT = 9
    MOUTH_RIGHT = 10
    LEFT_SHOULDER = 11
    RIGHT_SHOULDER = 12
    LEFT_ELBOW = 13
    RIGHT_ELBOW = 14
    LEFT_WRIST = 15
    RIGHT_WRIST = 16
    LEFT_PINKY = 17
    RIGHT_PINKY = 18
    LEFT_INDEX = 19
    RIGHT_INDEX = 20
    LEFT_THUMB = 21
    RIGHT_THUMB = 22
    LEFT_HIP = 23
    RIGHT_HIP = 24
    LEFT_KNEE = 25
    RIGHT_KNEE = 26
    LEFT_ANKLE = 27
    RIGHT_ANKLE = 28
    LEFT_HEEL = 29
    RIGHT_HEEL = 30
    LEFT_FOOT_INDEX = 31
    RIGHT_FOOT_INDEX = 32


@dataclass
class PoseResult:
    """Result from pose estimation."""
    landmarks_2d: Optional[np.ndarray] = None  # Shape: (33, 2)
    landmarks_3d: Optional[np.ndarray] = None  # Shape: (33, 3)
    visibility: Optional[np.ndarray] = None  # Shape: (33,)
    world_landmarks: Optional[np.ndarray] = None  # 3D world coordinates
    bbox: Optional[tuple[float, float, float, float]] = None
    segmentation_mask: Optional[np.ndarray] = None
    detected: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    def get_landmark_2d(self, idx: int) -> Optional[tuple[float, float]]:
        """Get 2D coordinates of a landmark."""
        if self.landmarks_2d is None:
            return None
        return tuple(self.landmarks_2d[idx])

    def get_landmark_3d(self, idx: int) -> Optional[tuple[float, float, float]]:
        """Get 3D coordinates of a landmark."""
        if self.landmarks_3d is None:
            return None
        return tuple(self.landmarks_3d[idx])

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "detected": self.detected,
            "landmarks_2d": self.landmarks_2d.tolist() if self.landmarks_2d is not None else None,
            "landmarks_3d": self.landmarks_3d.tolist() if self.landmarks_3d is not None else None,
            "visibility": self.visibility.tolist() if self.visibility is not None else None,
            "bbox": self.bbox,
            "metadata": self.metadata,
        }


class PoseEstimator:
    """
    MediaPipe-based pose estimation for sports analysis.

    Features:
    - 33 body landmarks with 2D and 3D coordinates
    - Real-time performance
    - Optional segmentation mask
    """

    def __init__(self, config: dict[str, Any]):
        """
        Initialize pose estimator.

        Args:
            config: Configuration dictionary
        """
        self.config = config
        pose_config = config.get("pose", {})
        mp_config = pose_config.get("mediapipe", {})

        self.model_complexity = mp_config.get("model_complexity", 2)
        self.min_detection_confidence = mp_config.get("min_detection_confidence", 0.5)
        self.min_tracking_confidence = mp_config.get("min_tracking_confidence", 0.5)
        self.enable_segmentation = mp_config.get("enable_segmentation", False)
        self.output_3d = pose_config.get("output_3d", True)

        # Lazy load model
        self._pose = None

    @property
    def pose(self):
        """Lazy load MediaPipe Pose."""
        if self._pose is None:
            self._load_model()
        return self._pose

    def _load_model(self) -> None:
        """Load MediaPipe Pose model."""
        try:
            import mediapipe as mp
        except ImportError:
            raise ImportError("mediapipe is required. Install with: pip install mediapipe")

        self.mp_pose = mp.solutions.pose
        self.mp_drawing = mp.solutions.drawing_utils

        self._pose = self.mp_pose.Pose(
            static_image_mode=False,
            model_complexity=self.model_complexity,
            enable_segmentation=self.enable_segmentation,
            min_detection_confidence=self.min_detection_confidence,
            min_tracking_confidence=self.min_tracking_confidence,
        )

        logger.info(f"MediaPipe Pose loaded (complexity={self.model_complexity})")

    def estimate(self, frame: np.ndarray) -> dict[str, Any]:
        """
        Estimate pose in frame.

        Args:
            frame: BGR image frame

        Returns:
            Pose estimation results dictionary
        """
        import cv2

        # Convert BGR to RGB
        rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

        # Process frame
        results = self.pose.process(rgb_frame)

        # Extract results
        pose_result = PoseResult()

        if results.pose_landmarks:
            pose_result.detected = True

            # Extract 2D landmarks (normalized coordinates)
            landmarks_2d = []
            visibility = []
            h, w = frame.shape[:2]

            for landmark in results.pose_landmarks.landmark:
                landmarks_2d.append([landmark.x * w, landmark.y * h])
                visibility.append(landmark.visibility)

            pose_result.landmarks_2d = np.array(landmarks_2d)
            pose_result.visibility = np.array(visibility)

            # Calculate bounding box
            x_coords = pose_result.landmarks_2d[:, 0]
            y_coords = pose_result.landmarks_2d[:, 1]
            pose_result.bbox = (
                float(x_coords.min()),
                float(y_coords.min()),
                float(x_coords.max()),
                float(y_coords.max()),
            )

            # Extract 3D landmarks if available
            if self.output_3d and results.pose_world_landmarks:
                world_landmarks = []
                for landmark in results.pose_world_landmarks.landmark:
                    world_landmarks.append([landmark.x, landmark.y, landmark.z])
                pose_result.world_landmarks = np.array(world_landmarks)

                # Also store as landmarks_3d for convenience
                landmarks_3d = []
                for landmark in results.pose_landmarks.landmark:
                    landmarks_3d.append([landmark.x * w, landmark.y * h, landmark.z * w])
                pose_result.landmarks_3d = np.array(landmarks_3d)

        # Segmentation mask
        if self.enable_segmentation and results.segmentation_mask is not None:
            pose_result.segmentation_mask = results.segmentation_mask

        return pose_result.to_dict()

    def draw_landmarks(
        self,
        frame: np.ndarray,
        pose_result: dict[str, Any],
        draw_connections: bool = True,
    ) -> np.ndarray:
        """
        Draw pose landmarks on frame.

        Args:
            frame: BGR image frame
            pose_result: Pose estimation result dict
            draw_connections: Whether to draw connection lines

        Returns:
            Frame with landmarks drawn
        """
        import cv2

        output = frame.copy()

        if not pose_result.get("detected"):
            return output

        landmarks_2d = pose_result.get("landmarks_2d")
        if landmarks_2d is None:
            return output

        landmarks_2d = np.array(landmarks_2d)

        # Draw landmarks
        for i, (x, y) in enumerate(landmarks_2d):
            cv2.circle(output, (int(x), int(y)), 4, (0, 255, 0), -1)

        # Draw connections
        if draw_connections:
            connections = [
                # Torso
                (11, 12), (11, 23), (12, 24), (23, 24),
                # Left arm
                (11, 13), (13, 15), (15, 17), (15, 19), (15, 21), (17, 19),
                # Right arm
                (12, 14), (14, 16), (16, 18), (16, 20), (16, 22), (18, 20),
                # Left leg
                (23, 25), (25, 27), (27, 29), (27, 31), (29, 31),
                # Right leg
                (24, 26), (26, 28), (28, 30), (28, 32), (30, 32),
                # Face
                (0, 1), (1, 2), (2, 3), (3, 7),
                (0, 4), (4, 5), (5, 6), (6, 8),
                (9, 10),
            ]

            for start_idx, end_idx in connections:
                start = landmarks_2d[start_idx]
                end = landmarks_2d[end_idx]
                cv2.line(
                    output,
                    (int(start[0]), int(start[1])),
                    (int(end[0]), int(end[1])),
                    (0, 255, 255),
                    2,
                )

        return output

    def close(self) -> None:
        """Release resources."""
        if self._pose:
            self._pose.close()
            self._pose = None

    def __del__(self):
        """Cleanup on deletion."""
        self.close()
