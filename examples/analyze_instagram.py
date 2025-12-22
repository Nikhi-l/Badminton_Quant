#!/usr/bin/env python3
"""
Example: Analyze an Instagram reel

This script demonstrates how to use the racket_sports package
to analyze a badminton video from Instagram.
"""

import logging
from pathlib import Path

from racket_sports.pipeline import AnalysisPipeline
from racket_sports.visualization.reports import ReportGenerator

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


def main():
    """Run analysis on an Instagram reel."""
    # Instagram reel URL
    # Replace with your own URL
    url = "https://www.instagram.com/reel/DSi1n47E0_Y/"

    # Initialize pipeline for badminton
    logger.info("Initializing badminton analysis pipeline...")
    pipeline = AnalysisPipeline(sport="badminton")

    # Run analysis
    logger.info(f"Analyzing video: {url}")
    try:
        results = pipeline.analyze_video(
            source="instagram",
            url=url,
            output_dir="data/output",
        )

        # Print summary
        print("\n" + "=" * 50)
        print("ANALYSIS COMPLETE")
        print("=" * 50)

        video_info = results.get("video_info", {})
        print(f"Frames: {video_info.get('frame_count', 0)}")
        print(f"FPS: {video_info.get('fps', 0):.1f}")

        speeds = results.get("speeds", [])
        if speeds:
            print(f"Max Speed: {max(speeds):.1f} km/h")
            print(f"Avg Speed: {sum(speeds)/len(speeds):.1f} km/h")

        # Generate report
        report_gen = ReportGenerator(pipeline.config_dict)
        report_path = Path("data/output/analysis_report.json")
        report_gen.generate_json_report(results, report_path)
        print(f"\nReport saved to: {report_path}")

        # Generate social caption
        caption = report_gen.generate_social_caption(results)
        print("\nSocial Media Caption:")
        print("-" * 30)
        print(caption)

    except Exception as e:
        logger.error(f"Analysis failed: {e}")
        raise


if __name__ == "__main__":
    main()
