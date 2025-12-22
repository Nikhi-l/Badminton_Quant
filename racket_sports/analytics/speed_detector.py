"""
Speed detection for shuttlecock/ball and player movement.

Calculates speeds from trajectory data using kinematic analysis
with optional Kalman filtering for noise reduction.
"""

import logging
from typing import Any, Optional

import numpy as np

logger = logging.getLogger(__name__)


class SpeedDetector:
    """
    Detects and calculates speeds from tracking data.

    Supports:
    - Shuttlecock/ball speed (smash detection)
    - Player movement speed
    - Direction-specific speed analysis
    """

    def __init__(self, config: dict[str, Any]):
        """
        Initialize speed detector.

        Args:
            config: Configuration dictionary
        """
        self.config = config
        self.sport = config.get("sport", "badminton")

        analytics_config = config.get("analytics", {})
        speed_config = analytics_config.get("speed", {})

        self.use_kalman = speed_config.get("kalman_filter", True)
        self.min_trajectory_frames = speed_config.get("min_trajectory_frames", 5)
        self.smash_threshold_kmh = speed_config.get("smash_threshold_kmh", 200)

        # Court/table dimensions for pixel-to-meter conversion
        court_config = config.get("court", config.get("table", {}))
        self.court_length_m = court_config.get("length_m", 13.4)  # Default: badminton

        # Calibration (pixels per meter) - set during court detection
        self.pixels_per_meter: Optional[float] = None

    def set_calibration(self, pixels_per_meter: float) -> None:
        """
        Set pixel-to-meter calibration.

        Args:
            pixels_per_meter: Conversion ratio
        """
        self.pixels_per_meter = pixels_per_meter
        logger.info(f"Calibration set: {pixels_per_meter:.2f} px/m")

    def calculate_speeds(
        self,
        positions: list[tuple[float, float]],
        fps: float,
        smooth: bool = True,
    ) -> list[float]:
        """
        Calculate speeds from position sequence.

        Args:
            positions: List of (x, y) positions in pixels
            fps: Video frame rate
            smooth: Whether to smooth the trajectory first

        Returns:
            List of speeds in km/h
        """
        if len(positions) < 2:
            return []

        positions = np.array(positions)

        if smooth:
            positions = self._smooth_trajectory(positions)

        # Calculate velocities (pixels per frame)
        velocities = np.diff(positions, axis=0)

        # Calculate speed magnitudes
        speeds_px_per_frame = np.linalg.norm(velocities, axis=1)

        # Convert to pixels per second
        speeds_px_per_sec = speeds_px_per_frame * fps

        # Convert to m/s if calibration available
        if self.pixels_per_meter:
            speeds_m_per_sec = speeds_px_per_sec / self.pixels_per_meter
        else:
            # Estimate based on typical court size
            # Assume camera captures full court width (~6m for badminton)
            estimated_px_per_m = 1280 / 6.0  # Rough estimate
            speeds_m_per_sec = speeds_px_per_sec / estimated_px_per_m
            logger.debug("Using estimated calibration")

        # Convert to km/h
        speeds_kmh = speeds_m_per_sec * 3.6

        return speeds_kmh.tolist()

    def _smooth_trajectory(
        self,
        positions: np.ndarray,
        window_size: int = 3,
    ) -> np.ndarray:
        """
        Smooth trajectory using moving average.

        Args:
            positions: Array of positions
            window_size: Smoothing window size

        Returns:
            Smoothed positions
        """
        if len(positions) < window_size:
            return positions

        smoothed = np.zeros_like(positions)

        for i in range(len(positions)):
            start = max(0, i - window_size // 2)
            end = min(len(positions), i + window_size // 2 + 1)
            smoothed[i] = positions[start:end].mean(axis=0)

        return smoothed

    def detect_smash(
        self,
        speeds: list[float],
        threshold: Optional[float] = None,
    ) -> list[dict[str, Any]]:
        """
        Detect smash events from speed data.

        Args:
            speeds: List of speeds in km/h
            threshold: Speed threshold for smash (km/h)

        Returns:
            List of smash events with frame indices and speeds
        """
        threshold = threshold or self.smash_threshold_kmh
        smashes = []

        speeds = np.array(speeds)

        # Find peaks above threshold
        for i in range(1, len(speeds) - 1):
            if speeds[i] > threshold:
                # Check if it's a local maximum
                if speeds[i] > speeds[i - 1] and speeds[i] > speeds[i + 1]:
                    smashes.append({
                        "frame": i,
                        "speed_kmh": float(speeds[i]),
                        "above_threshold": True,
                    })

        return smashes

    def calculate_player_speed(
        self,
        pose_results: list[dict[str, Any]],
        fps: float,
    ) -> dict[str, Any]:
        """
        Calculate player movement speed from pose data.

        Args:
            pose_results: List of pose estimation results
            fps: Video frame rate

        Returns:
            Player speed analysis
        """
        # Extract hip center positions as player position
        positions = []

        for pose in pose_results:
            if not pose.get("detected"):
                continue

            landmarks = pose.get("landmarks_2d")
            if landmarks is None:
                continue

            landmarks = np.array(landmarks)

            # Use hip center as player position
            left_hip = landmarks[23]  # LEFT_HIP
            right_hip = landmarks[24]  # RIGHT_HIP
            hip_center = (left_hip + right_hip) / 2

            positions.append(tuple(hip_center))

        if len(positions) < 2:
            return {"analyzed": False}

        # Calculate speeds
        speeds = self.calculate_speeds(positions, fps)

        if not speeds:
            return {"analyzed": False}

        return {
            "analyzed": True,
            "speeds_kmh": speeds,
            "max_speed_kmh": max(speeds),
            "avg_speed_kmh": np.mean(speeds),
            "total_distance_m": self._calculate_distance(positions),
        }

    def _calculate_distance(self, positions: list[tuple[float, float]]) -> float:
        """Calculate total distance traveled."""
        if len(positions) < 2:
            return 0.0

        positions = np.array(positions)
        distances = np.linalg.norm(np.diff(positions, axis=0), axis=1)
        total_px = distances.sum()

        if self.pixels_per_meter:
            return total_px / self.pixels_per_meter
        else:
            # Estimate
            return total_px / (1280 / 6.0)

    def analyze_direction_speeds(
        self,
        positions: list[tuple[float, float]],
        fps: float,
    ) -> dict[str, float]:
        """
        Analyze speeds in different directions.

        Args:
            positions: List of positions
            fps: Frame rate

        Returns:
            Speed analysis by direction
        """
        if len(positions) < 2:
            return {}

        positions = np.array(positions)
        velocities = np.diff(positions, axis=0) * fps

        # Separate horizontal and vertical components
        vx = velocities[:, 0]
        vy = velocities[:, 1]

        # Convert to m/s (estimated)
        px_per_m = self.pixels_per_meter or (1280 / 6.0)
        vx_ms = vx / px_per_m
        vy_ms = vy / px_per_m

        return {
            "lateral_max_kmh": float(np.abs(vx_ms).max() * 3.6),
            "lateral_avg_kmh": float(np.abs(vx_ms).mean() * 3.6),
            "forward_backward_max_kmh": float(np.abs(vy_ms).max() * 3.6),
            "forward_backward_avg_kmh": float(np.abs(vy_ms).mean() * 3.6),
            "left_movements": int((vx < 0).sum()),
            "right_movements": int((vx > 0).sum()),
            "forward_movements": int((vy < 0).sum()),  # Up in image
            "backward_movements": int((vy > 0).sum()),  # Down in image
        }
