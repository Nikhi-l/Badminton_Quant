"""
Pose analysis utilities for sports-specific metrics.

Analyzes pose landmarks to extract meaningful sports metrics like:
- Joint angles (elbow, knee, shoulder)
- Body orientation
- Movement direction
- Shot preparation detection
"""

import logging
from typing import Any, Optional

import numpy as np

from racket_sports.pose.mediapipe_pose import PoseLandmark

logger = logging.getLogger(__name__)


class PoseAnalyzer:
    """
    Analyzer for extracting sports metrics from pose data.

    Computes joint angles, body orientation, and sport-specific metrics
    from MediaPipe pose landmarks.
    """

    def __init__(self, config: dict[str, Any]):
        """
        Initialize pose analyzer.

        Args:
            config: Configuration dictionary
        """
        self.config = config
        self.sport = config.get("sport", "badminton")

    @staticmethod
    def calculate_angle(
        point1: np.ndarray,
        point2: np.ndarray,
        point3: np.ndarray,
    ) -> float:
        """
        Calculate angle between three points.

        Args:
            point1: First point (e.g., shoulder)
            point2: Middle point (vertex, e.g., elbow)
            point3: Last point (e.g., wrist)

        Returns:
            Angle in degrees
        """
        v1 = point1 - point2
        v2 = point3 - point2

        # Handle 2D or 3D points
        if len(v1) == 2:
            angle_rad = np.arctan2(v2[1], v2[0]) - np.arctan2(v1[1], v1[0])
        else:
            cos_angle = np.dot(v1, v2) / (np.linalg.norm(v1) * np.linalg.norm(v2) + 1e-8)
            angle_rad = np.arccos(np.clip(cos_angle, -1.0, 1.0))

        angle_deg = np.degrees(angle_rad)

        # Normalize to 0-180
        if angle_deg < 0:
            angle_deg += 360
        if angle_deg > 180:
            angle_deg = 360 - angle_deg

        return angle_deg

    def analyze_pose(self, pose_result: dict[str, Any]) -> dict[str, Any]:
        """
        Analyze pose for sports-specific metrics.

        Args:
            pose_result: Pose estimation result

        Returns:
            Analysis results dictionary
        """
        if not pose_result.get("detected"):
            return {"analyzed": False}

        landmarks = pose_result.get("landmarks_2d")
        if landmarks is None:
            return {"analyzed": False}

        landmarks = np.array(landmarks)

        analysis = {
            "analyzed": True,
            "joint_angles": self._calculate_joint_angles(landmarks),
            "body_orientation": self._calculate_body_orientation(landmarks),
            "arm_position": self._analyze_arm_position(landmarks),
        }

        # Sport-specific analysis
        if self.sport == "badminton":
            analysis["badminton"] = self._analyze_badminton(landmarks)
        elif self.sport == "table_tennis":
            analysis["table_tennis"] = self._analyze_table_tennis(landmarks)

        return analysis

    def _calculate_joint_angles(self, landmarks: np.ndarray) -> dict[str, float]:
        """Calculate key joint angles."""
        angles = {}

        # Right elbow angle
        angles["right_elbow"] = self.calculate_angle(
            landmarks[PoseLandmark.RIGHT_SHOULDER],
            landmarks[PoseLandmark.RIGHT_ELBOW],
            landmarks[PoseLandmark.RIGHT_WRIST],
        )

        # Left elbow angle
        angles["left_elbow"] = self.calculate_angle(
            landmarks[PoseLandmark.LEFT_SHOULDER],
            landmarks[PoseLandmark.LEFT_ELBOW],
            landmarks[PoseLandmark.LEFT_WRIST],
        )

        # Right knee angle
        angles["right_knee"] = self.calculate_angle(
            landmarks[PoseLandmark.RIGHT_HIP],
            landmarks[PoseLandmark.RIGHT_KNEE],
            landmarks[PoseLandmark.RIGHT_ANKLE],
        )

        # Left knee angle
        angles["left_knee"] = self.calculate_angle(
            landmarks[PoseLandmark.LEFT_HIP],
            landmarks[PoseLandmark.LEFT_KNEE],
            landmarks[PoseLandmark.LEFT_ANKLE],
        )

        # Right shoulder angle (arm elevation)
        angles["right_shoulder"] = self.calculate_angle(
            landmarks[PoseLandmark.RIGHT_HIP],
            landmarks[PoseLandmark.RIGHT_SHOULDER],
            landmarks[PoseLandmark.RIGHT_ELBOW],
        )

        # Left shoulder angle
        angles["left_shoulder"] = self.calculate_angle(
            landmarks[PoseLandmark.LEFT_HIP],
            landmarks[PoseLandmark.LEFT_SHOULDER],
            landmarks[PoseLandmark.LEFT_ELBOW],
        )

        return angles

    def _calculate_body_orientation(self, landmarks: np.ndarray) -> dict[str, Any]:
        """Calculate body orientation and facing direction."""
        # Shoulder vector
        left_shoulder = landmarks[PoseLandmark.LEFT_SHOULDER]
        right_shoulder = landmarks[PoseLandmark.RIGHT_SHOULDER]
        shoulder_vector = right_shoulder - left_shoulder

        # Hip vector
        left_hip = landmarks[PoseLandmark.LEFT_HIP]
        right_hip = landmarks[PoseLandmark.RIGHT_HIP]
        hip_vector = right_hip - left_hip

        # Calculate torso angle
        torso_angle = np.degrees(np.arctan2(shoulder_vector[1], shoulder_vector[0]))

        # Estimate facing direction based on shoulder/hip ratio
        shoulder_width = np.linalg.norm(shoulder_vector)
        hip_width = np.linalg.norm(hip_vector)

        # When facing camera, shoulders appear wider
        # When sideways, shoulders appear narrower
        facing_ratio = shoulder_width / (hip_width + 1e-8)

        return {
            "torso_angle": torso_angle,
            "facing_ratio": facing_ratio,
            "estimated_facing": "front" if facing_ratio > 1.2 else "side",
            "shoulder_width": shoulder_width,
            "hip_width": hip_width,
        }

    def _analyze_arm_position(self, landmarks: np.ndarray) -> dict[str, Any]:
        """Analyze arm positions for racket sports."""
        # Right arm analysis (commonly racket arm)
        right_wrist = landmarks[PoseLandmark.RIGHT_WRIST]
        right_shoulder = landmarks[PoseLandmark.RIGHT_SHOULDER]
        right_elbow = landmarks[PoseLandmark.RIGHT_ELBOW]

        # Arm elevation (how high is the arm)
        arm_elevation = right_shoulder[1] - right_wrist[1]

        # Arm extension (how straight is the arm)
        shoulder_to_wrist = np.linalg.norm(right_wrist - right_shoulder)
        shoulder_to_elbow = np.linalg.norm(right_elbow - right_shoulder)
        elbow_to_wrist = np.linalg.norm(right_wrist - right_elbow)
        max_extension = shoulder_to_elbow + elbow_to_wrist
        extension_ratio = shoulder_to_wrist / (max_extension + 1e-8)

        return {
            "right_arm_elevation": arm_elevation,
            "right_arm_extension_ratio": extension_ratio,
            "right_arm_extended": extension_ratio > 0.9,
            "right_arm_above_shoulder": right_wrist[1] < right_shoulder[1],
        }

    def _analyze_badminton(self, landmarks: np.ndarray) -> dict[str, Any]:
        """Badminton-specific pose analysis."""
        arm = self._analyze_arm_position(landmarks)
        angles = self._calculate_joint_angles(landmarks)

        # Detect smash preparation
        # - Arm raised above shoulder
        # - Elbow bent (90-150 degrees)
        smash_preparation = (
            arm["right_arm_above_shoulder"] and
            90 < angles["right_elbow"] < 150
        )

        # Detect ready position
        # - Knees slightly bent
        # - Arms in front of body
        ready_position = (
            140 < angles["right_knee"] < 170 and
            140 < angles["left_knee"] < 170
        )

        # Lunge detection
        # - One knee deeply bent, other extended
        knee_diff = abs(angles["right_knee"] - angles["left_knee"])
        lunge_detected = knee_diff > 40

        return {
            "smash_preparation": smash_preparation,
            "ready_position": ready_position,
            "lunge_detected": lunge_detected,
            "knee_bend_difference": knee_diff,
        }

    def _analyze_table_tennis(self, landmarks: np.ndarray) -> dict[str, Any]:
        """Table tennis-specific pose analysis."""
        arm = self._analyze_arm_position(landmarks)
        angles = self._calculate_joint_angles(landmarks)

        # Detect forehand vs backhand position
        right_wrist = landmarks[PoseLandmark.RIGHT_WRIST]
        left_shoulder = landmarks[PoseLandmark.LEFT_SHOULDER]
        right_shoulder = landmarks[PoseLandmark.RIGHT_SHOULDER]

        # If wrist crosses body midline, likely backhand
        body_midline = (left_shoulder[0] + right_shoulder[0]) / 2
        backhand_position = right_wrist[0] < body_midline

        # Ready position
        ready_position = (
            150 < angles["right_knee"] < 175 and
            150 < angles["left_knee"] < 175 and
            not arm["right_arm_extended"]
        )

        return {
            "backhand_position": backhand_position,
            "forehand_position": not backhand_position,
            "ready_position": ready_position,
            "compact_stance": angles["right_elbow"] < 120,
        }

    def detect_shot_type(
        self,
        pose_sequence: list[dict[str, Any]],
    ) -> Optional[str]:
        """
        Detect shot type from a sequence of poses.

        Args:
            pose_sequence: List of pose results over time

        Returns:
            Detected shot type or None
        """
        if len(pose_sequence) < 5:
            return None

        # Analyze movement pattern
        analyses = [self.analyze_pose(p) for p in pose_sequence if p.get("detected")]

        if len(analyses) < 3:
            return None

        # Check for smash pattern (arm goes up then down)
        arm_elevations = [
            a.get("arm_position", {}).get("right_arm_elevation", 0)
            for a in analyses
        ]

        if len(arm_elevations) >= 3:
            # Detect upward then downward motion
            max_idx = np.argmax(arm_elevations)
            if 0 < max_idx < len(arm_elevations) - 1:
                if arm_elevations[max_idx] > 100:  # High point
                    return "smash"

        # Add more shot detection patterns here

        return None
