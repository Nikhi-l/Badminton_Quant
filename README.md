# Racket Sports Analytics (Badminton Quant)

AI-powered sports analytics for racket sports, starting with badminton and extending to table tennis and beyond.

## Vision

Build an accessible, open-source sports analytics platform that transforms video footage into actionable insights for athletes at all levels. Process videos from social media (Instagram reels), POV cameras (Meta glasses), and stationary setups.

## Current Capabilities (In Development)

| Feature | Badminton | Table Tennis |
|---------|-----------|--------------|
| Shuttle/Ball Tracking | 🔄 | 🔄 |
| Pose Estimation (2D/3D) | 🔄 | 🔄 |
| Smash/Shot Speed Detection | 🔄 | 🔄 |
| Movement Heatmaps | 🔄 | 🔄 |
| Weakness Analysis | 🔄 | 🔄 |
| Shot Classification | 🔄 | 🔄 |

**Legend:** ✅ Ready | 🔄 In Progress | ⏳ Planned

## Quick Start

### Option 1: Chainlit Web Interface (Recommended)

```bash
# Clone the repository
git clone https://github.com/yourusername/Badminton_Quant.git
cd Badminton_Quant

# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -e .

# Launch the Chainlit chatbot interface
chainlit run app.py
```

Then open `http://localhost:8000` in your browser to start analyzing videos!

### Option 2: Command Line

```bash
# Run analysis on an Instagram reel
python -m racket_sports.cli --source instagram --url "YOUR_INSTAGRAM_REEL_URL"

# Run on local video
python -m racket_sports.cli --source local --path "path/to/video.mp4"

# Quick test to verify installation
python examples/quick_test.py
```

## Chainlit Chatbot Interface

The project includes a conversational AI interface built with [Chainlit](https://chainlit.io):

**Features:**
- Interactive sport selection (badminton/table tennis)
- Instagram reel URL processing
- Real-time analysis progress with steps
- Downloadable JSON reports
- Ready-to-share social media captions
- Custom UI with light/dark themes

**Screenshots:**

```
┌────────────────────────────────────────────────────┐
│  🏸 Racket Sports Analytics                        │
├────────────────────────────────────────────────────┤
│  Welcome! I can analyze your badminton videos.     │
│                                                    │
│  [🏸 Badminton]  [🏓 Table Tennis]                │
├────────────────────────────────────────────────────┤
│  > Paste Instagram URL here...                     │
└────────────────────────────────────────────────────┘
```

## Project Structure

```
Badminton_Quant/
├── app.py                      # Chainlit chatbot interface
├── chainlit.md                 # Welcome message
├── .chainlit/config.toml       # Chainlit configuration
├── racket_sports/              # Core Python package
│   ├── video_acquisition/      # Video download & preprocessing
│   │   ├── instagram.py        # Instagram reel downloader
│   │   └── preprocessor.py     # Frame extraction, stabilization
│   ├── tracking/               # Object tracking modules
│   │   ├── tracknet.py         # TrackNetV3 shuttle/ball tracking
│   │   ├── yolo_tracker.py     # YOLO-based tracking (lightweight)
│   │   └── sam2_tracker.py     # SAM2 segmentation tracking
│   ├── pose/                   # Pose estimation
│   │   ├── mediapipe_pose.py   # MediaPipe 2D/3D pose
│   │   └── pose_analyzer.py    # Pose-based analytics
│   ├── analytics/              # Core analytics
│   │   ├── speed_detector.py   # Smash/shot speed calculation
│   │   ├── heatmap.py          # Movement heatmaps
│   │   ├── weakness.py         # Weakness area detection
│   │   └── shot_classifier.py  # Shot type classification
│   └── visualization/          # Output generation
│       ├── overlays.py         # Video overlay generation
│       └── reports.py          # Analytics reports
├── configs/                    # Sport-specific configurations
│   ├── badminton.yaml
│   └── table_tennis.yaml
├── models/                     # Pre-trained weights (gitignored)
├── data/                       # Input/output data (gitignored)
│   ├── input/
│   └── output/
├── examples/                   # Example scripts
└── tests/                      # Unit tests
```

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                        VIDEO INPUT                                   │
│  (Instagram Reel / POV Camera / Stationary Camera)                  │
└─────────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────────┐
│                    VIDEO PREPROCESSING                               │
│  • Frame extraction • Stabilization • Court detection               │
└─────────────────────────────────────────────────────────────────────┘
                                │
                ┌───────────────┼───────────────┐
                ▼               ▼               ▼
        ┌──────────────┐ ┌──────────────┐ ┌──────────────┐
        │   TRACKING   │ │    POSE      │ │   RACKET     │
        │  TrackNet/   │ │  MediaPipe   │ │  Detection   │
        │  YOLO/SAM2   │ │  2D/3D       │ │  YOLO        │
        └──────────────┘ └──────────────┘ └──────────────┘
                │               │               │
                └───────────────┼───────────────┘
                                ▼
┌─────────────────────────────────────────────────────────────────────┐
│                      ANALYTICS ENGINE                                │
│  • Speed Detection • Heatmaps • Shot Classification • Weakness      │
└─────────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────────┐
│                         OUTPUT                                       │
│  • Annotated Video • Analytics Report • Social Media Share          │
└─────────────────────────────────────────────────────────────────────┘
```

## Key Technologies & Research

### Shuttle/Ball Tracking
- **[TrackNetV3](https://github.com/qaz812345/TrackNetV3)**: State-of-the-art shuttlecock tracking using deep learning with trajectory prediction and rectification
- **[YOLO](https://docs.ultralytics.com/)**: Lightweight object detection for real-time tracking
- **[SAM2](https://github.com/facebookresearch/sam2)**: Meta's Segment Anything Model 2 for precise video object segmentation

### Pose Estimation
- **[MediaPipe Pose](https://github.com/google-ai-edge/mediapipe/blob/master/docs/solutions/pose.md)**: Real-time 2D/3D pose estimation with 33 body landmarks
- **[SoloShuttlePose](https://github.com/sunwuzhou03/SoloShuttlePose)**: Lightweight badminton-specific pose detection

### Speed Detection
- Kinematic speed estimation using trajectory analysis
- Kalman filtering for robust tracking
- Camera calibration for real-world distance mapping

### Hit Detection
- **[SwingNet](https://github.com/wish44165/A-New-Perspective-for-Shuttlecock-Hitting-Event-Detection)**: Deep learning for shuttlecock hitting event detection
- **[Automated Hit-frame Detection](https://github.com/arthur900530/Automated-Hit-frame-Detection-for-Badminton-Match-Analysis)**: Transformer-based hit detection

### Table Tennis Resources
- **[TT3D](https://cogsys-tuebingen.github.io/tt3d/)**: 3D table tennis reconstruction
- **[tt_tracker](https://github.com/ckjellson/tt_tracker)**: 3D ball tracking using stereo cameras
- **[Table Tennis Posture Analysis](https://github.com/wutonytt/Camera-Based-Table-Tennis-Posture-Analysis)**: Pose-based analysis

## Social Media Integration

The platform is designed around social media sharing:

1. **Input**: Users share Instagram reel links of their gameplay
2. **Processing**: Our system analyzes the video
3. **Output**: Annotated video with analytics shared on our Instagram page

This approach:
- Saves data/storage costs (no direct video upload needed)
- Provides free marketing through shares
- Creates community engagement

## Configuration

Sport-specific parameters are defined in YAML configs:

```yaml
# configs/badminton.yaml
sport: badminton
court:
  length_m: 13.4
  width_singles_m: 5.18
  width_doubles_m: 6.1
  net_height_m: 1.55

tracking:
  model: tracknetv3  # or yolo, sam2
  confidence_threshold: 0.5

pose:
  model: mediapipe
  landmarks_3d: true

analytics:
  smash_speed_threshold_kmh: 200
  movement_sampling_hz: 30
```

## Development Roadmap

### Phase 1: Core Infrastructure ✅
- [x] Project structure
- [x] Configuration system
- [x] Video acquisition pipeline

### Phase 2: Tracking & Detection 🔄
- [ ] TrackNetV3 integration for shuttle tracking
- [ ] YOLO lightweight tracker
- [ ] MediaPipe pose estimation
- [ ] Court detection

### Phase 3: Analytics Engine ⏳
- [ ] Smash speed detection
- [ ] Movement heatmaps
- [ ] Shot classification
- [ ] Weakness analysis

### Phase 4: Production ⏳
- [x] Chainlit chatbot interface
- [ ] Optimized inference (ONNX, TensorRT)
- [ ] API server
- [ ] Social media bot integration
- [ ] Web dashboard

## Contributing

Contributions welcome! See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

## License

MIT License - see [LICENSE](LICENSE) for details.

## Acknowledgments

- [TrackNet](https://nol.cs.nctu.edu.tw/ndo3je6av9/) research team at NYCU
- [MediaPipe](https://mediapipe.dev/) team at Google
- [SAM2](https://ai.meta.com/sam2/) team at Meta AI
- [Chainlit](https://chainlit.io) for the chatbot framework
- Open source badminton analytics community

---

**Note**: This project is for research and personal use. Always respect copyright and terms of service when downloading content from social media platforms.
