"""TASK-041: RunPod poll must not count queue time against the run budget.

A busy endpoint held a job IN_QUEUE ~8 min, then it ran ~13 min; the old
single deadline (submission + TIMEOUT) fired at 20 min and abandoned a job
that COMPLETED on the worker ~90s later, silently downgrading the reel to the
CPU camera. The poll now runs the execution clock only once the job is RUNNING.
"""
import sys
import types

import pytest

from app import config
from app.pipeline import gpu


class _Resp:
    def __init__(self, payload):
        self._p = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._p


def _fake_clock():
    """Deterministic time source: each tick advances 60s (no real sleeping)."""
    t = {"now": 0.0}

    def now():
        return t["now"]

    def sleep(_):
        t["now"] += 60.0
    return now, sleep, t


def _install(monkeypatch, statuses, health=None):
    """statuses: list of state strings returned by successive /status polls."""
    now, sleep, t = _fake_clock()
    monkeypatch.setattr(gpu.time, "time", now)
    monkeypatch.setattr(gpu.time, "sleep", sleep)
    it = iter(statuses)

    def fake_get(url, **kw):
        if url.endswith("/health"):
            return _Resp(health or {"workers": {"idle": 2}})
        return _Resp({"status": next(it), "output": {"ok": True}})

    def fake_post(url, **kw):
        return _Resp({"id": "run1"})

    monkeypatch.setattr(gpu.requests, "get", fake_get)
    monkeypatch.setattr(gpu.requests, "post", fake_post)
    monkeypatch.setattr(config, "RUNPOD_ENDPOINT_ID", "ep")
    monkeypatch.setattr(config, "RUNPOD_API_KEY", "key")
    monkeypatch.setattr(config, "RUNPOD_BASE_URL", "https://api.runpod.ai/v2")
    monkeypatch.setattr(config, "RUNPOD_POLL_SEC", 1.0)
    monkeypatch.setattr(config, "RUNPOD_TIMEOUT_SEC", 1200.0)   # 20 min run budget
    monkeypatch.setattr(config, "RUNPOD_QUEUE_STALL_SEC", 150.0)
    monkeypatch.setattr(config, "RUNPOD_QUEUE_MAX_SEC", 900.0)
    return t


def test_long_queue_then_run_completes_not_abandoned(monkeypatch):
    # 8 polls IN_QUEUE (8 min, workers present) then 13 IN_PROGRESS (13 min)
    # then COMPLETED = 21 min wall — the exact case that used to time out.
    statuses = ["IN_QUEUE"] * 8 + ["IN_PROGRESS"] * 13 + ["COMPLETED"]
    _install(monkeypatch, statuses)
    out = gpu._runpod_request({"contract": gpu.CONTRACT}, log=lambda *_: None)
    assert out == {"ok": True}


def test_stalled_queue_no_workers_fast_fails(monkeypatch):
    statuses = ["IN_QUEUE"] * 20
    _install(monkeypatch, statuses, health={"workers": {"idle": 0, "running": 0}})
    with pytest.raises(RuntimeError, match="no available workers"):
        gpu._runpod_request({"contract": gpu.CONTRACT}, log=lambda *_: None)


def test_runaway_execution_still_times_out(monkeypatch):
    # Job starts running then never finishes: the execution clock must still
    # fire (25 min of IN_PROGRESS > 20 min run budget).
    statuses = ["IN_PROGRESS"] * 25
    _install(monkeypatch, statuses)
    with pytest.raises(TimeoutError, match="after starting"):
        gpu._runpod_request({"contract": gpu.CONTRACT}, log=lambda *_: None)
