"""
Analytics module for sports-specific analysis.

Includes:
- Speed detection (smash, movement)
- Heatmap generation
- Shot classification
- Weakness analysis
"""

from racket_sports.analytics.speed_detector import SpeedDetector
from racket_sports.analytics.heatmap import HeatmapGenerator
from racket_sports.analytics.shot_classifier import ShotClassifier
from racket_sports.analytics.weakness import WeaknessAnalyzer

__all__ = [
    "SpeedDetector",
    "HeatmapGenerator",
    "ShotClassifier",
    "WeaknessAnalyzer",
]
