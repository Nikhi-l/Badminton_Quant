"""
Main video acquisition class combining multiple sources.
"""

import logging
from pathlib import Path
from typing import Any, Optional

import cv2

from racket_sports.video_acquisition.instagram import download_instagram_reel

logger = logging.getLogger(__name__)


class VideoAcquisition:
    """
    Unified video acquisition from multiple sources.

    Supports:
    - Instagram reels
    - Local files
    - YouTube (future)
    - Direct camera feed (future)
    """

    def __init__(self, config: dict[str, Any]):
        """
        Initialize video acquisition.

        Args:
            config: Configuration dictionary
        """
        self.config = config
        self.video_config = config.get("video", {})

        self.max_fps = self.video_config.get("max_fps", 30)
        self.target_resolution = self.video_config.get("target_resolution", [1280, 720])

    def download_instagram(
        self,
        url: str,
        output_dir: str = "data/input",
        cookies_file: Optional[str] = None,
    ) -> Path:
        """
        Download video from Instagram.

        Args:
            url: Instagram reel/post URL
            output_dir: Output directory
            cookies_file: Optional cookies file for authentication

        Returns:
            Path to downloaded video
        """
        return download_instagram_reel(url, output_dir, cookies_file)

    def load_local(self, path: str) -> Path:
        """
        Load a local video file.

        Args:
            path: Path to video file

        Returns:
            Path object (validated)

        Raises:
            FileNotFoundError: If file doesn't exist
            ValueError: If file is not a valid video
        """
        video_path = Path(path)

        if not video_path.exists():
            raise FileNotFoundError(f"Video file not found: {path}")

        # Validate it's a video
        cap = cv2.VideoCapture(str(video_path))
        if not cap.isOpened():
            raise ValueError(f"Cannot open video file: {path}")
        cap.release()

        logger.info(f"Loaded local video: {video_path}")
        return video_path

    def get_video_info(self, path: Path) -> dict[str, Any]:
        """
        Get information about a video file.

        Args:
            path: Path to video file

        Returns:
            Video metadata dictionary
        """
        cap = cv2.VideoCapture(str(path))

        info = {
            "path": str(path),
            "fps": cap.get(cv2.CAP_PROP_FPS),
            "frame_count": int(cap.get(cv2.CAP_PROP_FRAME_COUNT)),
            "width": int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)),
            "height": int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)),
            "duration_s": cap.get(cv2.CAP_PROP_FRAME_COUNT) / cap.get(cv2.CAP_PROP_FPS),
            "codec": int(cap.get(cv2.CAP_PROP_FOURCC)),
        }

        cap.release()
        return info

    def preprocess_video(
        self,
        input_path: Path,
        output_path: Optional[Path] = None,
        target_fps: Optional[int] = None,
        target_resolution: Optional[tuple[int, int]] = None,
    ) -> Path:
        """
        Preprocess video for analysis.

        Args:
            input_path: Input video path
            output_path: Output path (optional, creates temp file)
            target_fps: Target FPS (optional)
            target_resolution: Target resolution as (width, height)

        Returns:
            Path to preprocessed video
        """
        target_fps = target_fps or self.max_fps
        target_resolution = target_resolution or tuple(self.target_resolution)

        cap = cv2.VideoCapture(str(input_path))
        original_fps = cap.get(cv2.CAP_PROP_FPS)

        # Determine output path
        if output_path is None:
            output_path = input_path.parent / f"{input_path.stem}_processed.mp4"

        # Set up writer
        fourcc = cv2.VideoWriter_fourcc(*"mp4v")
        out = cv2.VideoWriter(
            str(output_path),
            fourcc,
            min(target_fps, original_fps),
            target_resolution,
        )

        # Frame skip for FPS reduction
        frame_skip = max(1, int(original_fps / target_fps))
        frame_idx = 0

        while True:
            ret, frame = cap.read()
            if not ret:
                break

            if frame_idx % frame_skip == 0:
                # Resize if needed
                if (frame.shape[1], frame.shape[0]) != target_resolution:
                    frame = cv2.resize(frame, target_resolution)
                out.write(frame)

            frame_idx += 1

        cap.release()
        out.release()

        logger.info(f"Preprocessed video saved to: {output_path}")
        return output_path
