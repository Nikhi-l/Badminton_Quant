"""Final assembly: concat rally clips, lay the soundtrack under the court audio, thumbnail."""
import subprocess
from pathlib import Path

from .. import config
from . import media, music


XFADE = 0.45  # crossfade between rallies, seconds


def _join_with_transitions(clips: list[Path], raw: Path):
    """Crossfade video+audio between consecutive rally clips (single re-encode)."""
    durs = [media.probe(c).duration for c in clips]
    cmd = ["ffmpeg", "-y", "-v", "error"]
    for c in clips:
        cmd += ["-i", str(c)]
    vf, af = "", ""
    vprev, aprev = "0:v", "0:a"
    off = 0.0
    for k in range(1, len(clips)):
        off += durs[k - 1] - XFADE
        vf += f"[{vprev}][{k}:v]xfade=transition=fade:duration={XFADE}:offset={off:.3f}[v{k}];"
        af += f"[{aprev}][{k}:a]acrossfade=d={XFADE}[a{k}];"
        vprev, aprev = f"v{k}", f"a{k}"
    cmd += ["-filter_complex", vf + af.rstrip(";"),
            "-map", f"[{vprev}]", "-map", f"[{aprev}]",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", str(raw)]
    subprocess.run(cmd, check=True)


def stitch(clips: list[Path], workdir: Path, log=print) -> dict:
    workdir = Path(workdir)
    raw = workdir / "reel_raw.mp4"
    final = workdir / "reel.mp4"
    thumb = workdir / "thumb.jpg"

    if len(clips) == 1:
        lst = workdir / "concat.txt"
        lst.write_text(f"file '{clips[0].resolve()}'\n")
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0",
                        "-i", str(lst), "-c", "copy", str(raw)], check=True)
    else:
        log(f"crossfading {len(clips)} rally clips")
        _join_with_transitions(clips, raw)

    total = media.probe(raw).duration
    log(f"reel is {total:.1f}s — synthesizing {config.MUSIC_BPM} BPM soundtrack")
    wav = workdir / "music.wav"
    music.write_wav(wav, music.build_track(total))

    subprocess.run([
        "ffmpeg", "-y", "-v", "error", "-i", str(raw), "-i", str(wav),
        "-filter_complex",
        f"[0:a]volume={config.AMBIENT_GAIN}[amb];"
        f"[1:a]volume={config.MUSIC_GAIN}[mus];"
        f"[amb][mus]amix=inputs=2:duration=first:normalize=0[a]",
        "-map", "0:v", "-map", "[a]",
        "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart",
        str(final)], check=True)

    subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", "0.8", "-i", str(final),
                    "-frames:v", "1", "-vf", "scale=540:-2", "-q:v", "3", str(thumb)], check=True)
    return {"reel": final, "thumb": thumb, "duration": round(total, 2)}
