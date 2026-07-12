"""TASK-042: measured audio impacts veto implausible Gemini rally segmentation.

Owner footage: Gemini tiled a 270s video as 18 back-to-back "rallies" (91%
coverage — badminton always has dead time), two of which contained a single
impact in 10s (the "fake rally detections"). Refinement is shrink-only and
fail-open: it must never touch a healthy segmentation or act on thin audio.
"""
from app import config
from app.pipeline import rally


def _peaks(ts):
    return [{"t": float(t)} for t in ts]


def _win(s, e, intensity=3):
    return {"start": float(s), "end": float(e), "dur": float(e - s),
            "intensity": intensity, "note": "x"}


def test_wall_to_wall_windows_shrink_split_and_drop():
    # 3 windows tiling 0..60 (100% coverage): one real rally cluster, one
    # merged double-rally with a 8s silent middle, one impact-free fake.
    windows = [_win(0, 20), _win(20, 44), _win(44, 60)]
    peaks = _peaks([3, 4.5, 6, 7.5, 9,            # cluster inside window 1
                    22, 23.5, 25,                 # sub-rally A of window 2
                    33.5, 35, 37, 38.5])          # sub-rally B (8.5s gap)
    out = rally.refine_with_audio(windows, peaks, 60.0, log=lambda m: None)
    assert len(out) == 3                          # w1, w2a, w2b — fake dropped
    s = [(round(r["start"], 1), round(r["end"], 1)) for r in out]
    assert s[0] == (1.0, 11.0)                    # cluster ± pads, inside window
    assert s[1] == (20.0, 27.0)                   # clamped to window start
    assert s[2] == (31.5, 40.5)
    assert all(r["audio_hits"] >= 2 for r in out)
    assert all(r["dur"] >= config.MIN_RALLY_SEC for r in out)


def test_healthy_segmentation_untouched():
    windows = [_win(10, 20), _win(50, 62), _win(100, 115)]   # 21% coverage
    peaks = _peaks(range(0, 120, 4))
    out = rally.refine_with_audio(windows, peaks, 180.0, log=lambda m: None)
    assert out is windows


def test_thin_audio_fails_open():
    windows = [_win(0, 50), _win(50, 100)]        # 100% coverage, but...
    out = rally.refine_with_audio(windows, _peaks([10, 60]), 100.0,
                                  log=lambda m: None)
    assert out is windows                          # 2 peaks can't judge anything


def test_audio_contradicting_everything_fails_open():
    # all peaks outside every window: the audio stream is suspect, not the video
    windows = [_win(0, 40), _win(40, 80)]
    peaks = _peaks([90 + i for i in range(12)])
    out = rally.refine_with_audio(windows, peaks, 100.0, log=lambda m: None)
    assert out is windows


def test_audio_evidence_prompt_block():
    txt = rally._audio_evidence(_peaks([1.2, 5.0, 9.9] * 4))
    assert "transients" in txt and "dead time" in txt
    assert rally._audio_evidence(_peaks([1, 2])) == ""      # too thin → no anchor
    assert rally._audio_evidence(None) == ""
