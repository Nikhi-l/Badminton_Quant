"""
Heatmap generation for player movement visualization.

Creates visual representations of player positioning and movement
patterns on the court.
"""

import logging
from typing import Any, Optional

import numpy as np

logger = logging.getLogger(__name__)


class HeatmapGenerator:
    """
    Generates heatmaps from player position data.

    Features:
    - Position frequency heatmaps
    - Movement direction heatmaps
    - Shot location heatmaps
    """

    def __init__(self, config: dict[str, Any]):
        """
        Initialize heatmap generator.

        Args:
            config: Configuration dictionary
        """
        self.config = config

        analytics_config = config.get("analytics", {})
        heatmap_config = analytics_config.get("heatmap", {})

        self.resolution = tuple(heatmap_config.get("resolution", [100, 50]))
        self.gaussian_sigma = heatmap_config.get("gaussian_sigma", 2.0)

        # Frame dimensions (set during processing)
        self.frame_width: Optional[int] = None
        self.frame_height: Optional[int] = None

    def set_frame_dimensions(self, width: int, height: int) -> None:
        """Set frame dimensions for coordinate mapping."""
        self.frame_width = width
        self.frame_height = height

    def generate(
        self,
        pose_results: list[dict[str, Any]],
        normalize: bool = True,
    ) -> dict[str, Any]:
        """
        Generate heatmap from pose data.

        Args:
            pose_results: List of pose estimation results
            normalize: Whether to normalize the heatmap

        Returns:
            Heatmap data dictionary
        """
        # Extract player positions (hip center)
        positions = []

        for pose in pose_results:
            if not pose.get("detected"):
                continue

            landmarks = pose.get("landmarks_2d")
            if landmarks is None:
                continue

            landmarks = np.array(landmarks)

            # Use hip center
            left_hip = landmarks[23]
            right_hip = landmarks[24]
            hip_center = (left_hip + right_hip) / 2

            positions.append(hip_center)

        if not positions:
            return {
                "generated": False,
                "reason": "No pose data",
            }

        positions = np.array(positions)

        # Determine frame dimensions from data if not set
        if self.frame_width is None:
            self.frame_width = int(positions[:, 0].max()) + 100
            self.frame_height = int(positions[:, 1].max()) + 100

        # Create heatmap
        heatmap = self._create_heatmap(positions)

        if normalize:
            heatmap = self._normalize(heatmap)

        # Apply Gaussian smoothing
        heatmap = self._apply_gaussian(heatmap)

        return {
            "generated": True,
            "heatmap": heatmap.tolist(),
            "resolution": self.resolution,
            "position_count": len(positions),
            "stats": self._calculate_stats(positions),
        }

    def _create_heatmap(self, positions: np.ndarray) -> np.ndarray:
        """
        Create raw heatmap from positions.

        Args:
            positions: Array of (x, y) positions

        Returns:
            2D heatmap array
        """
        heatmap = np.zeros(self.resolution, dtype=np.float32)

        for pos in positions:
            # Map position to heatmap coordinates
            x = int(pos[0] / self.frame_width * (self.resolution[0] - 1))
            y = int(pos[1] / self.frame_height * (self.resolution[1] - 1))

            # Clamp to valid range
            x = max(0, min(x, self.resolution[0] - 1))
            y = max(0, min(y, self.resolution[1] - 1))

            heatmap[x, y] += 1

        return heatmap

    def _normalize(self, heatmap: np.ndarray) -> np.ndarray:
        """Normalize heatmap to [0, 1] range."""
        max_val = heatmap.max()
        if max_val > 0:
            return heatmap / max_val
        return heatmap

    def _apply_gaussian(self, heatmap: np.ndarray) -> np.ndarray:
        """Apply Gaussian blur for smoothing."""
        try:
            from scipy.ndimage import gaussian_filter
            return gaussian_filter(heatmap, sigma=self.gaussian_sigma)
        except ImportError:
            # Fallback to simple smoothing
            return self._simple_smooth(heatmap)

    def _simple_smooth(self, heatmap: np.ndarray, kernel_size: int = 3) -> np.ndarray:
        """Simple averaging smoothing fallback."""
        smoothed = np.zeros_like(heatmap)
        pad = kernel_size // 2

        for i in range(heatmap.shape[0]):
            for j in range(heatmap.shape[1]):
                i_start = max(0, i - pad)
                i_end = min(heatmap.shape[0], i + pad + 1)
                j_start = max(0, j - pad)
                j_end = min(heatmap.shape[1], j + pad + 1)
                smoothed[i, j] = heatmap[i_start:i_end, j_start:j_end].mean()

        return smoothed

    def _calculate_stats(self, positions: np.ndarray) -> dict[str, Any]:
        """Calculate position statistics."""
        return {
            "center_of_mass": positions.mean(axis=0).tolist(),
            "std_x": float(positions[:, 0].std()),
            "std_y": float(positions[:, 1].std()),
            "x_range": [float(positions[:, 0].min()), float(positions[:, 0].max())],
            "y_range": [float(positions[:, 1].min()), float(positions[:, 1].max())],
        }

    def render_heatmap(
        self,
        heatmap_data: dict[str, Any],
        output_path: Optional[str] = None,
        colormap: str = "jet",
    ) -> np.ndarray:
        """
        Render heatmap as an image.

        Args:
            heatmap_data: Heatmap data from generate()
            output_path: Optional path to save image
            colormap: Matplotlib colormap name

        Returns:
            RGB image array
        """
        try:
            import matplotlib.pyplot as plt
            import matplotlib.cm as cm
        except ImportError:
            raise ImportError("matplotlib is required for rendering")

        heatmap = np.array(heatmap_data["heatmap"])

        # Create figure
        fig, ax = plt.subplots(figsize=(12, 6))

        # Plot heatmap
        im = ax.imshow(
            heatmap.T,  # Transpose for correct orientation
            cmap=colormap,
            aspect="auto",
            origin="lower",
        )

        ax.set_title("Player Position Heatmap")
        ax.set_xlabel("Court Width")
        ax.set_ylabel("Court Length")
        plt.colorbar(im, ax=ax, label="Frequency")

        # Save if path provided
        if output_path:
            plt.savefig(output_path, dpi=150, bbox_inches="tight")
            logger.info(f"Heatmap saved to {output_path}")

        # Convert to array
        fig.canvas.draw()
        img = np.frombuffer(fig.canvas.tostring_rgb(), dtype=np.uint8)
        img = img.reshape(fig.canvas.get_width_height()[::-1] + (3,))

        plt.close(fig)

        return img

    def generate_shot_heatmap(
        self,
        shot_positions: list[tuple[float, float]],
    ) -> dict[str, Any]:
        """
        Generate heatmap of shot landing positions.

        Args:
            shot_positions: List of shot landing positions

        Returns:
            Heatmap data dictionary
        """
        if not shot_positions:
            return {"generated": False, "reason": "No shot data"}

        positions = np.array(shot_positions)

        heatmap = self._create_heatmap(positions)
        heatmap = self._normalize(heatmap)
        heatmap = self._apply_gaussian(heatmap)

        return {
            "generated": True,
            "heatmap": heatmap.tolist(),
            "resolution": self.resolution,
            "shot_count": len(shot_positions),
            "type": "shot_landing",
        }
