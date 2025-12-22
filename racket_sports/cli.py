"""
Command-line interface for racket sports analytics.
"""

import argparse
import json
import logging
import sys
from pathlib import Path

from racket_sports.pipeline import AnalysisPipeline


def setup_logging(verbose: bool = False):
    """Configure logging."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def main():
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Racket Sports Analytics - AI-powered video analysis",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Analyze Instagram reel
  python -m racket_sports.analyze --source instagram --url "https://instagram.com/reel/..."

  # Analyze local video
  python -m racket_sports.analyze --source local --path video.mp4

  # Use table tennis config
  python -m racket_sports.analyze --sport table_tennis --source local --path video.mp4
        """,
    )

    parser.add_argument(
        "--sport",
        choices=["badminton", "table_tennis"],
        default="badminton",
        help="Sport type (default: badminton)",
    )
    parser.add_argument(
        "--source",
        choices=["instagram", "local", "youtube"],
        required=True,
        help="Video source type",
    )
    parser.add_argument(
        "--url",
        help="URL for remote video sources (instagram, youtube)",
    )
    parser.add_argument(
        "--path",
        help="Path to local video file",
    )
    parser.add_argument(
        "--output-dir",
        default="data/output",
        help="Output directory for results (default: data/output)",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable verbose logging",
    )
    parser.add_argument(
        "--save-json",
        action="store_true",
        help="Save results as JSON file",
    )

    args = parser.parse_args()

    # Validate arguments
    if args.source in ["instagram", "youtube"] and not args.url:
        parser.error(f"--url is required for source '{args.source}'")
    if args.source == "local" and not args.path:
        parser.error("--path is required for source 'local'")

    setup_logging(args.verbose)
    logger = logging.getLogger(__name__)

    try:
        # Initialize pipeline
        logger.info(f"Initializing {args.sport} analysis pipeline...")
        pipeline = AnalysisPipeline(sport=args.sport)

        # Run analysis
        logger.info("Starting video analysis...")
        results = pipeline.analyze_video(
            source=args.source,
            url=args.url,
            path=args.path,
            output_dir=args.output_dir,
        )

        # Output results
        if args.save_json:
            output_path = Path(args.output_dir) / "results.json"
            with open(output_path, "w") as f:
                json.dump(results, f, indent=2, default=str)
            logger.info(f"Results saved to {output_path}")

        # Print summary
        print("\n" + "=" * 50)
        print("ANALYSIS COMPLETE")
        print("=" * 50)
        print(f"Frames processed: {results['video_info']['frame_count']}")
        print(f"Detections: {len([t for t in results['tracking'] if t.get('position')])}")
        if results['speeds']:
            max_speed = max(results['speeds'], default=0)
            print(f"Max speed detected: {max_speed:.1f} km/h")
        print("=" * 50)

    except Exception as e:
        logger.error(f"Analysis failed: {e}")
        if args.verbose:
            import traceback
            traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
