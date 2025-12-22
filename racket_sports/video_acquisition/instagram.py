"""
Instagram video downloading utilities.

Uses yt-dlp for downloading Instagram reels and posts.
"""

import logging
import re
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


def extract_instagram_id(url: str) -> Optional[str]:
    """
    Extract the Instagram post/reel ID from a URL.

    Args:
        url: Instagram URL (reel, post, or TV)

    Returns:
        Post/reel ID or None if not found
    """
    patterns = [
        r"instagram\.com/reel/([A-Za-z0-9_-]+)",
        r"instagram\.com/p/([A-Za-z0-9_-]+)",
        r"instagram\.com/tv/([A-Za-z0-9_-]+)",
    ]

    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)

    return None


def download_instagram_reel(
    url: str,
    output_dir: str = "data/input",
    cookies_file: Optional[str] = None,
) -> Path:
    """
    Download an Instagram reel using yt-dlp.

    Args:
        url: Instagram reel URL
        output_dir: Directory to save the video
        cookies_file: Optional path to cookies file for authentication

    Returns:
        Path to downloaded video file
    """
    try:
        import yt_dlp
    except ImportError:
        raise ImportError("yt-dlp is required. Install with: pip install yt-dlp")

    # Create output directory
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    # Extract ID for filename
    video_id = extract_instagram_id(url) or "video"

    # Configure yt-dlp options
    ydl_opts = {
        "format": "bestvideo+bestaudio/best",
        "merge_output_format": "mp4",
        "outtmpl": str(output_path / f"{video_id}.%(ext)s"),
        "quiet": False,
        "no_warnings": False,
    }

    # Add cookies if provided
    if cookies_file:
        ydl_opts["cookiefile"] = cookies_file

    logger.info(f"Downloading Instagram video: {url}")

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            filename = ydl.prepare_filename(info)
            # Handle format merging
            if not filename.endswith(".mp4"):
                filename = filename.rsplit(".", 1)[0] + ".mp4"

        video_path = Path(filename)
        logger.info(f"Downloaded to: {video_path}")
        return video_path

    except Exception as e:
        logger.error(f"Failed to download video: {e}")
        raise


def get_instagram_info(url: str) -> dict:
    """
    Get information about an Instagram video without downloading.

    Args:
        url: Instagram URL

    Returns:
        Video information dictionary
    """
    try:
        import yt_dlp
    except ImportError:
        raise ImportError("yt-dlp is required. Install with: pip install yt-dlp")

    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)

    return {
        "id": info.get("id"),
        "title": info.get("title"),
        "duration": info.get("duration"),
        "uploader": info.get("uploader"),
        "description": info.get("description"),
        "thumbnail": info.get("thumbnail"),
        "formats": [
            {
                "format_id": f.get("format_id"),
                "ext": f.get("ext"),
                "resolution": f.get("resolution"),
                "fps": f.get("fps"),
            }
            for f in info.get("formats", [])
        ],
    }
