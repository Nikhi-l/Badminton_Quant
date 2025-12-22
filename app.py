"""
Chainlit chatbot interface for Racket Sports Analytics.

A conversational interface for analyzing badminton and table tennis videos.
Users can submit Instagram reel links and receive detailed analytics.
"""

import asyncio
import logging
import traceback
from pathlib import Path
from typing import Optional

import chainlit as cl

from racket_sports.config import load_config
from racket_sports.pipeline import AnalysisPipeline
from racket_sports.video_acquisition.instagram import download_instagram_reel, extract_instagram_id
from racket_sports.visualization.reports import ReportGenerator

# Configure logging with format
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


@cl.on_chat_start
async def on_chat_start():
    """Initialize the chat session."""
    # Set default sport
    cl.user_session.set("sport", "badminton")
    cl.user_session.set("pipeline", None)

    # Welcome message with sport selection
    welcome_msg = """# Welcome to Racket Sports Analytics! 🏸🏓

I can analyze your badminton or table tennis videos to provide insights on:
- **Shuttle/Ball Tracking** - Track the object throughout the rally
- **Pose Estimation** - Analyze player body positions
- **Smash Speed Detection** - Measure shot speeds
- **Movement Heatmaps** - Visualize court coverage
- **Weakness Analysis** - Identify areas for improvement

## How to use:
1. **Select your sport** using the buttons below
2. **Share an Instagram reel link** of gameplay
3. **Wait for analysis** (usually 1-2 minutes)
4. **Review your results!**

Which sport would you like to analyze?"""

    # Create sport selection actions
    actions = [
        cl.Action(
            name="select_badminton",
            value="badminton",
            label="🏸 Badminton",
            description="Analyze badminton gameplay",
        ),
        cl.Action(
            name="select_table_tennis",
            value="table_tennis",
            label="🏓 Table Tennis",
            description="Analyze table tennis gameplay",
        ),
    ]

    await cl.Message(content=welcome_msg, actions=actions).send()


@cl.action_callback("select_badminton")
async def on_select_badminton(action: cl.Action):
    """Handle badminton selection."""
    await select_sport("badminton")


@cl.action_callback("select_table_tennis")
async def on_select_table_tennis(action: cl.Action):
    """Handle table tennis selection."""
    await select_sport("table_tennis")


async def select_sport(sport: str):
    """Set the selected sport and initialize pipeline."""
    logger.info(f"User selected sport: {sport}")
    cl.user_session.set("sport", sport)

    try:
        # Initialize pipeline for selected sport
        config = load_config(sport)
        pipeline = AnalysisPipeline(sport=sport)
        cl.user_session.set("pipeline", pipeline)
        logger.info(f"Pipeline initialized for {sport}")
    except Exception as e:
        logger.error(f"Failed to initialize pipeline: {e}")
        await cl.Message(
            content=f"❌ Error initializing {sport} pipeline: {str(e)}"
        ).send()
        return

    sport_emoji = "🏸" if sport == "badminton" else "🏓"
    sport_name = sport.replace("_", " ").title()

    await cl.Message(
        content=f"{sport_emoji} **{sport_name}** selected!\n\n"
        f"Now share an Instagram reel link of {sport_name.lower()} gameplay, "
        f"and I'll analyze it for you.\n\n"
        f"Example: `https://www.instagram.com/reel/ABC123/`"
    ).send()


@cl.on_message
async def on_message(message: cl.Message):
    """Handle incoming messages."""
    content = message.content.strip()

    # Check for sport change commands
    if content.lower() in ["badminton", "switch to badminton"]:
        await select_sport("badminton")
        return
    elif content.lower() in ["table tennis", "table_tennis", "ping pong", "switch to table tennis"]:
        await select_sport("table_tennis")
        return

    # Check for Instagram URL
    if "instagram.com" in content:
        await process_instagram_url(content)
        return

    # Check for help command
    if content.lower() in ["help", "?"]:
        await show_help()
        return

    # Default response
    await cl.Message(
        content="I can analyze Instagram reels of badminton or table tennis gameplay.\n\n"
        "Please share an Instagram reel link, or type **help** for more options."
    ).send()


async def process_instagram_url(url: str):
    """Process an Instagram reel URL and run analysis."""
    sport = cl.user_session.get("sport", "badminton")
    sport_emoji = "🏸" if sport == "badminton" else "🏓"

    logger.info(f"Processing Instagram URL: {url}")

    # Extract video ID
    video_id = extract_instagram_id(url)
    if not video_id:
        logger.warning(f"Could not extract video ID from URL: {url}")
        await cl.Message(
            content="❌ Could not extract video ID from the URL. "
            "Please make sure it's a valid Instagram reel URL."
        ).send()
        return

    logger.info(f"Extracted video ID: {video_id}")

    # Start analysis with steps
    async with cl.Step(name="Video Download", type="tool") as step:
        step.input = url
        await cl.Message(
            content=f"{sport_emoji} Starting analysis of Instagram reel...\n\n"
            f"**Video ID:** `{video_id}`"
        ).send()

        try:
            # Download video
            step.output = "Downloading video from Instagram..."
            logger.info("Starting video download...")
            video_path = await asyncio.to_thread(
                download_instagram_reel,
                url,
                "data/input",
            )
            step.output = f"Downloaded: {video_path}"
            logger.info(f"Video downloaded to: {video_path}")

        except Exception as e:
            error_msg = str(e)
            logger.error(f"Download failed: {error_msg}\n{traceback.format_exc()}")
            step.output = f"Download failed: {error_msg}"
            await cl.Message(
                content=f"❌ Failed to download video: {error_msg}\n\n"
                f"This might be due to:\n"
                f"- Private account\n"
                f"- Rate limiting\n"
                f"- Invalid URL\n\n"
                f"Please try again or use a different video."
            ).send()
            return

    # Run analysis pipeline
    async with cl.Step(name="Video Analysis", type="run") as analysis_step:
        analysis_step.input = str(video_path)

        try:
            # Get pipeline
            pipeline = cl.user_session.get("pipeline")
            if pipeline is None:
                logger.info("Creating new pipeline...")
                pipeline = AnalysisPipeline(sport=sport)
                cl.user_session.set("pipeline", pipeline)

            # Process video with progress updates
            await cl.Message(content="📊 Analyzing video frames...").send()

            # Run analysis
            logger.info("Starting video analysis...")
            results = await asyncio.to_thread(
                pipeline.analyze_video,
                source="local",
                path=str(video_path),
                output_dir="data/output",
            )

            analysis_step.output = "Analysis complete"
            logger.info("Video analysis completed successfully")

            # Log any errors from the analysis
            if results.get("errors"):
                logger.warning(f"Analysis completed with {len(results['errors'])} errors")
                for err in results["errors"][:5]:  # Log first 5 errors
                    logger.warning(f"  - {err}")

        except Exception as e:
            error_msg = str(e)
            logger.error(f"Analysis failed: {error_msg}\n{traceback.format_exc()}")
            analysis_step.output = f"Analysis failed: {error_msg}"
            await cl.Message(
                content=f"❌ Analysis failed: {error_msg}\n\n"
                f"Check the logs for more details."
            ).send()
            return

    # Generate and display results
    await display_results(results, video_id, sport)


async def display_results(results: dict, video_id: str, sport: str):
    """Display analysis results with elements."""
    logger.info(f"Displaying results for video: {video_id}")
    sport_emoji = "🏸" if sport == "badminton" else "🏓"

    # Generate summary
    video_info = results.get("video_info", {})
    speeds = results.get("speeds", [])
    tracking = results.get("tracking", [])
    poses = results.get("poses", [])

    # Calculate statistics
    frame_count = video_info.get("frame_count", 0)
    fps = video_info.get("fps", 30)
    duration = frame_count / fps if fps > 0 else 0

    detected_frames = sum(1 for t in tracking if t.get("position"))
    detection_rate = detected_frames / max(len(tracking), 1) * 100

    detected_poses = sum(1 for p in poses if p.get("detected"))
    pose_rate = detected_poses / max(len(poses), 1) * 100

    max_speed = max(speeds) if speeds else 0
    avg_speed = sum(speeds) / len(speeds) if speeds else 0

    # Build results message
    results_msg = f"""# {sport_emoji} Analysis Complete!

## Video Information
- **Duration:** {duration:.1f} seconds
- **Frames:** {frame_count}
- **FPS:** {fps:.0f}

## Tracking Performance
- **Detection Rate:** {detection_rate:.1f}%
- **Pose Detection:** {pose_rate:.1f}%

## Speed Analysis
"""

    if max_speed > 0:
        smash_detected = max_speed > 200 if sport == "badminton" else max_speed > 80
        if smash_detected:
            results_msg += f"### 🚀 SMASH DETECTED!\n"
        results_msg += f"- **Maximum Speed:** {max_speed:.1f} km/h\n"
        results_msg += f"- **Average Speed:** {avg_speed:.1f} km/h\n"
    else:
        results_msg += "- No speed data available (tracking needed)\n"

    await cl.Message(content=results_msg).send()

    # Generate report file
    report_gen = ReportGenerator(load_config(sport))

    # Save JSON report
    output_dir = Path("data/output")
    output_dir.mkdir(parents=True, exist_ok=True)

    json_path = output_dir / f"{video_id}_report.json"
    report_gen.generate_json_report(results, json_path)

    # Create file element for download
    report_file = cl.File(
        name=f"{video_id}_report.json",
        path=str(json_path),
        display="inline",
    )

    await cl.Message(
        content="📄 **Download your detailed report:**",
        elements=[report_file],
    ).send()

    # Generate social media caption
    caption = report_gen.generate_social_caption(results, platform="instagram")

    await cl.Message(
        content=f"### 📱 Ready-to-share Caption:\n\n```\n{caption}\n```"
    ).send()

    # Offer next actions
    actions = [
        cl.Action(
            name="analyze_another",
            value="new",
            label="🔄 Analyze Another Video",
        ),
        cl.Action(
            name="change_sport",
            value="change",
            label="🔀 Change Sport",
        ),
    ]

    await cl.Message(
        content="What would you like to do next?",
        actions=actions,
    ).send()


@cl.action_callback("analyze_another")
async def on_analyze_another(action: cl.Action):
    """Handle analyze another video action."""
    sport = cl.user_session.get("sport", "badminton")
    sport_name = sport.replace("_", " ").title()

    await cl.Message(
        content=f"Ready for another analysis! Share an Instagram reel link of {sport_name.lower()} gameplay."
    ).send()


@cl.action_callback("change_sport")
async def on_change_sport(action: cl.Action):
    """Handle change sport action."""
    actions = [
        cl.Action(
            name="select_badminton",
            value="badminton",
            label="🏸 Badminton",
        ),
        cl.Action(
            name="select_table_tennis",
            value="table_tennis",
            label="🏓 Table Tennis",
        ),
    ]

    await cl.Message(
        content="Select your sport:",
        actions=actions,
    ).send()


async def show_help():
    """Display help information."""
    help_msg = """# Help - Racket Sports Analytics

## Commands
- **Share an Instagram URL** - Analyze a video
- `badminton` - Switch to badminton mode
- `table tennis` - Switch to table tennis mode
- `help` - Show this help message

## Supported Analysis
1. **Shuttle/Ball Tracking** - Uses YOLO/TrackNet to track the object
2. **Pose Estimation** - MediaPipe for 33 body landmarks
3. **Speed Detection** - Kinematic analysis with Kalman filtering
4. **Heatmaps** - Player position frequency visualization
5. **Shot Classification** - Identifies shot types (smash, clear, drop, etc.)

## Tips
- Use high-quality videos for better results
- Stationary camera footage works best
- POV footage from Meta glasses is also supported
- Analysis typically takes 1-2 minutes

## Privacy
- Videos are processed locally
- No data is stored after analysis
- Only you receive the results

Need more help? Check our [GitHub repository](https://github.com/yourusername/Badminton_Quant)
"""

    await cl.Message(content=help_msg).send()


if __name__ == "__main__":
    # This is for local development
    # Run with: chainlit run app.py
    pass
