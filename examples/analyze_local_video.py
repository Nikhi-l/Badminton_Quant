#!/usr/bin/env python3
"""
Example: Analyze a local video file

This script demonstrates how to analyze a local video file
using the racket_sports package.
"""

import argparse
import logging
from pathlib import Path

from racket_sports.pipeline import AnalysisPipeline
from racket_sports.visualization.overlays import VideoOverlay
from racket_sports.visualization.reports import ReportGenerator

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


def main():
    """Run analysis on a local video."""
    parser = argparse.ArgumentParser(description="Analyze local badminton/table tennis video")
    parser.add_argument("video_path", help="Path to video file")
    parser.add_argument(
        "--sport",
        choices=["badminton", "table_tennis"],
        default="badminton",
        help="Sport type",
    )
    parser.add_argument(
        "--output-dir",
        default="data/output",
        help="Output directory",
    )
    parser.add_argument(
        "--annotate",
        action="store_true",
        help="Generate annotated video",
    )
    args = parser.parse_args()

    video_path = Path(args.video_path)
    if not video_path.exists():
        raise FileNotFoundError(f"Video not found: {video_path}")

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Initialize pipeline
    logger.info(f"Initializing {args.sport} analysis pipeline...")
    pipeline = AnalysisPipeline(sport=args.sport)

    # Run analysis
    logger.info(f"Analyzing video: {video_path}")
    results = pipeline.analyze_video(
        source="local",
        path=str(video_path),
        output_dir=str(output_dir),
    )

    # Print summary
    print("\n" + "=" * 50)
    print("ANALYSIS COMPLETE")
    print("=" * 50)

    video_info = results.get("video_info", {})
    print(f"Frames: {video_info.get('frame_count', 0)}")
    print(f"Resolution: {video_info.get('resolution', 'N/A')}")
    print(f"FPS: {video_info.get('fps', 0):.1f}")

    tracking = results.get("tracking", [])
    detected = sum(1 for t in tracking if t.get("position"))
    print(f"Detection Rate: {detected / max(len(tracking), 1) * 100:.1f}%")

    speeds = results.get("speeds", [])
    if speeds:
        print(f"Max Speed: {max(speeds):.1f} km/h")

    # Generate annotated video if requested
    if args.annotate:
        logger.info("Generating annotated video...")
        overlay = VideoOverlay(pipeline.config_dict)
        annotated_path = output_dir / f"{video_path.stem}_annotated.mp4"
        overlay.process_video(
            video_path,
            annotated_path,
            results.get("tracking", []),
            results.get("poses", []),
            results,
        )
        print(f"\nAnnotated video: {annotated_path}")

    # Generate reports
    report_gen = ReportGenerator(pipeline.config_dict)

    # JSON report
    json_path = output_dir / f"{video_path.stem}_report.json"
    report_gen.generate_json_report(results, json_path)
    print(f"JSON report: {json_path}")

    # Text report
    text_path = output_dir / f"{video_path.stem}_report.txt"
    report_gen.save_text_report(results, text_path)
    print(f"Text report: {text_path}")


if __name__ == "__main__":
    main()
