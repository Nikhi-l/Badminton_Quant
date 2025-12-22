"""
Racket Sports Analytics

AI-powered sports analytics for racket sports (badminton, table tennis).
"""

__version__ = "0.1.0"
__author__ = "Your Name"

from racket_sports.config import load_config
from racket_sports.pipeline import AnalysisPipeline

__all__ = ["load_config", "AnalysisPipeline", "__version__"]
