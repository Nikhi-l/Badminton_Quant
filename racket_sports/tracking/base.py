"""
Base classes for object tracking.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Optional

import numpy as np


@dataclass
class TrackingResult:
    """Result from a single frame tracking."""

    position: Optional[tuple[float, float]] = None  # (x, y) center
    bbox: Optional[tuple[float, float, float, float]] = None  # (x1, y1, x2, y2)
    confidence: float = 0.0
    class_id: int = 0
    class_name: str = ""
    mask: Optional[np.ndarray] = None
    trajectory: list[tuple[float, float]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "position": self.position,
            "bbox": self.bbox,
            "confidence": self.confidence,
            "class_id": self.class_id,
            "class_name": self.class_name,
            "trajectory": self.trajectory,
            "metadata": self.metadata,
        }


class BaseTracker(ABC):
    """
    Abstract base class for object trackers.

    All tracker implementations should inherit from this class.
    """

    def __init__(self, config: dict[str, Any]):
        """
        Initialize tracker.

        Args:
            config: Configuration dictionary
        """
        self.config = config
        self.tracking_config = config.get("tracking", {})
        self.trajectory: list[tuple[float, float]] = []
        self.frame_count = 0

    @abstractmethod
    def track(self, frame: np.ndarray) -> dict[str, Any]:
        """
        Track objects in a single frame.

        Args:
            frame: BGR image frame

        Returns:
            Tracking results dictionary
        """
        pass

    @abstractmethod
    def reset(self) -> None:
        """Reset tracker state."""
        pass

    def get_trajectory(self) -> list[tuple[float, float]]:
        """Get current trajectory."""
        return self.trajectory.copy()

    def add_to_trajectory(self, position: tuple[float, float]) -> None:
        """Add position to trajectory."""
        self.trajectory.append(position)

    def clear_trajectory(self) -> None:
        """Clear trajectory history."""
        self.trajectory.clear()


class KalmanTracker:
    """
    Kalman filter for smoothing object trajectories.

    Provides prediction and smoothing for noisy detections.
    """

    def __init__(self, process_noise: float = 1.0, measurement_noise: float = 1.0):
        """
        Initialize Kalman filter.

        Args:
            process_noise: Process noise covariance
            measurement_noise: Measurement noise covariance
        """
        try:
            from filterpy.kalman import KalmanFilter
        except ImportError:
            raise ImportError("filterpy is required. Install with: pip install filterpy")

        # State: [x, y, vx, vy]
        self.kf = KalmanFilter(dim_x=4, dim_z=2)

        # State transition matrix
        self.kf.F = np.array([
            [1, 0, 1, 0],
            [0, 1, 0, 1],
            [0, 0, 1, 0],
            [0, 0, 0, 1],
        ])

        # Measurement matrix
        self.kf.H = np.array([
            [1, 0, 0, 0],
            [0, 1, 0, 0],
        ])

        # Covariance matrices
        self.kf.P *= 100
        self.kf.R *= measurement_noise
        self.kf.Q = np.eye(4) * process_noise

        self.initialized = False

    def update(self, position: tuple[float, float]) -> tuple[float, float]:
        """
        Update filter with new measurement.

        Args:
            position: Measured (x, y) position

        Returns:
            Filtered (x, y) position
        """
        if not self.initialized:
            self.kf.x = np.array([position[0], position[1], 0, 0])
            self.initialized = True
            return position

        self.kf.predict()
        self.kf.update(np.array(position))

        return (float(self.kf.x[0]), float(self.kf.x[1]))

    def predict(self) -> tuple[float, float]:
        """
        Predict next position without measurement.

        Returns:
            Predicted (x, y) position
        """
        self.kf.predict()
        return (float(self.kf.x[0]), float(self.kf.x[1]))

    def get_velocity(self) -> tuple[float, float]:
        """
        Get current velocity estimate.

        Returns:
            (vx, vy) velocity
        """
        return (float(self.kf.x[2]), float(self.kf.x[3]))

    def reset(self) -> None:
        """Reset filter state."""
        self.initialized = False
        self.kf.x = np.zeros(4)
