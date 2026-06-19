"""ffmpeg/ffprobe helpers: probing, proxy creation, raw-frame piping."""
import json
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .. import config

FFMPEG = "ffmpeg"
FFPROBE = "ffprobe"


@dataclass
class VideoInfo:
    width: int          # display width (rotation applied)
    height: int         # display height (rotation applied)
    fps: float
    duration: float
    rotation: int


def probe(path: str | Path) -> VideoInfo:
    cmd = [FFPROBE, "-v", "error", "-select_streams", "v:0",
           "-show_entries", "stream=width,height,r_frame_rate,duration,side_data_list",
           "-show_entries", "format=duration", "-of", "json", str(path)]
    # ffprobe can transiently fail to spawn when the box is saturated (parallel
    # ffmpeg + model inference). Retry a few times before giving up so one busy
    # moment doesn't sink a whole render.
    last = None
    for attempt in range(4):
        res = subprocess.run(cmd, capture_output=True, text=True)
        if res.returncode == 0 and res.stdout.strip():
            out = res.stdout
            break
        last = res
        time.sleep(0.4 * (attempt + 1))
    else:
        raise RuntimeError(
            f"ffprobe failed for {path} after retries: "
            f"{(last.stderr or '').strip()[:300]}")
    d = json.loads(out)
    s = d["streams"][0]
    num, den = s["r_frame_rate"].split("/")
    fps = float(num) / float(den or 1)
    duration = float(s.get("duration") or d["format"]["duration"])
    rotation = 0
    for sd in s.get("side_data_list", []) or []:
        if "rotation" in sd:
            rotation = int(sd["rotation"])
    w, h = int(s["width"]), int(s["height"])
    if abs(rotation) % 180 == 90:
        w, h = h, w
    return VideoInfo(width=w, height=h, fps=fps, duration=duration, rotation=rotation)


def creation_time(path: str | Path) -> str | None:
    """Recording timestamp from container metadata (ISO string), or None."""
    out = subprocess.run(
        [FFPROBE, "-v", "error", "-show_entries",
         "format_tags=creation_time,com.apple.quicktime.creationdate",
         "-of", "json", str(path)],
        capture_output=True, text=True, check=True).stdout
    tags = (json.loads(out).get("format") or {}).get("tags") or {}
    return tags.get("creation_time") or tags.get("com.apple.quicktime.creationdate")


def normalize_concat(srcs: list[Path], dst: Path, log=print) -> None:
    """Multi-clip games: normalize every clip to the first clip's display geometry
    at 30 fps (clips from phones/POV glasses vary in size and timebase), then concat."""
    first = probe(srcs[0])
    W = first.width - first.width % 2
    H = first.height - first.height % 2
    parts = []
    for i, src in enumerate(srcs):
        part = dst.parent / f"norm_{i:02d}.mp4"
        log(f"normalizing clip {i + 1}/{len(srcs)} to {W}x{H}@30")
        subprocess.run(
            [FFMPEG, "-y", "-v", "error", "-i", str(src),
             "-vf", f"scale={W}:{H}:force_original_aspect_ratio=decrease,"
                    f"pad={W}:{H}:(ow-iw)/2:(oh-ih)/2,fps=30",
             "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
             "-c:a", "aac", "-b:a", "160k", "-ar", "44100", "-ac", "2",
             "-map", "0:v:0", "-map", "0:a:0?", str(part)],
            check=True)
        parts.append(part)
    lst = dst.parent / "concat_inputs.txt"
    lst.write_text("".join(f"file '{p.resolve()}'\n" for p in parts))
    subprocess.run([FFMPEG, "-y", "-v", "error", "-f", "concat", "-safe", "0",
                    "-i", str(lst), "-c", "copy", "-movflags", "+faststart", str(dst)],
                   check=True)
    for p in parts:
        p.unlink(missing_ok=True)


def make_proxy(src: str | Path, dst: str | Path, height: int = config.PROXY_HEIGHT,
               fps: int = config.PROXY_FPS) -> VideoInfo:
    """Downscaled H.264 proxy used for Gemini upload and motion analysis.
    ffmpeg applies rotation metadata, so proxy dims are display dims."""
    subprocess.run(
        [FFMPEG, "-y", "-v", "error", "-i", str(src),
         "-vf", f"scale=-2:{height},fps={fps}",
         "-c:v", "libx264", "-preset", "veryfast", "-crf", "28",
         "-c:a", "aac", "-b:a", "64k", "-movflags", "+faststart", str(dst)],
        check=True)
    return probe(dst)


def iter_frames(path: str | Path, t0: float, t1: float, *, fps: int, gray: bool = False,
                scale_h: int | None = None):
    """Yield (index, frame ndarray) decoded via an ffmpeg rawvideo pipe.
    Frames are RGB (H,W,3) or grayscale (H,W). Rotation metadata is applied by ffmpeg."""
    info = probe(path)
    w, h = info.width, info.height
    if scale_h:
        h2 = scale_h
        w2 = int(round(w * h2 / h / 2) * 2)
        w, h = w2, h2
    vf = f"fps={fps}" + (f",scale={w}:{h}" if scale_h else "")
    pix = "gray" if gray else "rgb24"
    chans = 1 if gray else 3
    cmd = [FFMPEG, "-v", "error", "-ss", f"{t0:.3f}", "-t", f"{max(0.0, t1 - t0):.3f}",
           "-i", str(path), "-vf", vf, "-f", "rawvideo", "-pix_fmt", pix, "-"]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    frame_bytes = w * h * chans
    i = 0
    try:
        while True:
            buf = proc.stdout.read(frame_bytes)
            if not buf or len(buf) < frame_bytes:
                break
            arr = np.frombuffer(buf, dtype=np.uint8)
            yield i, (arr.reshape(h, w) if gray else arr.reshape(h, w, 3))
            i += 1
    finally:
        proc.stdout.close()
        proc.wait()


class FrameWriter:
    """Pipe RGB frames into ffmpeg, muxing ambient audio from the source segment.
    Maps only the first audio stream — phone videos carry extra undecodable data tracks."""

    def __init__(self, dst: str | Path, w: int, h: int, fps: int,
                 audio_src: str | Path, a_t0: float, a_t1: float):
        self.log = Path(str(dst) + ".fflog")
        self._logf = open(self.log, "w")
        self.proc = subprocess.Popen(
            [FFMPEG, "-y", "-v", "error",
             "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{w}x{h}", "-r", str(fps), "-i", "-",
             "-ss", f"{a_t0:.3f}", "-t", f"{max(0.0, a_t1 - a_t0):.3f}", "-i", str(audio_src),
             "-map", "0:v", "-map", "1:a:0?",
             "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
             "-c:a", "aac", "-b:a", "160k", "-ar", "44100", "-ac", "2",
             "-shortest", "-movflags", "+faststart", str(dst)],
            stdin=subprocess.PIPE, stderr=self._logf)

    def _fail(self) -> str:
        try:
            self._logf.flush()
            return self.log.read_text()[-800:]
        except OSError:
            return "(no ffmpeg log)"

    def write(self, frame: np.ndarray):
        try:
            self.proc.stdin.write(frame.tobytes())
        except BrokenPipeError:
            raise RuntimeError(f"ffmpeg encoder died: {self._fail()}") from None

    def close(self):
        try:
            self.proc.stdin.close()
        except BrokenPipeError:
            pass
        rc = self.proc.wait()
        self._logf.close()
        if rc != 0:
            raise RuntimeError(f"ffmpeg exited {rc}: {self._fail()}")
        self.log.unlink(missing_ok=True)
