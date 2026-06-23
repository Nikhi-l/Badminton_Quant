import sqlite3

from app import config, db
from app.main import _job_meta, job_status


def _tmp_db(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "jobs.sqlite")
    db.init()


def test_create_job_records_pipeline_and_generation_timing(monkeypatch, tmp_path):
    _tmp_db(monkeypatch, tmp_path)

    db.create_job("cpujob", "cpu.mp4", {"shuttle": "off", "pose": "yolo11"})
    db.create_job("gpujob", "gpu.mp4", {"shuttle": "tracknetv3", "pose": "off"})

    cpu = db.get_job("cpujob")
    gpu = db.get_job("gpujob")
    assert cpu["pipeline"] == "cpu"
    assert gpu["pipeline"] == "gpu"
    assert cpu["started_at"] is None
    assert cpu["finished_at"] is None

    db.update_stage("cpujob", "probe", "reading metadata")
    processing = db.get_job("cpujob")
    assert processing["status"] == "processing"
    assert processing["stage"] == "probe"
    assert processing["started_at"] is not None
    assert processing["finished_at"] is None

    db.set_done("cpujob", {"duration": 12.3})
    done = db.get_job("cpujob")
    assert done["status"] == "done"
    assert done["stage"] == "done"
    assert done["finished_at"] >= done["started_at"]

    meta = _job_meta(done)
    assert meta["submitted_at"] == done["created_at"]
    assert meta["pipeline"] == "cpu"
    assert meta["expected_gen_seconds"] == config.EXPECTED_CPU_GEN_SEC
    assert meta["gen_seconds"] >= 0


def test_failed_status_replaces_legacy_error_state(monkeypatch, tmp_path):
    _tmp_db(monkeypatch, tmp_path)

    db.create_job("badjob", "bad.mp4", {"shuttle": "tracknetv3"})
    db.set_error("badjob", "x" * 700)

    failed = db.get_job("badjob")
    assert failed["status"] == "failed"
    assert failed["stage"] == "queued"
    assert len(failed["error"]) == 500
    assert failed["started_at"] is not None
    assert failed["finished_at"] >= failed["started_at"]

    public = job_status("badjob")
    assert public["status"] == "failed"
    assert public["pipeline"] == "gpu"
    assert public["expected_gen_seconds"] == config.EXPECTED_GPU_GEN_SEC
    assert public["gen_seconds"] >= 0


def test_jobs_queue_lists_all_statuses_newest_first(monkeypatch, tmp_path):
    _tmp_db(monkeypatch, tmp_path)
    from app.main import jobs_queue

    db.create_job("j_queued", "a.mp4", {"shuttle": "off"})
    db.create_job("j_done", "b.mp4", {"shuttle": "tracknetv3"})
    db.set_done("j_done", {"duration": 5.0})
    db.create_job("j_failed", "c.mp4", {"shuttle": "off"})
    db.set_error("j_failed", "boom")

    jobs = jobs_queue()["jobs"]
    by_id = {j["id"]: j for j in jobs}
    assert set(by_id) == {"j_queued", "j_done", "j_failed"}
    # newest-first (created_at desc)
    times = [j["submitted_at"] for j in jobs]
    assert times == sorted(times, reverse=True)
    assert by_id["j_queued"]["status"] == "queued"
    assert by_id["j_done"]["status"] == "done"
    assert by_id["j_done"]["thumb"].endswith("/thumb.jpg")
    assert by_id["j_done"]["pipeline"] == "gpu"          # shuttle=tracknetv3 -> gpu
    assert by_id["j_done"]["error"] is None              # error only on failed jobs
    assert by_id["j_failed"]["status"] == "failed"
    assert by_id["j_failed"]["error"] == "boom"
    assert by_id["j_queued"]["expected_gen_seconds"] is not None


def test_init_migrates_existing_jobs_additively(monkeypatch, tmp_path):
    path = tmp_path / "legacy.sqlite"
    with sqlite3.connect(path) as c:
        c.execute("""
            CREATE TABLE jobs (
              id TEXT PRIMARY KEY,
              filename TEXT,
              status TEXT NOT NULL DEFAULT 'queued',
              stage TEXT DEFAULT 'queued',
              message TEXT DEFAULT '',
              result TEXT,
              error TEXT,
              created_at REAL,
              updated_at REAL
            )
        """)
        c.execute("INSERT INTO jobs (id, filename, status, stage, created_at, updated_at) "
                  "VALUES ('legacy', 'old.mp4', 'error', 'render', 10, 20)")

    monkeypatch.setattr(config, "DB_PATH", path)
    db.init()

    migrated = db.get_job("legacy")
    assert migrated["status"] == "failed"
    assert migrated["stage"] == "render"
    assert migrated["options"] is None
    assert migrated["pipeline"] == "cpu"
    assert migrated["started_at"] == 10
    assert migrated["finished_at"] == 20
