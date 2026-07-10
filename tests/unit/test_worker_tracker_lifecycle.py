"""TASK-034 P0: worker tracker lifecycle — persist semantics + per-rally reset.

The audit bug: ultralytics registers its tracking callbacks on the first
``model.track()`` call and permanently captures that call's ``persist`` value;
the old handler passed ``persist=not reset_tracker``, so the first call ever
(a rally start) baked in ``persist=False`` and the tracker was rebuilt on
every subsequent predict — fresh ids each sampled frame, while id coverage
still read 100%. Two layers are pinned here:

- the DEPENDENCY behavior that makes the old pattern fatal, against the pinned
  ultralytics version: ``on_predict_start(persist=False)`` rebuilds trackers,
  ``persist=True`` reuses them;
- the HANDLER behavior: ``.track()`` is always called with ``persist=True``,
  a rally boundary explicitly resets tracker state, and a mid-rally frame
  does not.
"""
import sys
import types
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]

sys.modules.setdefault("runpod", types.SimpleNamespace(serverless=types.SimpleNamespace(start=lambda *_: None)))
sys.modules.setdefault("requests", types.SimpleNamespace())
try:
    import cv2  # noqa: F401
except Exception:  # pragma: no cover - ultralytics brings cv2 in this venv
    sys.modules.setdefault("cv2", types.SimpleNamespace())
sys.path.insert(0, str(ROOT / "runpod_worker"))
import handler  # noqa: E402


# --------------------------------------------------------------- dependency

def _stub_predictor():
    return types.SimpleNamespace(
        args=types.SimpleNamespace(task="pose", tracker="bytetrack.yaml"),
        dataset=types.SimpleNamespace(bs=1, mode="image"),
    )


def test_ultralytics_on_predict_start_rebuilds_unless_persist():
    from ultralytics.trackers.track import on_predict_start

    pred = _stub_predictor()
    on_predict_start(pred, persist=False)
    first = pred.trackers[0]
    # persist=False (what the old first-frame call captured into the callback
    # forever): the tracker is REBUILT on the next predict → id churn.
    on_predict_start(pred, persist=False)
    assert pred.trackers[0] is not first

    on_predict_start(pred, persist=True)
    kept = pred.trackers[0]
    on_predict_start(pred, persist=True)
    assert pred.trackers[0] is kept


def test_ultralytics_tracker_reset_restarts_id_space():
    from ultralytics.trackers.byte_tracker import BYTETracker
    from ultralytics.trackers.basetrack import BaseTrack
    from ultralytics.utils import YAML, IterableSimpleNamespace
    from ultralytics.utils.checks import check_yaml

    cfg = IterableSimpleNamespace(**YAML.load(check_yaml("bytetrack.yaml")))
    tracker = BYTETracker(args=cfg)
    BaseTrack._count = 41   # ids minted by a previous rally
    tracker.reset()
    assert BaseTrack._count == 0   # rally starts back at id 1


# ------------------------------------------------------------------ handler

class _T:
    def __init__(self, arr):
        self._a = np.asarray(arr, dtype=float)

    def cpu(self):
        return self

    def numpy(self):
        return self._a


class _FakeTracker:
    def __init__(self):
        self.resets = 0

    def reset(self):
        self.resets += 1


class _FakeModel:
    def __init__(self, ids=(1, 2)):
        self._ids = list(ids)
        self.track_kwargs = []
        self.predictor = types.SimpleNamespace(trackers=[_FakeTracker()])

    def track(self, frame, **kwargs):
        self.track_kwargs.append(kwargs)
        n = len(self._ids)
        boxes = types.SimpleNamespace(
            xyxy=_T([[10 + 30 * i, 10, 40 + 30 * i, 90] for i in range(n)]),
            conf=_T([0.9] * n),
            id=_T(self._ids),
        )
        return [types.SimpleNamespace(boxes=boxes, keypoints=None)]


def test_detect_pose_always_persists_and_resets_per_rally(monkeypatch):
    fake = _FakeModel(ids=(1, 2))
    monkeypatch.setattr(handler, "_pose_model", fake)
    monkeypatch.setattr(handler, "_track_error", "")
    frame = np.zeros((120, 160, 3), dtype=np.uint8)

    players, _, _ = handler._detect_pose(frame, reset_tracker=True)
    handler._detect_pose(frame, reset_tracker=False)
    handler._detect_pose(frame, reset_tracker=False)
    handler._detect_pose(frame, reset_tracker=True)   # next rally

    # persist=True on EVERY call — never the captured-False footgun.
    assert [kw.get("persist") for kw in fake.track_kwargs] == [True] * 4
    # Explicit reset exactly at the two rally boundaries.
    assert fake.predictor.trackers[0].resets == 2
    # Tracker ids still flow out on the boxes.
    assert [p.get("track_id") for p in players] == [1, 2]


def test_rally_boundary_clears_previous_tracker_error(monkeypatch):
    fake = _FakeModel()
    monkeypatch.setattr(handler, "_pose_model", fake)
    monkeypatch.setattr(handler, "_track_error", "RuntimeError: transient CUDA hiccup")
    frame = np.zeros((120, 160, 3), dtype=np.uint8)

    handler._detect_pose(frame, reset_tracker=True)

    assert handler._track_error == ""
    assert fake.track_kwargs   # tracking was retried, not skipped
