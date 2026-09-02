"""Background execution of runner.start_run() for the web UI.

Kept separate from runner.py on purpose: runner.py is pure orchestration (used
identically by the CLI, no threads, no web concerns), this module is the web
server's bookkeeping around running one in the background -- a thread, a
rolling log the browser can poll, and a way to ask it to stop.

A probe run can take from seconds to hours. The web request that starts it
must return immediately (so the browser can show progress), so the actual
work happens on a daemon thread while /api/run/<id>/progress is polled for
updates.
"""
import threading
import time

from . import runner as runner_mod

# Live jobs, run_id -> job dict. Deliberately in-process memory, not disk --
# the durable state of a run is run.json (written by runner.py itself) plus
# results.jsonl; this is only the thin "is it still going, and what just
# happened" view for a UI that is open right now. If the process restarts
# mid-run, run.json still shows run_state="running", which is handled by
# treating a run with no live job entry as of unknown/stalled state rather
# than lying about it being active.
_JOBS = {}
_LOCK = threading.Lock()

LOG_LIMIT = 400  # lines kept per run; enough to scroll, not an unbounded log


def start(root, **kwargs):
    """Launch a run in the background. Returns the run_id immediately."""
    run_id = kwargs.get("run_id") or time.strftime("%Y%m%d-%H%M%S")
    kwargs["run_id"] = run_id
    job = {"run_id": run_id, "log": [], "state": "starting",
           "stop_requested": False, "error": None}

    def log(msg):
        with _LOCK:
            job["log"].append(f"[{time.strftime('%H:%M:%S')}] {msg}")
            if len(job["log"]) > LOG_LIMIT:
                job["log"] = job["log"][-LOG_LIMIT:]

    def should_stop():
        return job["stop_requested"]

    def progress_cb(snapshot):
        with _LOCK:
            job["progress"] = snapshot

    def work():
        job["state"] = "running"
        try:
            runner_mod.start_run(root, log=log, progress_cb=progress_cb,
                                 should_stop=should_stop, **kwargs)
            job["state"] = "stopped" if job["stop_requested"] else "done"
        except Exception as e:
            job["state"] = "error"
            job["error"] = str(e)
            log(f"error: {e}")

    with _LOCK:
        _JOBS[run_id] = job
    threading.Thread(target=work, daemon=True).start()
    return run_id


def status(run_id):
    with _LOCK:
        job = _JOBS.get(run_id)
        if not job:
            return None
        return {"run_id": run_id, "state": job["state"],
                "error": job.get("error"), "log": list(job["log"]),
                "progress": job.get("progress")}


def request_stop(run_id):
    with _LOCK:
        job = _JOBS.get(run_id)
        if not job:
            return False
        job["stop_requested"] = True
        return True
