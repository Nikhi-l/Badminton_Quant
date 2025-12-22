"""
Main analysis pipeline for racket sports video processing.
"""

import logging
from pathlib import Path
from typing import Any, Optional

import cv2
import numpy as np

from racket_sports.config import Config, load_config
from racket_sports.video_acquisition import VideoAcquisition
from racket_sports.tracking import get_tracker
from racket_sports.pose import PoseEstimator
from racket_sports.analytics import SpeedDetector, HeatmapGenerator

logger = logging.getLogger(__name__)


class AnalysisPipeline:
    """
    Main pipeline for analyzing racket sports videos.

    Combines tracking, pose estimation, and analytics into a unified workflow.
    """

    def __init__(
        self,
        sport: str = "badminton",
        config_override: Optional[dict] = None,
    ):
        """
        Initialize the analysis pipeline.

        Args:
            sport: Sport type (badminton, table_tennis)
            config_override: Optional configuration overrides
        """
        self.sport = sport
        self.config_dict = load_config(sport)

        if config_override:
            from racket_sports.config import merge_configs
            self.config_dict = merge_configs(self.config_dict, config_override)

        self.config = Config(self.config_dict)

        # Initialize components (lazy loading)
        self._video_acquisition = None
        self._tracker = None
        self._pose_estimator = None
        self._speed_detector = None
        self._heatmap_generator = None

        logger.info(f"Initialized pipeline for {sport}")

    @property
    def video_acquisition(self) -> VideoAcquisition:
        """Lazy load video acquisition module."""
        if self._video_acquisition is None:
            self._video_acquisition = VideoAcquisition(self.config_dict)
        return self._video_acquisition

    @property
    def tracker(self):
        """Lazy load tracker."""
        if self._tracker is None:
            self._tracker = get_tracker(self.config_dict)
        return self._tracker

    @property
    def pose_estimator(self) -> PoseEstimator:
        """Lazy load pose estimator."""
        if self._pose_estimator is None:
            self._pose_estimator = PoseEstimator(self.config_dict)
        return self._pose_estimator

    @property
    def speed_detector(self) -> SpeedDetector:
        """Lazy load speed detector."""
        if self._speed_detector is None:
            self._speed_detector = SpeedDetector(self.config_dict)
        return self._speed_detector

    @property
    def heatmap_generator(self) -> HeatmapGenerator:
        """Lazy load heatmap generator."""
        if self._heatmap_generator is None:
            self._heatmap_generator = HeatmapGenerator(self.config_dict)
        return self._heatmap_generator

    def analyze_video(
        self,
        source: str,
        url: Optional[str] = None,
        path: Optional[str] = None,
        output_dir: Optional[str] = None,
    ) -> dict[str, Any]:
        """
        Analyze a video from various sources.

        Args:
            source: Video source type (instagram, local, youtube)
            url: URL for remote sources
            path: Path for local videos
            output_dir: Output directory for results

        Returns:
            Analysis results dictionary
        """
        # Set up output directory
        if output_dir is None:
            output_dir = Path("data/output")
        else:
            output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        # Acquire video
        logger.info(f"Acquiring video from {source}...")
        if source == "instagram":
            video_path = self.video_acquisition.download_instagram(url)
        elif source == "local":
            video_path = Path(path)
        else:
            raise ValueError(f"Unsupported source: {source}")

        # Process video
        results = self._process_video(video_path, output_dir)

        return results

    def _process_video(
        self,
        video_path: Path,
        output_dir: Path,
    ) -> dict[str, Any]:
        """
        Process a video file through the full pipeline.

        Args:
            video_path: Path to video file
            output_dir: Output directory

        Returns:
            Analysis results
        """
        logger.info(f"Processing video: {video_path}")

        # Open video
        cap = cv2.VideoCapture(str(video_path))
        if not cap.isOpened():
            raise ValueError(f"Could not open video: {video_path}")

        fps = cap.get(cv2.CAP_PROP_FPS)
        frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

        logger.info(f"Video: {width}x{height} @ {fps}fps, {frame_count} frames")

        # Initialize results
        results = {
            "video_info": {
                "path": str(video_path),
                "fps": fps,
                "frame_count": frame_count,
                "resolution": [width, height],
            },
            "tracking": [],
            "poses": [],
            "speeds": [],
            "heatmap": None,
        }

        # Process frames
        frame_idx = 0
        positions = []

        while True:
            ret, frame = cap.read()
            if not ret:
                break

            # Track shuttle/ball
            tracking_result = self.tracker.track(frame)
            results["tracking"].append(tracking_result)

            if tracking_result.get("position"):
                positions.append(tracking_result["position"])

            # Estimate pose
            pose_result = self.pose_estimator.estimate(frame)
            results["poses"].append(pose_result)

            frame_idx += 1
            if frame_idx % 100 == 0:
                logger.info(f"Processed {frame_idx}/{frame_count} frames")

        cap.release()

        # Calculate speeds
        if positions:
            speeds = self.speed_detector.calculate_speeds(
                positions,
                fps=fps,
            )
            results["speeds"] = speeds

        # Generate heatmap
        if results["poses"]:
            heatmap = self.heatmap_generator.generate(results["poses"])
            results["heatmap"] = heatmap

        logger.info("Analysis complete")
        return results

    def analyze_frame(self, frame: np.ndarray) -> dict[str, Any]:
        """
        Analyze a single frame.

        Args:
            frame: BGR image frame

        Returns:
            Frame analysis results
        """
        results = {
            "tracking": self.tracker.track(frame),
            "pose": self.pose_estimator.estimate(frame),
        }
        return results
