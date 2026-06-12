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
# $ per 1M tokens for cost estimates shown in the UI (override when pricing changes).
GEMINI_IN_RATE = float(os.environ.get("GEMINI_IN_RATE", "0.30"))
GEMINI_OUT_RATE = float(os.environ.get("GEMINI_OUT_RATE", "2.50"))

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
