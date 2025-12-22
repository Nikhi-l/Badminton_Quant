"""
Shot classification for racket sports.

Classifies shots based on trajectory and pose analysis.
"""

import logging
from typing import Any, Optional

import numpy as np

logger = logging.getLogger(__name__)


class ShotClassifier:
    """
    Classifies shot types from tracking and pose data.

    Supports classification of various shot types in badminton
    and table tennis based on trajectory patterns and body pose.
    """

    def __init__(self, config: dict[str, Any]):
        """
        Initialize shot classifier.

        Args:
            config: Configuration dictionary
        """
        self.config = config
        self.sport = config.get("sport", "badminton")

        analytics_config = config.get("analytics", {})
        shot_config = analytics_config.get("shot_classification", {})

        self.enabled = shot_config.get("enabled", True)
        self.shot_classes = shot_config.get("classes", self._default_classes())

    def _default_classes(self) -> list[str]:
        """Get default shot classes for sport."""
        if self.sport == "badminton":
            return ["smash", "clear", "drop", "drive", "net_shot", "lift", "push"]
        elif self.sport == "table_tennis":
            return ["forehand_drive", "backhand_drive", "forehand_push",
                    "backhand_push", "smash", "block", "chop", "lob"]
        return []

    def classify_shot(
        self,
        trajectory: list[tuple[float, float]],
        pose_before: Optional[dict[str, Any]] = None,
        pose_after: Optional[dict[str, Any]] = None,
        speed: Optional[float] = None,
    ) -> dict[str, Any]:
        """
        Classify a single shot.

        Args:
            trajectory: Shuttlecock/ball trajectory points
            pose_before: Player pose before shot
            pose_after: Player pose after shot
            speed: Shot speed in km/h

        Returns:
            Classification result
        """
        if len(trajectory) < 3:
            return {"classified": False, "reason": "Insufficient trajectory data"}

        trajectory = np.array(trajectory)

        # Analyze trajectory features
        features = self._extract_trajectory_features(trajectory)

        # Add speed if available
        if speed is not None:
            features["speed"] = speed

        # Classify based on features
        shot_type, confidence = self._classify_by_rules(features)

        return {
            "classified": True,
            "shot_type": shot_type,
            "confidence": confidence,
            "features": features,
        }

    def _extract_trajectory_features(self, trajectory: np.ndarray) -> dict[str, float]:
        """
        Extract features from trajectory.

        Args:
            trajectory: Array of (x, y) points

        Returns:
            Feature dictionary
        """
        # Direction (start to end)
        start = trajectory[0]
        end = trajectory[-1]
        direction = end - start

        # Vertical movement (positive = down)
        vertical_movement = direction[1]

        # Horizontal movement
        horizontal_movement = direction[0]

        # Arc height (max y deviation from straight line)
        if len(trajectory) > 2:
            # Fit line from start to end
            t = np.linspace(0, 1, len(trajectory))
            expected_y = start[1] + t * (end[1] - start[1])
            arc_deviation = trajectory[:, 1] - expected_y
            arc_height = arc_deviation.min()  # Most negative = highest point
        else:
            arc_height = 0

        # Speed (using displacement)
        total_distance = np.linalg.norm(np.diff(trajectory, axis=0), axis=1).sum()

        # Angle of trajectory
        angle = np.degrees(np.arctan2(-vertical_movement, horizontal_movement))

        return {
            "vertical_movement": float(vertical_movement),
            "horizontal_movement": float(horizontal_movement),
            "arc_height": float(arc_height),
            "total_distance": float(total_distance),
            "angle": float(angle),
            "trajectory_length": len(trajectory),
        }

    def _classify_by_rules(
        self,
        features: dict[str, float],
    ) -> tuple[str, float]:
        """
        Classify shot using rule-based approach.

        Args:
            features: Trajectory features

        Returns:
            (shot_type, confidence) tuple
        """
        if self.sport == "badminton":
            return self._classify_badminton(features)
        elif self.sport == "table_tennis":
            return self._classify_table_tennis(features)
        return ("unknown", 0.0)

    def _classify_badminton(
        self,
        features: dict[str, float],
    ) -> tuple[str, float]:
        """Classify badminton shots."""
        angle = features.get("angle", 0)
        vertical = features.get("vertical_movement", 0)
        arc = features.get("arc_height", 0)
        speed = features.get("speed", 0)

        # Smash: steep downward, high speed
        if speed > 200 and vertical > 100 and angle < -30:
            return ("smash", 0.9)

        # Clear: high arc, travels far
        if arc < -50 and abs(features.get("horizontal_movement", 0)) > 200:
            return ("clear", 0.8)

        # Drop: downward trajectory, short distance
        if vertical > 50 and features.get("total_distance", 0) < 200:
            return ("drop", 0.7)

        # Drive: relatively flat trajectory
        if abs(angle) < 20:
            return ("drive", 0.7)

        # Net shot: short trajectory near net area
        if features.get("total_distance", 0) < 100:
            return ("net_shot", 0.6)

        # Lift: upward trajectory
        if vertical < -50:
            return ("lift", 0.7)

        return ("unknown", 0.3)

    def _classify_table_tennis(
        self,
        features: dict[str, float],
    ) -> tuple[str, float]:
        """Classify table tennis shots."""
        angle = features.get("angle", 0)
        speed = features.get("speed", 0)

        # Smash: high speed, downward
        if speed > 80 and angle < -20:
            return ("smash", 0.8)

        # Chop: upward trajectory, backspin
        if angle > 20:
            return ("chop", 0.7)

        # Drive: relatively flat, medium speed
        if abs(angle) < 15 and 30 < speed < 80:
            return ("drive", 0.7)

        # Push: slow, flat
        if speed < 30:
            return ("push", 0.6)

        # Block: very short trajectory
        if features.get("total_distance", 0) < 50:
            return ("block", 0.6)

        return ("unknown", 0.3)

    def classify_sequence(
        self,
        tracking_data: list[dict[str, Any]],
        pose_data: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """
        Classify shots in a sequence of tracking data.

        Args:
            tracking_data: List of frame tracking results
            pose_data: List of pose estimation results

        Returns:
            List of classified shots
        """
        shots = []

        # Find shot segments (when shuttle changes direction significantly)
        trajectories = self._segment_trajectories(tracking_data)

        for traj_info in trajectories:
            start_frame = traj_info["start_frame"]
            end_frame = traj_info["end_frame"]
            trajectory = traj_info["trajectory"]

            # Get corresponding pose data
            pose_before = pose_data[start_frame] if start_frame < len(pose_data) else None
            pose_after = pose_data[end_frame] if end_frame < len(pose_data) else None

            # Classify
            classification = self.classify_shot(
                trajectory,
                pose_before=pose_before,
                pose_after=pose_after,
            )

            classification["start_frame"] = start_frame
            classification["end_frame"] = end_frame
            shots.append(classification)

        return shots

    def _segment_trajectories(
        self,
        tracking_data: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """
        Segment tracking data into individual shot trajectories.

        Args:
            tracking_data: List of frame tracking results

        Returns:
            List of trajectory segments
        """
        segments = []
        current_trajectory = []
        start_frame = 0

        for i, track in enumerate(tracking_data):
            pos = track.get("position")
            if pos is None:
                if current_trajectory:
                    segments.append({
                        "start_frame": start_frame,
                        "end_frame": i - 1,
                        "trajectory": current_trajectory,
                    })
                    current_trajectory = []
                continue

            if not current_trajectory:
                start_frame = i

            current_trajectory.append(pos)

            # Check for direction change (potential new shot)
            if len(current_trajectory) >= 5:
                recent = np.array(current_trajectory[-5:])
                velocities = np.diff(recent, axis=0)

                # Check if velocity changed direction significantly
                if len(velocities) >= 2:
                    v1 = velocities[-2]
                    v2 = velocities[-1]
                    dot = np.dot(v1, v2)
                    if dot < 0:  # Direction reversed
                        segments.append({
                            "start_frame": start_frame,
                            "end_frame": i,
                            "trajectory": current_trajectory[:-1],
                        })
                        current_trajectory = [pos]
                        start_frame = i

        # Add final segment
        if current_trajectory:
            segments.append({
                "start_frame": start_frame,
                "end_frame": len(tracking_data) - 1,
                "trajectory": current_trajectory,
            })

        return segments
