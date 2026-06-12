# Research: AI-coach stack for racket sports (Roboflow + pose + court geometry + VLM)

*June 2026 — five parallel research sweeps; sources inline.*

## TL;DR

- **Roboflow RF-DETR is the wrong tool for the shuttle itself, the right tool for everything around it.** Single-frame detectors top out near F1 0.70–0.86 on shuttlecocks even with 20k training images ([arXiv:2603.06691](https://arxiv.org/pdf/2603.06691)) because the shuttle is a motion-blurred streak — temporal models (TrackNetV3 97.5%) win decisively. But for **players, net, court, paddles/rackets**, RF-DETR Nano/Small fine-tunes from ~100–2,000 images to 76–96% mAP@50, is Apache 2.0 (self-host free forever via `pip install rfdetr`), and beats YOLO11 at every size class.
- **Court homography is the highest-leverage, cheapest upgrade.** Our cameras are static → fit ONE homography per video (~zero CPU cost) → real-world coordinates → shot speed (km/h), placement heatmaps, player coverage, serve depth, line calls. This is exactly what SwingVision ($180/yr, tennis/pickleball) and PB Vision ($8/hr API, pickleball) monetize.
- **VLM coaching works only with the "measure-then-verbalize" pattern.** Raw video→critique hallucinates (Gemini 3 invented 3 flaws on a textbook golf swing; MotionBench confirms VLMs are weak at fine-grained motion). Google's own basketball coach injects MediaPipe joint data + rubric docs and uses Gemini to timestamp stroke phases and verbalize measured metrics. Cost is trivial: ~$0.02/clip on Gemini 3.5 Flash.
- **GPU is unavoidable for shuttle-precision but cheap as a burst worker:** spot L4 $0.31/hr (~$0.05/match), Modal T4 $0.59/hr with $30/mo free credits (≈50 GPU-hours — likely our whole early bill).

## Key resources

| What | Resource | Notes |
|---|---|---|
| Shuttle tracking | [TrackNetV3](https://github.com/qaz812345/TrackNetV3) (MIT, weights public) | ~25fps GPU; the chosen upgrade path |
| Cross-sport ball | [WASB-SBDT](https://github.com/nttcom/WASB-SBDT) (MIT) | badminton/tennis/volleyball zoo |
| Detector (players/net/court/paddle) | [RF-DETR](https://github.com/roboflow/rf-detr) (Apache 2.0 Nano–Large) | Nano: 48.4 AP, 2.3ms T4; ~5fps CPU |
| Badminton all-in-one reference | [SoloShuttlePose](https://github.com/sunwuzhou03/SoloShuttlePose) (MIT) | court+net keypoints, pose, shuttle, rally clipping |
| Court keypoints blueprint | [TennisCourtDetector](https://github.com/yastrebksv/TennisCourtDetector) | heatmap CNN, 14 kpts, ~1.8px err |
| 3D shuttle + hit detection | [MonoTrack (CVPRW'22)](https://arxiv.org/abs/2204.01899) | ~90% hit detection via GRU |
| Stroke classification | [BST transformer](https://github.com/Va6lue/BST-Badminton-Stroke-type-Transformer) | RTMPose+TrackNetV3, 35 strokes, 77%/93% top-2 |
| Stroke dataset | [ShuttleSet (KDD'23)](https://github.com/wywyWang/CoachAI-Projects) (MIT) | 36k strokes, 18 types, court coords |
| Pose | MediaPipe Pose (Apache 2.0) or [RTMPose](https://github.com/open-mmlab/mmpose) (Apache 2.0) | **avoid YOLO-pose: AGPL** |
| Pose-augmented VLM patterns | [Google AI basketball coach](https://cloud.google.com/transform/how-we-built-an-ai-basketball-coach-with-gemini-on-vertex-ai), [SportsGPT](https://arxiv.org/abs/2512.14121), [Talking Tennis](https://arxiv.org/pdf/2510.03921), [BioCoach](https://arxiv.org/html/2603.26938) | measure → timestamp → verbalize |
| Hit/contact detection | trajectory inflection + wrist velocity + **audio spike** ([impact ≈5ms](https://pmc.ncbi.nlm.nih.gov/articles/PMC11843912/)) | fusion lifts P from 59→90% |
| Commercial benchmarks | SwingVision $179/yr · PB Vision $8/hr API · [goSmash](https://gosmash.app) (badminton, Claude-powered) | feature/pricing references |

## Biomechanics: what's honestly measurable from one phone camera

**Safe to ship:** jump height (validated ICC 0.84–0.99 vs force plates), elbow angle at contact (side view), knee bend, kinetic-chain timing (hip→shoulder→elbow→wrist velocity peaks), contact-point height, footwork/court coverage.
**Unreliable monocular — don't ship as numbers:** shoulder internal rotation (the single most predictive smash variable, per elite mocap studies), true 3D racket-head speed. Gate metrics by detected camera angle; label estimates as estimates.

## Cost model (per 20-min match, ~8 min of selected rallies)

| Component | Where | Cost | Latency |
|---|---|---|---|
| Court homography (once/video) | CPU (existing VM) | ~$0 | seconds |
| Audio hit detection | CPU | ~$0 | seconds |
| Pose (selected rallies) | browser (tasks-vision, 38–92fps) or CPU lite | $0 | client-side |
| Shuttle (TrackNetV3) + RF-DETR players | burst GPU (Modal T4 / spot L4 / Cloud Run GPU) | $0.05–0.11 | 5–12 min |
| VLM coaching (Gemini Flash) | API | $0.04–0.20 | tens of sec |
| **Total added** | | **+$0.06–0.25/match** | parallel with CPU work |

## Recommended build order

1. **Phase 1 — CPU-only, immediate:** court+net keypoint model (start from SoloShuttlePose / Universe pickleball keypoints; fine-tune RF-DETR Nano or a MobileNetV3 keypoint head) → homography → rally stats (shot count via audio-spike hit detection, rally speed, placement heatmap overlays on reels) + Gemini coaching feedback fed with measured stats (never raw video alone). Browser-side MediaPipe pose for a "form check" Studio panel.
2. **Phase 2 — burst GPU worker (Modal first, Cloud Run GPU later):** TrackNetV3 shuttle precision into the existing `FocusPath` interface (shuttle-locked virtual camera), RF-DETR players/net, smash-speed estimates via court scale.
3. **Phase 3 — full coach:** BST stroke classification (35 types) on ShuttleSet, per-stroke-type technique rubrics, side-by-side reference comparison in Studio (leapfrogs OnForm's manual workflow), trend dashboards.
