"""TASK-026 P0: schools auth, tenancy scoping, assignment, student profile."""
import json

import pytest
from fastapi.testclient import TestClient

from app import auth, config, db
from app.main import app


@pytest.fixture()
def client(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "jobs.sqlite")
    # keep scrypt cheap in tests
    monkeypatch.setattr(auth, "_SCRYPT", {"n": 2 ** 4, "r": 8, "p": 1})
    db.init()
    with TestClient(app) as c:   # separate cookie jars per actor below
        yield c


def _register_school(c, school="Green Valley High", user="coach.admin"):
    r = c.post("/api/auth/register-school", json={
        "school_name": school, "name": "Admin A", "username": user,
        "password": "supersecret1"})
    assert r.status_code == 200, r.text
    return r.json()


def _codes(c):
    return c.get("/api/school/overview").json()["join_codes"]


def test_register_login_join_roles_flow(client):
    _register_school(client)
    me = client.get("/api/auth/me").json()
    assert me["role"] == "admin" and me["school_name"] == "Green Valley High"
    codes = _codes(client)
    assert codes["student"].startswith("ST-") and codes["coach"].startswith("CO-")

    # student joins with the student code (fresh cookie jar)
    student = TestClient(app)
    r = student.post("/api/auth/join", json={
        "code": codes["student"], "name": "Nia Player", "username": "nia",
        "password": "password123"})
    assert r.status_code == 200 and r.json()["role"] == "student"
    assert student.get("/api/auth/me").json()["role"] == "student"

    # student cannot see the coach/admin overview
    assert student.get("/api/school/overview").status_code == 403

    # logout kills the session
    student.post("/api/auth/logout")
    assert student.get("/api/auth/me").status_code == 401

    # login again
    r = student.post("/api/auth/login", json={"username": "NIA", "password": "password123"})
    assert r.status_code == 200
    assert student.get("/api/auth/me").json()["name"] == "Nia Player"

    # wrong password rejected; duplicate username rejected
    bad = TestClient(app)
    assert bad.post("/api/auth/login", json={"username": "nia", "password": "nope-nope"}).status_code == 401
    assert bad.post("/api/auth/join", json={"code": codes["student"], "name": "X",
                                            "username": "nia", "password": "password123"}).status_code == 409


def _done_job(job_id, school_id=None, uploader=None, with_result=True):
    db.create_job(job_id, f"{job_id}.mp4", {"shuttle": "off", "pose": "off"})
    if school_id:
        db.set_job_owner(job_id, school_id, uploader)
    if with_result:
        players = [{"t": i / 3.0, "boxes": [
            {"x1": 0.2, "y1": 0.55, "x2": 0.34, "y2": 0.9, "confidence": 0.8},
            {"x1": 0.6, "y1": 0.2, "x2": 0.68, "y2": 0.36, "confidence": 0.6},
        ]} for i in range(30)]
        db.set_done(job_id, {
            "duration": 30.0,
            "rallies": [{"dur": 12.0, "note": "long rally",
                         "vision": {"shuttle_quality": 0.8, "players": players}}],
            "vision": {"summary": {"shuttle_quality": 0.8, "pose_quality": 0.7,
                                   "player_quality": 0.6}},
            "coach": {"status": "ok", "headline": "Solid base game",
                      "confidence": 0.7, "strengths": ["footwork"], "work_on": ["smash"]},
            "court": {"status": "ok",
                      "homography": [6.1, 0, 0, 0, 13.4, 0, 0, 0, 1]},
        })


def test_assignment_and_student_profile_scoping(client):
    out = _register_school(client)
    school_id = out["school_id"]
    codes = _codes(client)

    student = TestClient(app)
    student.post("/api/auth/join", json={"code": codes["student"], "name": "Nia",
                                         "username": "nia", "password": "password123"})
    sid = student.get("/api/auth/me").json()["id"]

    _done_job("job1", school_id, uploader="whoever")
    _done_job("otherschool")   # unowned/anonymous job

    # overview lists only the school's job
    jobs = client.get("/api/school/overview").json()["jobs"]
    assert [j["id"] for j in jobs] == ["job1"]

    # cannot assign a job outside the school; cannot assign unknown student
    assert client.post("/api/jobs/otherschool/assign", json={"student_id": sid}).status_code == 404
    assert client.post("/api/jobs/job1/assign", json={"student_id": "ghost"}).status_code == 404

    # assign with a player pin; the student profile aggregates it
    r = client.post("/api/jobs/job1/assign", json={"student_id": sid, "player_id": 0})
    assert r.status_code == 200 and r.json()["assignees"][0]["player_id"] == 0

    profile = student.get(f"/api/students/{sid}/profile").json()
    assert profile["student"]["name"] == "Nia"
    s = profile["sessions"][0]
    assert s["job_id"] == "job1" and s["n_rallies"] == 1 and s["longest_rally"] == 12.0
    assert s["coach"]["headline"] == "Solid base game"
    assert s["movement"]["court_space"] is True and s["movement"]["points"] > 0
    assert s["movement"]["coverage_pct"] > 0

    # students can't read other students; a coach of the school can
    other = TestClient(app)
    other.post("/api/auth/join", json={"code": codes["student"], "name": "Zed",
                                       "username": "zed", "password": "password123"})
    assert other.get(f"/api/students/{sid}/profile").status_code == 403
    assert client.get(f"/api/students/{sid}/profile").status_code == 200

    # unassign removes the session from the profile
    client.delete(f"/api/jobs/job1/assign/{sid}")
    assert student.get(f"/api/students/{sid}/profile").json()["sessions"] == []


def test_anonymous_upload_flow_untouched(client):
    # No cookie: job creation via the internal path has no owner and public
    # endpoints keep working exactly as before.
    _done_job("anonjob")
    job = db.get_job("anonjob")
    assert job["school_id"] is None and job["uploaded_by"] is None
    assert client.get("/api/jobs/anonjob").status_code == 200
    assert client.get("/api/gallery").status_code == 200


def test_migration_is_idempotent_and_additive(client):
    db.init()
    db.init()   # re-running must not fail or duplicate
    cols = {r[1] for r in db._conn().execute("PRAGMA table_info(jobs)").fetchall()}
    assert {"school_id", "uploaded_by"} <= cols
