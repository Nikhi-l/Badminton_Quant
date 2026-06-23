"""Single background worker thread that drains the job queue through the pipeline."""
import queue
import threading
import traceback

from . import config, db
from .pipeline import run as pipeline_run

_q: "queue.Queue" = queue.Queue()
_started = False


def enqueue(job_id: str):
    _q.put(("job", job_id, None))


def enqueue_remix(job_id: str, params: dict):
    _q.put(("remix", job_id, params))


def _find_input(job_id: str) -> list:
    d = config.UPLOADS / job_id
    if not d.exists():
        return []
    return sorted(f for f in d.iterdir() if f.name.startswith("input"))


def _loop():
    while True:
        kind, job_id, params = _q.get()
        src = _find_input(job_id)
        if not src:
            db.set_error(job_id, "uploaded file missing on disk")
            continue
        workdir = config.OUTPUTS / job_id
        cb = lambda stage, msg: db.update_stage(job_id, stage, msg)  # noqa: E731
        try:
            if kind == "remix":
                old = db.get_job(job_id)
                try:
                    result = pipeline_run.remix(src[0], workdir,
                                                params.get("rallies") or [],
                                                bool(params.get("mirror")),
                                                camera=params.get("camera"), cb=cb)
                    db.set_done(job_id, result)
                except Exception:
                    # a failed remix must not brick a finished job
                    if old and old.get("result"):
                        import json as _json
                        db.set_done(job_id, _json.loads(old["result"]))
                    raise
            else:
                db.set_pipeline(job_id, config.pipeline_for_options(db.job_options(job_id)))
                result = pipeline_run.process(src, workdir, cb=cb,
                                              options=db.job_options(job_id))
                db.set_done(job_id, result)
        except Exception as e:  # noqa: BLE001 — job isolation: one bad video must not kill the worker
            traceback.print_exc()
            if kind != "remix":
                db.set_error(job_id, f"{type(e).__name__}: {e}")


def start():
    global _started
    if _started:
        return
    _started = True
    threading.Thread(target=_loop, daemon=True, name="baddy-worker").start()
    for job_id in db.pending_jobs():  # resume anything interrupted by a restart
        enqueue(job_id)
