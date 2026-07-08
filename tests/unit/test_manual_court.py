"""TASK-027: user-drawn court corners — option validation, manual geometry,
and the existing-job recompute endpoint."""
import json

import numpy as np
import pytest
from fastapi.testclient import TestClient

from app import config, db
from app.main import app
from app.pipeline import court, rally3d

CORNERS = [[0.34, 0.22], [0.66, 0.22], [0.9, 0.88], [0.1, 0.88]]


def test_court_corners_option_validation():
    assert config.court_corners_option(CORNERS) == CORNERS
    assert config.court_corners_option(None) is None
    assert config.court_corners_option([[0, 0]] * 3) is None            # not 4
    assert config.court_corners_option([[2, 0], [0, 0], [1, 1], [0, 1]]) is None  # off-frame
    assert config.court_corners_option([[0.5, 0.5]] * 4) is None        # degenerate
    opts = config.normalize_options({"shuttle": "off", "court_corners": CORNERS})
    assert opts["court_corners"] == CORNERS
    assert "court_corners" not in config.normalize_options({"shuttle": "off"})


def test_manual_result_builds_right_handed_court():
    out = court.manual_result(CORNERS, (1280, 720))
    assert out["status"] == "ok" and out["source"] == "manual"
    assert out["confidence"] >= 0.9
    assert rally3d.is_right_handed(out["homography"], 1280, 720) is True
    # Corners map onto the court plane.
    u, v = court.project(out["homography"], *out["corners"][2])
    assert abs(u - court.COURT_WIDTH_M) < 0.2 and abs(v - court.COURT_LENGTH_M) < 0.3


@pytest.fixture()
def client(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "jobs.sqlite")
    monkeypatch.setattr(config, "OUTPUTS", tmp_path / "outputs")
    monkeypatch.setattr(config, "UPLOADS", tmp_path / "uploads")
    (tmp_path / "uploads").mkdir()   # startup sweeps this dir
    db.init()
    with TestClient(app) as c:
        yield c


def _seed_job(job_id="manualcourt1"):
    workdir = config.OUTPUTS / job_id
    workdir.mkdir(parents=True, exist_ok=True)
    # A ballistic shot projected through a known camera, so the endpoint's
    # recompute has something real to reconstruct.
    W, H, F = 1280, 720, 1400.0
    C = np.array([3.05, 27.0, 8.0])   # frames the whole court (clickable corners)
    target = np.array([3.05, 6.7, 1.0])
    fwd = target - C
    fwd /= np.linalg.norm(fwd)
    up = np.array([0.0, 0.0, 1.0])
    xc = np.cross(fwd, up)
    xc /= np.linalg.norm(xc)
    yc = np.cross(fwd, xc)
    R = np.stack([xc, yc, fwd])
    t = -R @ C

    def project(pts):
        p = (R @ np.asarray(pts, float).T).T + t
        return np.column_stack([F * p[:, 0] / p[:, 2] / W + 0.5,
                                F * p[:, 1] / p[:, 2] / H + 0.5])

    corners_img = project([(0, 0, 0), (6.1, 0, 0), (6.1, 13.4, 0), (0, 13.4, 0)])
    idx = np.argsort(corners_img[:, 1])
    top = sorted(idx[:2], key=lambda i: corners_img[i, 0])
    bot = sorted(idx[2:], key=lambda i: corners_img[i, 0])
    ordered = [corners_img[i].tolist() for i in (top[0], top[1], bot[1], bot[0])]

    ts = np.arange(10.0, 11.0, 0.1)
    traj = rally3d.simulate(np.array([1.6, 11.2, 2.4]), np.array([1.2, -9.5, 5.0]), 10.0, ts)
    uv = project(traj)
    shuttle = [{"t": float(a), "x": float(x), "y": float(y), "confidence": 0.9}
               for a, (x, y) in zip(ts, uv)]

    result = {
        "duration": 10.0, "n_rallies_used": 1, "n_rallies_found": 1,
        "source": {"w": W, "h": H, "fps": 30, "duration": 20.0},
        "court": {"status": "not_found"},
        "rallies": [{"start": 10.0, "end": 11.0, "dur": 1.0, "clip_dur": 1.0,
                     "vision": {"status": "ok", "shuttle_quality": 0.8,
                                "shuttle": shuttle}}],
    }
    (workdir / "result.json").write_text(json.dumps(result))
    db.create_job(job_id, "manual court test", options={})
    db.set_done(job_id, result)
    return job_id, ordered


def test_set_court_endpoint_recomputes_3d(client):
    job_id, ordered = _seed_job()
    r = client.post(f"/api/jobs/{job_id}/court", json={"corners": ordered})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["court"]["source"] == "manual"
    assert body["rallies_3d"] == 1

    # Persisted to both the DB payload and the on-disk result.
    full = client.get(f"/api/jobs/{job_id}").json()["result"]
    assert full["court"]["source"] == "manual"
    assert full["rallies"][0]["rally_3d"]["status"] == "ok"
    disk = json.loads((config.OUTPUTS / job_id / "result.json").read_text())
    assert disk["rallies"][0]["rally_3d"]["shots"]


def test_set_court_endpoint_rejects_bad_corners(client):
    job_id, _ = _seed_job("manualcourt2")
    r = client.post(f"/api/jobs/{job_id}/court", json={"corners": [[0.5, 0.5]] * 4})
    assert r.status_code == 400
    r = client.post("/api/jobs/nosuchjob/court", json={"corners": CORNERS})
    assert r.status_code == 409


def test_racquet_track_exposed_bounded():
    from app.main import _public_rally
    frames = [{"t": i / 30, "boxes": [{"x1": 0.4, "y1": 0.5, "x2": 0.46, "y2": 0.58,
                                       "confidence": 0.55}]}
              for i in range(300)]
    out = _public_rally({
        "start": 0.0, "end": 10.0, "dur": 10.0,
        "vision": {"status": "ok", "racquet_quality": 0.5, "racquets": frames},
    })
    track = out["vision"]["racquet_track"]
    assert 0 < len(track) <= 120
    assert set(track[0]["boxes"][0]) == {"x", "y", "w", "h", "confidence"}


def test_retry_requeues_failed_job(client, monkeypatch):
    calls = []
    from app import worker
    monkeypatch.setattr(worker, "enqueue", lambda jid: calls.append(jid))
    (config.UPLOADS / "retryme").mkdir(parents=True, exist_ok=True)
    (config.UPLOADS / "retryme" / "input_00.mp4").write_bytes(b"x")
    db.create_job("retryme", "crashed.mp4", options={})
    db.set_error("retryme", "ValueError: operands could not be broadcast")

    r = client.post("/api/jobs/retryme/retry")
    assert r.status_code == 200 and calls == ["retryme"]
    job = db.get_job("retryme")
    assert job["status"] == "queued" and job["error"] is None

    # done jobs are refused without the explicit reprocess flag
    db.set_done("retryme", {"duration": 1})
    assert client.post("/api/jobs/retryme/retry").status_code == 409
    assert client.post("/api/jobs/retryme/retry?reprocess=1").status_code == 200
    assert db.get_job("retryme")["status"] == "queued"
    db.create_job("noinput", "gone.mp4", options={})
    db.set_error("noinput", "boom")
    assert client.post("/api/jobs/noinput/retry").status_code == 409
