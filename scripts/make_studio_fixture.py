"""Build a fully synthetic Studio fixture job — no Gemini, no GPU, no upload.

A bright "shuttle" dot and two "players" (near = large pink, far = small blue)
move on a court-ish background along known parametric paths. The SAME ground
truth drives (a) the rendered pixels and (b) the vision tracks, and the reel is
produced by the REAL render + stitch code path, so the exported camera_path is
exactly what the renderer used.

Open the Studio on job `fixture01` and the overlay markers must sit ON the drawn
shapes in every view: Portrait·Reel (crop projection), Portrait·Source, and
Landscape. If a marker drifts, the mapping is wrong — not the data.

Usage:
    .venv/bin/python scripts/make_studio_fixture.py
"""
import math
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import config, db  # noqa: E402
from app.pipeline import court, media, render, stitch, track  # noqa: E402

JOB_ID = "fixture01"
W, H, FPS, DUR = 1280, 720, 30, 14.0
COURT = (24, 84, 52)          # dark green
LINE = (210, 214, 220)
SHUTTLE = (255, 255, 255)
NEAR = (255, 122, 198)        # pink — matches the Studio p1 palette on purpose? no: near player
FAR = (70, 160, 255)

RALLIES = [
    {"start": 2.0, "end": 7.0, "note": "synthetic rally one", "intensity": "high"},
    {"start": 9.0, "end": 12.5, "note": "synthetic rally two", "intensity": "medium"},
]


# ---------------------------------------------------------------- ground truth
def shuttle_at(t: float) -> tuple[float, float]:
    return 0.5 + 0.38 * math.sin(t * 1.1), 0.36 + 0.22 * math.sin(t * 2.3 + 1.0)


def near_at(t: float) -> tuple[float, float, float, float]:  # cx, cy, w, h
    return 0.5 + 0.24 * math.sin(t * 0.7), 0.74, 0.12, 0.30


def far_at(t: float) -> tuple[float, float, float, float]:
    return 0.5 + 0.20 * math.cos(t * 0.9), 0.30, 0.06, 0.14


def pose_keypoints(cx: float, cy: float, w: float, h: float, t: float, phase: float):
    """A plausible COCO-17 stick figure inside the box, arms swinging."""
    sw = math.sin(t * 3.0 + phase) * 0.35   # arm swing -0.35..0.35
    X = lambda dx: cx + dx * w
    Y = lambda dy: cy + dy * h
    pts = [
        (X(0), Y(-0.42)),                       # 0 nose
        (X(-0.08), Y(-0.46)), (X(0.08), Y(-0.46)),   # eyes
        (X(-0.16), Y(-0.44)), (X(0.16), Y(-0.44)),   # ears
        (X(-0.35), Y(-0.25)), (X(0.35), Y(-0.25)),   # shoulders
        (X(-0.45), Y(-0.05 + sw * 0.1)), (X(0.45), Y(-0.05 - sw * 0.1)),  # elbows
        (X(-0.5 - sw * 0.2), Y(0.12)), (X(0.5 + sw * 0.2), Y(0.12)),      # wrists
        (X(-0.2), Y(0.05)), (X(0.2), Y(0.05)),       # hips
        (X(-0.22), Y(0.25)), (X(0.22), Y(0.25)),     # knees
        (X(-0.24 + sw * 0.1), Y(0.45)), (X(0.24 - sw * 0.1), Y(0.45)),    # ankles
    ]
    return [{"x": round(px, 5), "y": round(py, 5), "confidence": 0.9} for px, py in pts]


# ---------------------------------------------------------------- draw helpers
def rect(img, cx, cy, w, h, color):
    x0, y0 = int((cx - w / 2) * W), int((cy - h / 2) * H)
    x1, y1 = int((cx + w / 2) * W), int((cy + h / 2) * H)
    img[max(0, y0):max(0, y1), max(0, x0):max(0, x1)] = color


_YY, _XX = np.mgrid[0:H, 0:W]


def disc(img, cx, cy, r_px, color):
    m = (_XX - cx * W) ** 2 + (_YY - cy * H) ** 2 <= r_px ** 2
    img[m] = color


def draw_frame(t: float) -> np.ndarray:
    img = np.zeros((H, W, 3), dtype=np.uint8)
    img[:] = COURT
    # court outline + net line, so the crop's motion is visible
    img[int(0.16 * H):int(0.16 * H) + 3, int(0.2 * W):int(0.8 * W)] = LINE
    img[int(0.92 * H):int(0.92 * H) + 3, int(0.06 * W):int(0.94 * W)] = LINE
    img[int(0.16 * H):int(0.92 * H), int(0.2 * W):int(0.2 * W) + 3] = LINE
    img[int(0.16 * H):int(0.92 * H), int(0.8 * W) - 3:int(0.8 * W)] = LINE
    img[int(0.5 * H):int(0.5 * H) + 4, int(0.12 * W):int(0.88 * W)] = (160, 165, 175)
    nx, ny, nw, nh = near_at(t)
    fx, fy, fw, fh = far_at(t)
    rect(img, nx, ny, nw, nh, NEAR)
    disc(img, nx, ny - nh * 0.42, 10, NEAR)
    rect(img, fx, fy, fw, fh, FAR)
    disc(img, fx, fy - fh * 0.42, 6, FAR)
    sx, sy = shuttle_at(t)
    disc(img, sx, sy, 6, SHUTTLE)
    return img


def write_source(dst: Path):
    proc = subprocess.Popen(
        ["ffmpeg", "-y", "-v", "error",
         "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-",
         "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo",
         "-shortest", "-map", "0:v", "-map", "1:a",
         "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
         "-c:a", "aac", "-b:a", "96k", "-movflags", "+faststart", str(dst)],
        stdin=subprocess.PIPE)
    for i in range(int(DUR * FPS)):
        proc.stdin.write(draw_frame(i / FPS).tobytes())
    proc.stdin.close()
    if proc.wait() != 0:
        raise RuntimeError("source encode failed")


# ---------------------------------------------------------------- vision synth
def vision_rally(idx: int, r: dict) -> dict:
    t0 = max(0.0, r["start"] - config.PAD_BEFORE)
    t1 = min(DUR, r["end"] + config.PAD_AFTER)
    shuttle, players, poses = [], [], []
    t = t0
    while t <= t1 + 1e-6:
        sx, sy = shuttle_at(t)
        shuttle.append({"t": round(t, 3), "x": round(sx, 5), "y": round(sy, 5), "confidence": 0.86})
        boxes = []
        people = []
        for who, (cx, cy, w, h), phase in (("near", near_at(t), 0.0), ("far", far_at(t), 2.1)):
            boxes.append({"x1": round(cx - w / 2, 5), "y1": round(cy - h / 2, 5),
                          "x2": round(cx + w / 2, 5), "y2": round(cy + h / 2, 5),
                          "confidence": 0.85 if who == "near" else 0.62})
            people.append({"confidence": 0.85 if who == "near" else 0.62,
                           "bbox": dict(boxes[-1]),
                           "keypoints": pose_keypoints(cx, cy, w, h, t, phase)})
        players.append({"t": round(t, 3), "boxes": boxes})
        poses.append({"t": round(t, 3), "people": people, "count": 2, "confidence": 0.74})
        t += 0.1
    return {
        "rally_index": idx, "start": r["start"], "end": r["end"],
        "dur": round(r["end"] - r["start"], 3),
        "status": "ok", "camera_mode": "gpu_pose_shuttle",
        "shuttle_quality": 0.84, "player_quality": 0.74, "pose_quality": 0.74,
        "racquet_quality": 0.0, "racquet_candidate_quality": 0.0,
        "pose_samples": len(poses), "racquet_samples": 0, "racquet_candidate_samples": 0,
        "mask_enabled": False, "shuttle_engine": "tracknetv3",
        "tracknet": {"enabled": True, "status": "ok", "points": len(shuttle), "quality": 0.84},
        "shuttle": shuttle, "players": players, "poses": poses,
    }


def focus_path(t0: float, t1: float) -> track.FocusPath:
    """Shuttle-follow camera: exactly what the tracker would aim for."""
    n = int((t1 - t0) * FPS) + 2
    ts = [t0 + i / FPS for i in range(n)]
    xs = np.array([shuttle_at(t)[0] for t in ts], dtype=np.float32)
    ys = np.array([min(0.9, shuttle_at(t)[1] + 0.12) for t in ts], dtype=np.float32)
    zs = np.full(n, 1.28, dtype=np.float32)
    return track.FocusPath(t0=t0, fps=FPS, xs=xs, ys=ys, zs=zs)


def main():
    workdir = config.OUTPUTS / JOB_ID
    if workdir.exists():
        shutil.rmtree(workdir)
    (workdir / "clips").mkdir(parents=True)
    src = workdir / "source.mp4"
    print("drawing synthetic source video…")
    write_source(src)
    print("building proxy…")
    media.make_proxy(src, workdir / "proxy.mp4")
    info = media.probe(src)

    rendered, clips = [], []
    for i, r in enumerate(RALLIES, 1):
        t0 = max(0.0, r["start"] - config.PAD_BEFORE)
        t1 = min(info.duration, r["end"] + config.PAD_AFTER)
        out = workdir / "clips" / f"clip_{i:02d}.mp4"
        print(f"rendering rally {i} ({t0:.1f}–{t1:.1f}s) through the real pipeline…")
        vr = vision_rally(i, r)
        dur, cam_path = render.render_rally(
            src, info, t0, t1, focus_path(t0, t1), out,
            f"RALLY {i}", f"{r['end'] - r['start']:.0f}s · {r['note']}")
        clips.append(out)
        rendered.append({
            **r, "dur": round(r["end"] - r["start"], 2), "clip": out.name,
            "clip_dur": round(dur, 2), "src_start": r["start"],
            "render_window": [round(t0, 3), round(t1, 3)], "camera_path": cam_path,
            "vision": {k: vr.get(k) for k in (
                "status", "camera_mode", "shuttle_quality", "player_quality",
                "pose_quality", "racquet_quality", "pose_samples", "racquet_samples",
                "racquet_candidate_quality", "racquet_candidate_samples",
                "mask_enabled", "shuttle_engine", "tracknet", "shuttle", "players", "poses")},
        })

    print("stitching…")
    stitched = stitch.stitch(clips, workdir)
    result = {
        "reel": str(stitched["reel"]), "thumb": str(stitched["thumb"]),
        "sport": "badminton",
        "all_rallies": [{**r, "dur": round(r["end"] - r["start"], 2), "used": True}
                        for r in RALLIES],
        "duration": stitched["duration"],
        "n_rallies_found": len(RALLIES), "n_rallies_used": len(rendered),
        "rallies": rendered,
        "validation": {"clips": [], "reel": {"ok": True}},
        "stitch": {"xfade": stitch.XFADE},
        "court": court.detect_from_video(workdir / "proxy.mp4"),
        "source": {"w": info.width, "h": info.height, "fps": round(info.fps, 2),
                   "duration": round(info.duration, 2)},
        "n_clips": 1, "clip_order": None, "pov_camera": False,
        "options": {"shuttle": "tracknetv3", "pose": "yolo11", "coach": False},
        "pipeline": "gpu",
        "vision": {"enabled": True, "status": "ok", "engine": "fixture",
                   "backend": "fixture", "contract": "baddy.vision.v1",
                   "message": "synthetic ground-truth fixture",
                   "models": {"pose": {"enabled": True, "model": "synthetic"},
                              "tracknet": {"enabled": True},
                              "racquet": {"enabled": False}},
                   "summary": {"camera_mode": "gpu_pose_shuttle",
                               "shuttle_engine": "tracknetv3", "shuttle_mask": False,
                               "shuttle_quality": 0.84, "pose_quality": 0.74,
                               "racquet_quality": 0.0, "racquet_candidate_quality": 0.0,
                               "player_quality": 0.74}},
        "coach": {"status": "disabled", "message": "fixture"},
        "gemini_usage": None, "elapsed_sec": 0.0,
    }
    (workdir / "result.json").write_text(__import__("json").dumps(result, indent=2))

    db.init()
    if db.get_job(JOB_ID):
        with db._conn() as c:
            c.execute("DELETE FROM jobs WHERE id=?", (JOB_ID,))
    db.create_job(JOB_ID, "fixture — synthetic overlay ground truth",
                  options=result["options"])
    db.set_done(JOB_ID, result)
    print(f"done → job {JOB_ID} · open the Studio and check the markers sit on the shapes")


if __name__ == "__main__":
    main()
