"""
Video acquisition module for downloading and preprocessing videos.
"""

from racket_sports.video_acquisition.acquisition import VideoAcquisition
from racket_sports.video_acquisition.instagram import download_instagram_reel

__all__ = ["VideoAcquisition", "download_instagram_reel"]
