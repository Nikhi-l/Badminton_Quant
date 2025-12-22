"""
Report generation for analytics results.

Generates:
- JSON reports
- Summary text reports
- Social media captions
"""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class ReportGenerator:
    """
    Generates analytics reports in various formats.

    Supports:
    - JSON export
    - Text summary
    - Social media captions
    """

    def __init__(self, config: dict[str, Any]):
        """
        Initialize report generator.

        Args:
            config: Configuration dictionary
        """
        self.config = config
        self.sport = config.get("sport", "badminton")

    def generate_json_report(
        self,
        results: dict[str, Any],
        output_path: Path,
    ) -> Path:
        """
        Generate JSON report.

        Args:
            results: Analysis results
            output_path: Output file path

        Returns:
            Path to generated report
        """
        report = {
            "generated_at": datetime.now().isoformat(),
            "sport": self.sport,
            "video_info": results.get("video_info", {}),
            "summary": self._generate_summary(results),
            "detailed_results": self._prepare_for_json(results),
        }

        with open(output_path, "w") as f:
            json.dump(report, f, indent=2, default=str)

        logger.info(f"JSON report saved to {output_path}")
        return output_path

    def _prepare_for_json(self, results: dict[str, Any]) -> dict[str, Any]:
        """Prepare results for JSON serialization."""
        import numpy as np

        def convert(obj):
            if isinstance(obj, np.ndarray):
                return obj.tolist()
            elif isinstance(obj, np.floating):
                return float(obj)
            elif isinstance(obj, np.integer):
                return int(obj)
            elif isinstance(obj, dict):
                return {k: convert(v) for k, v in obj.items()}
            elif isinstance(obj, list):
                return [convert(v) for v in obj]
            return obj

        return convert(results)

    def _generate_summary(self, results: dict[str, Any]) -> dict[str, Any]:
        """Generate summary statistics."""
        summary = {}

        # Video info
        video_info = results.get("video_info", {})
        summary["duration_seconds"] = video_info.get("frame_count", 0) / max(
            video_info.get("fps", 30), 1
        )

        # Tracking stats
        tracking = results.get("tracking", [])
        detected_frames = sum(1 for t in tracking if t.get("position"))
        summary["detection_rate"] = detected_frames / max(len(tracking), 1)

        # Speed stats
        speeds = results.get("speeds", [])
        if speeds:
            summary["max_speed_kmh"] = max(speeds)
            summary["avg_speed_kmh"] = sum(speeds) / len(speeds)

        # Pose stats
        poses = results.get("poses", [])
        detected_poses = sum(1 for p in poses if p.get("detected"))
        summary["pose_detection_rate"] = detected_poses / max(len(poses), 1)

        return summary

    def generate_text_summary(self, results: dict[str, Any]) -> str:
        """
        Generate human-readable text summary.

        Args:
            results: Analysis results

        Returns:
            Summary text
        """
        summary = self._generate_summary(results)
        video_info = results.get("video_info", {})

        lines = [
            "=" * 50,
            f"RACKET SPORTS ANALYSIS REPORT",
            f"Sport: {self.sport.replace('_', ' ').title()}",
            "=" * 50,
            "",
            "VIDEO INFORMATION",
            "-" * 30,
            f"Duration: {summary.get('duration_seconds', 0):.1f} seconds",
            f"Resolution: {video_info.get('resolution', ['N/A', 'N/A'])}",
            f"FPS: {video_info.get('fps', 'N/A')}",
            "",
            "TRACKING PERFORMANCE",
            "-" * 30,
            f"Detection Rate: {summary.get('detection_rate', 0) * 100:.1f}%",
            f"Pose Detection Rate: {summary.get('pose_detection_rate', 0) * 100:.1f}%",
            "",
        ]

        if summary.get("max_speed_kmh"):
            lines.extend([
                "SPEED ANALYSIS",
                "-" * 30,
                f"Maximum Speed: {summary['max_speed_kmh']:.1f} km/h",
                f"Average Speed: {summary.get('avg_speed_kmh', 0):.1f} km/h",
                "",
            ])

        # Add weakness summary if available
        weakness = results.get("weakness", {})
        if weakness.get("summary"):
            lines.extend([
                "WEAKNESS ANALYSIS",
                "-" * 30,
            ])
            for item in weakness["summary"]:
                lines.append(f"• {item}")
            lines.append("")

        lines.extend([
            "=" * 50,
            f"Report generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            "=" * 50,
        ])

        return "\n".join(lines)

    def generate_social_caption(
        self,
        results: dict[str, Any],
        platform: str = "instagram",
    ) -> str:
        """
        Generate social media caption.

        Args:
            results: Analysis results
            platform: Social media platform

        Returns:
            Caption text
        """
        summary = self._generate_summary(results)

        # Build caption
        lines = []

        # Sport-specific emoji
        sport_emoji = "🏸" if self.sport == "badminton" else "🏓"

        lines.append(f"{sport_emoji} {self.sport.replace('_', ' ').title()} Analysis")
        lines.append("")

        # Speed highlight
        if summary.get("max_speed_kmh"):
            speed = summary["max_speed_kmh"]
            if speed > 200:
                lines.append(f"🚀 SMASH DETECTED!")
            lines.append(f"⚡ Max Speed: {speed:.0f} km/h")

        lines.append("")
        lines.append("📊 Analysis powered by AI")
        lines.append("")

        # Hashtags
        hashtags = [
            f"#{self.sport}",
            "#sportsanalytics",
            "#AI",
            "#computervision",
        ]
        if self.sport == "badminton":
            hashtags.extend(["#badmintonplayer", "#badmintonlife", "#smash"])
        elif self.sport == "table_tennis":
            hashtags.extend(["#tabletennis", "#pingpong", "#tabletennisplayer"])

        lines.append(" ".join(hashtags))

        return "\n".join(lines)

    def save_text_report(
        self,
        results: dict[str, Any],
        output_path: Path,
    ) -> Path:
        """Save text report to file."""
        text = self.generate_text_summary(results)

        with open(output_path, "w") as f:
            f.write(text)

        logger.info(f"Text report saved to {output_path}")
        return output_path
