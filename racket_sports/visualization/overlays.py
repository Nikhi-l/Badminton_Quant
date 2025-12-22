"""
Video overlay generation for annotated output videos.

Creates annotated videos with:
- Tracking visualization
- Pose skeleton overlay
- Speed displays
- Shot labels
"""

import logging
from pathlib import Path
from typing import Any, Optional

import cv2
import numpy as np

logger = logging.getLogger(__name__)


class VideoOverlay:
    """
    Generates annotated video overlays.

    Features:
    - Tracking trail visualization
    - Pose skeleton overlay
    - Speed/metrics display
    - Shot type labels
    """

    def __init__(self, config: dict[str, Any]):
        """
        Initialize video overlay generator.

        Args:
            config: Configuration dictionary
        """
        self.config = config

        output_config = config.get("output", {})
        self.add_tracking = output_config.get("tracking_overlay", True)
        self.add_pose = output_config.get("pose_overlay", True)
        self.add_metrics = output_config.get("metrics_overlay", True)

        # Visual settings
        self.tracking_color = (0, 255, 255)  # Yellow
        self.pose_color = (0, 255, 0)  # Green
        self.text_color = (255, 255, 255)  # White
        self.trail_length = 20

    def process_video(
        self,
        input_path: Path,
        output_path: Path,
        tracking_results: list[dict[str, Any]],
        pose_results: list[dict[str, Any]],
        analytics: dict[str, Any],
    ) -> Path:
        """
        Process video and add overlays.

        Args:
            input_path: Input video path
            output_path: Output video path
            tracking_results: Frame-by-frame tracking results
            pose_results: Frame-by-frame pose results
            analytics: Analytics results

        Returns:
            Path to output video
        """
        cap = cv2.VideoCapture(str(input_path))

        fps = cap.get(cv2.CAP_PROP_FPS)
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

        fourcc = cv2.VideoWriter_fourcc(*"mp4v")
        out = cv2.VideoWriter(str(output_path), fourcc, fps, (width, height))

        frame_idx = 0
        trail = []

        while True:
            ret, frame = cap.read()
            if not ret:
                break

            # Get frame data
            tracking = tracking_results[frame_idx] if frame_idx < len(tracking_results) else {}
            pose = pose_results[frame_idx] if frame_idx < len(pose_results) else {}

            # Add overlays
            if self.add_tracking:
                frame = self._draw_tracking(frame, tracking, trail)

            if self.add_pose:
                frame = self._draw_pose(frame, pose)

            if self.add_metrics:
                frame = self._draw_metrics(frame, tracking, analytics, frame_idx)

            # Update trail
            pos = tracking.get("position")
            if pos:
                trail.append(pos)
                if len(trail) > self.trail_length:
                    trail.pop(0)

            out.write(frame)
            frame_idx += 1

        cap.release()
        out.release()

        logger.info(f"Annotated video saved to {output_path}")
        return output_path

    def _draw_tracking(
        self,
        frame: np.ndarray,
        tracking: dict[str, Any],
        trail: list[tuple[float, float]],
    ) -> np.ndarray:
        """Draw tracking overlay."""
        # Draw trail
        if len(trail) > 1:
            for i in range(1, len(trail)):
                alpha = i / len(trail)
                color = tuple(int(c * alpha) for c in self.tracking_color)
                pt1 = (int(trail[i - 1][0]), int(trail[i - 1][1]))
                pt2 = (int(trail[i][0]), int(trail[i][1]))
                cv2.line(frame, pt1, pt2, color, 2)

        # Draw current position
        pos = tracking.get("position")
        if pos:
            center = (int(pos[0]), int(pos[1]))
            cv2.circle(frame, center, 8, self.tracking_color, -1)
            cv2.circle(frame, center, 10, (255, 255, 255), 2)

        # Draw bounding box
        bbox = tracking.get("bbox")
        if bbox:
            pt1 = (int(bbox[0]), int(bbox[1]))
            pt2 = (int(bbox[2]), int(bbox[3]))
            cv2.rectangle(frame, pt1, pt2, self.tracking_color, 2)

        return frame

    def _draw_pose(
        self,
        frame: np.ndarray,
        pose: dict[str, Any],
    ) -> np.ndarray:
        """Draw pose skeleton overlay."""
        if not pose.get("detected"):
            return frame

        landmarks = pose.get("landmarks_2d")
        if landmarks is None:
            return frame

        landmarks = np.array(landmarks)

        # Draw connections
        connections = [
            (11, 12), (11, 23), (12, 24), (23, 24),
            (11, 13), (13, 15), (12, 14), (14, 16),
            (23, 25), (25, 27), (24, 26), (26, 28),
        ]

        for start_idx, end_idx in connections:
            start = landmarks[start_idx]
            end = landmarks[end_idx]
            cv2.line(
                frame,
                (int(start[0]), int(start[1])),
                (int(end[0]), int(end[1])),
                self.pose_color,
                2,
            )

        # Draw key landmarks
        key_landmarks = [0, 11, 12, 13, 14, 15, 16, 23, 24, 25, 26, 27, 28]
        for idx in key_landmarks:
            pt = landmarks[idx]
            cv2.circle(frame, (int(pt[0]), int(pt[1])), 4, self.pose_color, -1)

        return frame

    def _draw_metrics(
        self,
        frame: np.ndarray,
        tracking: dict[str, Any],
        analytics: dict[str, Any],
        frame_idx: int,
    ) -> np.ndarray:
        """Draw metrics overlay."""
        # Background for text
        overlay = frame.copy()
        cv2.rectangle(overlay, (10, 10), (300, 120), (0, 0, 0), -1)
        cv2.addWeighted(overlay, 0.5, frame, 0.5, 0, frame)

        # Frame counter
        cv2.putText(
            frame,
            f"Frame: {frame_idx}",
            (20, 35),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.6,
            self.text_color,
            1,
        )

        # Confidence
        conf = tracking.get("confidence", 0)
        cv2.putText(
            frame,
            f"Confidence: {conf:.2f}",
            (20, 60),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.6,
            self.text_color,
            1,
        )

        # Speed (if available in analytics)
        speeds = analytics.get("speeds", [])
        if frame_idx < len(speeds):
            speed = speeds[frame_idx]
            color = (0, 255, 0) if speed < 200 else (0, 0, 255)
            cv2.putText(
                frame,
                f"Speed: {speed:.1f} km/h",
                (20, 85),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.6,
                color,
                1,
            )

        # Max speed
        if speeds:
            max_speed = max(speeds)
            cv2.putText(
                frame,
                f"Max Speed: {max_speed:.1f} km/h",
                (20, 110),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.6,
                self.text_color,
                1,
            )

        return frame

    def draw_frame(
        self,
        frame: np.ndarray,
        tracking: Optional[dict[str, Any]] = None,
        pose: Optional[dict[str, Any]] = None,
        speed: Optional[float] = None,
    ) -> np.ndarray:
        """
        Draw overlays on a single frame.

        Args:
            frame: Input frame
            tracking: Tracking result
            pose: Pose result
            speed: Current speed

        Returns:
            Annotated frame
        """
        output = frame.copy()

        if tracking and self.add_tracking:
            output = self._draw_tracking(output, tracking, [])

        if pose and self.add_pose:
            output = self._draw_pose(output, pose)

        if speed is not None and self.add_metrics:
            cv2.putText(
                output,
                f"Speed: {speed:.1f} km/h",
                (20, 40),
                cv2.FONT_HERSHEY_SIMPLEX,
                1.0,
                self.text_color,
                2,
            )

        return output
