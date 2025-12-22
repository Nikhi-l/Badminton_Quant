"""
Weakness analysis for player performance evaluation.

Identifies areas where a player might be vulnerable based on:
- Movement patterns
- Shot response times
- Court coverage gaps
- Shot success rates by area
"""

import logging
from typing import Any, Optional

import numpy as np

logger = logging.getLogger(__name__)


class WeaknessAnalyzer:
    """
    Analyzes player weaknesses from movement and shot data.

    Identifies:
    - Court areas with poor coverage
    - Slow response directions
    - Predictable patterns
    - Vulnerable positions
    """

    def __init__(self, config: dict[str, Any]):
        """
        Initialize weakness analyzer.

        Args:
            config: Configuration dictionary
        """
        self.config = config
        self.sport = config.get("sport", "badminton")

        analytics_config = config.get("analytics", {})
        weakness_config = analytics_config.get("weakness", {})

        self.enabled = weakness_config.get("enabled", True)
        self.min_samples = weakness_config.get("min_samples", 10)

        # Court dimensions
        court_config = config.get("court", config.get("table", {}))
        self.court_length = court_config.get("length_m", 13.4)
        self.court_width = court_config.get("width_singles_m", court_config.get("width_m", 5.18))

    def analyze(
        self,
        pose_data: list[dict[str, Any]],
        shot_data: list[dict[str, Any]],
        tracking_data: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """
        Perform comprehensive weakness analysis.

        Args:
            pose_data: Pose estimation results
            shot_data: Shot classification results
            tracking_data: Ball/shuttle tracking data

        Returns:
            Weakness analysis results
        """
        if not self.enabled:
            return {"analyzed": False, "reason": "Weakness analysis disabled"}

        results = {
            "analyzed": True,
            "coverage": self._analyze_coverage(pose_data),
            "movement": self._analyze_movement(pose_data),
            "response": self._analyze_response_patterns(pose_data, tracking_data),
        }

        if shot_data:
            results["shots"] = self._analyze_shot_weaknesses(shot_data)

        # Generate summary
        results["summary"] = self._generate_summary(results)

        return results

    def _analyze_coverage(
        self,
        pose_data: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """
        Analyze court coverage patterns.

        Args:
            pose_data: Pose estimation results

        Returns:
            Coverage analysis
        """
        # Extract player positions
        positions = []
        for pose in pose_data:
            if not pose.get("detected"):
                continue
            landmarks = pose.get("landmarks_2d")
            if landmarks is None:
                continue
            landmarks = np.array(landmarks)
            hip_center = (landmarks[23] + landmarks[24]) / 2
            positions.append(hip_center)

        if len(positions) < self.min_samples:
            return {"analyzed": False, "reason": "Insufficient data"}

        positions = np.array(positions)

        # Divide court into zones (3x3 grid)
        x_min, x_max = positions[:, 0].min(), positions[:, 0].max()
        y_min, y_max = positions[:, 1].min(), positions[:, 1].max()

        zone_counts = np.zeros((3, 3))
        zone_names = [
            ["back_left", "back_center", "back_right"],
            ["mid_left", "mid_center", "mid_right"],
            ["front_left", "front_center", "front_right"],
        ]

        for pos in positions:
            x_zone = min(2, int((pos[0] - x_min) / (x_max - x_min + 1e-8) * 3))
            y_zone = min(2, int((pos[1] - y_min) / (y_max - y_min + 1e-8) * 3))
            zone_counts[y_zone, x_zone] += 1

        # Normalize
        zone_percentages = zone_counts / zone_counts.sum() * 100

        # Find weak zones (less than 5% time spent)
        weak_zones = []
        for i in range(3):
            for j in range(3):
                if zone_percentages[i, j] < 5:
                    weak_zones.append(zone_names[i][j])

        return {
            "analyzed": True,
            "zone_distribution": {
                zone_names[i][j]: float(zone_percentages[i, j])
                for i in range(3)
                for j in range(3)
            },
            "weak_zones": weak_zones,
            "dominant_zone": zone_names[
                np.unravel_index(zone_percentages.argmax(), zone_percentages.shape)[0]
            ][
                np.unravel_index(zone_percentages.argmax(), zone_percentages.shape)[1]
            ],
            "center_bias": float(zone_percentages[1, 1]),
        }

    def _analyze_movement(
        self,
        pose_data: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """
        Analyze movement patterns and weaknesses.

        Args:
            pose_data: Pose estimation results

        Returns:
            Movement analysis
        """
        positions = []
        for pose in pose_data:
            if not pose.get("detected"):
                continue
            landmarks = pose.get("landmarks_2d")
            if landmarks is None:
                continue
            landmarks = np.array(landmarks)
            hip_center = (landmarks[23] + landmarks[24]) / 2
            positions.append(hip_center)

        if len(positions) < self.min_samples:
            return {"analyzed": False}

        positions = np.array(positions)
        velocities = np.diff(positions, axis=0)

        # Analyze movement directions
        left_movements = velocities[velocities[:, 0] < -5]
        right_movements = velocities[velocities[:, 0] > 5]
        forward_movements = velocities[velocities[:, 1] < -5]
        backward_movements = velocities[velocities[:, 1] > 5]

        # Calculate average speeds in each direction
        def avg_speed(movements):
            if len(movements) == 0:
                return 0.0
            return float(np.linalg.norm(movements, axis=1).mean())

        direction_speeds = {
            "left": avg_speed(left_movements),
            "right": avg_speed(right_movements),
            "forward": avg_speed(forward_movements),
            "backward": avg_speed(backward_movements),
        }

        # Find slowest direction
        slowest = min(direction_speeds, key=direction_speeds.get)

        return {
            "analyzed": True,
            "direction_speeds": direction_speeds,
            "slowest_direction": slowest,
            "movement_asymmetry": {
                "lateral": abs(direction_speeds["left"] - direction_speeds["right"]),
                "sagittal": abs(direction_speeds["forward"] - direction_speeds["backward"]),
            },
        }

    def _analyze_response_patterns(
        self,
        pose_data: list[dict[str, Any]],
        tracking_data: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """
        Analyze player response patterns to shuttlecock positions.

        Args:
            pose_data: Pose data
            tracking_data: Tracking data

        Returns:
            Response analysis
        """
        # This would correlate shuttle position with player movement
        # Simplified version for now
        return {
            "analyzed": True,
            "note": "Full response analysis requires synchronized tracking and pose data",
        }

    def _analyze_shot_weaknesses(
        self,
        shot_data: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """
        Analyze weaknesses in shot selection and execution.

        Args:
            shot_data: Shot classification data

        Returns:
            Shot weakness analysis
        """
        if len(shot_data) < self.min_samples:
            return {"analyzed": False, "reason": "Insufficient shot data"}

        # Count shot types
        shot_types = {}
        for shot in shot_data:
            if shot.get("classified"):
                shot_type = shot.get("shot_type", "unknown")
                shot_types[shot_type] = shot_types.get(shot_type, 0) + 1

        total = sum(shot_types.values())
        shot_distribution = {k: v / total * 100 for k, v in shot_types.items()}

        # Find underused shots
        underused = [k for k, v in shot_distribution.items() if v < 5 and k != "unknown"]

        return {
            "analyzed": True,
            "shot_distribution": shot_distribution,
            "underused_shots": underused,
            "most_common": max(shot_types, key=shot_types.get) if shot_types else None,
        }

    def _generate_summary(self, results: dict[str, Any]) -> list[str]:
        """
        Generate human-readable summary of weaknesses.

        Args:
            results: Analysis results

        Returns:
            List of weakness descriptions
        """
        summary = []

        # Coverage weaknesses
        coverage = results.get("coverage", {})
        if coverage.get("analyzed"):
            weak_zones = coverage.get("weak_zones", [])
            if weak_zones:
                summary.append(
                    f"Low coverage in zones: {', '.join(weak_zones)}. "
                    "Consider training movement to these areas."
                )

            if coverage.get("center_bias", 0) > 50:
                summary.append(
                    "Heavy center bias detected. Opponent may exploit corners."
                )

        # Movement weaknesses
        movement = results.get("movement", {})
        if movement.get("analyzed"):
            slowest = movement.get("slowest_direction")
            if slowest:
                summary.append(
                    f"Slower movement towards {slowest} direction. "
                    f"Opponent may target this side."
                )

            asymmetry = movement.get("movement_asymmetry", {})
            if asymmetry.get("lateral", 0) > 2:
                summary.append("Significant lateral movement asymmetry detected.")

        # Shot weaknesses
        shots = results.get("shots", {})
        if shots.get("analyzed"):
            underused = shots.get("underused_shots", [])
            if underused:
                summary.append(
                    f"Underused shot types: {', '.join(underused)}. "
                    "Adding variety may improve effectiveness."
                )

        if not summary:
            summary.append("No significant weaknesses detected in available data.")

        return summary
