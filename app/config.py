"""Central config. Values come from environment, with .env as a convenience loader."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
UPLOADS = DATA / "uploads"
OUTPUTS = DATA / "outputs"
DB_PATH = DATA / "db.sqlite"


def _load_dotenv() -> None:
    env = ROOT / ".env"
    if not env.exists():
        return
    for line in env.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())


_load_dotenv()

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
SEGMENT_MODEL = os.environ.get("SEGMENT_MODEL", "gemini-3.5-flash")
PRO_MODEL = os.environ.get("PRO_MODEL", "gemini-3.1-pro-preview")
COACH_MODEL = os.environ.get("COACH_MODEL", SEGMENT_MODEL)
COACH_ENABLED = os.environ.get("COACH_ENABLED", "1").lower() not in {"0", "false", "no", "off"}
COACH_FRAME_COUNT = int(os.environ.get("COACH_FRAME_COUNT", "4"))
COACH_FRAME_HEIGHT = int(os.environ.get("COACH_FRAME_HEIGHT", "360"))
# $ per 1M tokens for cost estimates shown in the UI (override when pricing changes).
GEMINI_IN_RATE = float(os.environ.get("GEMINI_IN_RATE", "0.30"))
GEMINI_OUT_RATE = float(os.environ.get("GEMINI_OUT_RATE", "2.50"))

# Optional burst-GPU vision worker. When these are unset, the pipeline keeps the
# existing CPU tracking path and records why GPU analysis was skipped.
PUBLIC_BASE_URL = os.environ.get("PUBLIC_BASE_URL", "").rstrip("/")
RUNPOD_API_KEY = os.environ.get("RUNPOD_API_KEY", "")
RUNPOD_ENDPOINT_ID = os.environ.get("RUNPOD_ENDPOINT_ID", "")
RUNPOD_BASE_URL = os.environ.get("RUNPOD_BASE_URL", "https://api.runpod.ai")
RUNPOD_TIMEOUT_SEC = float(os.environ.get("RUNPOD_TIMEOUT_SEC", "1200"))
RUNPOD_POLL_SEC = float(os.environ.get("RUNPOD_POLL_SEC", "5"))
GPU_ARTIFACT_TOKEN = os.environ.get("GPU_ARTIFACT_TOKEN", "")
GPU_ARTIFACT_TTL_SEC = int(os.environ.get("GPU_ARTIFACT_TTL_SEC", "7200"))
SHUTTLE_MASK_MIN_CONF = float(os.environ.get("SHUTTLE_MASK_MIN_CONF", "0.55"))
SHUTTLE_MASK_MIN_QUALITY = float(os.environ.get("SHUTTLE_MASK_MIN_QUALITY", "0.65"))

# Per-job vision worker selection. Each upload picks which analyses run; only
# selected workers execute. Heavy GPU work (TrackNetV3) goes to Runpod serverless
# and is opt-in to conserve credits; CPU-viable work (YOLO pose) runs on the VM.
#   shuttle: "off" (CPU motion camera) | "tracknetv3" (Runpod GPU shuttle lock)
#   pose:    "off" | "yolo11" (player + pose; CPU on VM, or bundled into a GPU job)
#   coach:   bool (grounded Gemini coach notes)
SHUTTLE_ENGINES = {"off", "tracknetv3"}
POSE_ENGINES = {"off", "yolo11"}
VISION_DEFAULT_SHUTTLE = os.environ.get("VISION_DEFAULT_SHUTTLE", "off")
VISION_DEFAULT_POSE = os.environ.get("VISION_DEFAULT_POSE", "off")
# When a GPU task is requested but Runpod is unavailable, may we run TrackNetV3 on
# the VM CPU? Off by default: it is ~1 hour/reel and would block the queue.
VISION_ALLOW_CPU_TRACKNET = os.environ.get("VISION_ALLOW_CPU_TRACKNET", "0").lower() \
    not in {"0", "false", "no", "off"}


def normalize_options(opts: dict | None) -> dict:
    """Validate/clamp per-job vision options to the supported worker set."""
    opts = opts if isinstance(opts, dict) else {}
    shuttle = str(opts.get("shuttle", VISION_DEFAULT_SHUTTLE)).lower()
    pose = str(opts.get("pose", VISION_DEFAULT_POSE)).lower()
    return {
        "shuttle": shuttle if shuttle in SHUTTLE_ENGINES else "off",
        "pose": pose if pose in POSE_ENGINES else "off",
        "coach": bool(opts.get("coach", COACH_ENABLED)),
    }

# Analysis runs on a downscaled proxy; final render samples the original file.
PROXY_HEIGHT = int(os.environ.get("PROXY_HEIGHT", "480"))
PROXY_FPS = 30

# Output reel: vertical story format.
OUT_W, OUT_H, OUT_FPS = 1080, 1920, 30
MAX_REEL_SEC = float(os.environ.get("MAX_REEL_SEC", "59"))
TOP_RALLIES = int(os.environ.get("TOP_RALLIES", "5"))
MIN_RALLY_SEC = 3.0
PAD_BEFORE, PAD_AFTER = 1.0, 1.6

MUSIC_BPM = 120
MUSIC_GAIN = 0.5      # music bed level under ambient court audio
AMBIENT_GAIN = 1.0

for d in (UPLOADS, OUTPUTS):
    d.mkdir(parents=True, exist_ok=True)
