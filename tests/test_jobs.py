import json, os, time

from relic5 import jobs
from relic5.status import status


def test_job_events_and_running(tmp_path):
    root = str(tmp_path)
    with jobs.job(root, "index") as j:
        j.progress(done=3, unit="months")
        _, running = jobs.read(root)
        assert [e["verb"] for e in running] == ["index"]           # our own pid is alive
    evs, running = jobs.read(root)
    assert running == [] and evs[0]["state"] == "done" and evs[0]["rc"] == 0
    lines = [json.loads(l) for l in open(jobs.log_path(root))]
    assert [l["state"] for l in lines] == ["start", "progress", "done"] and lines[0]["who"]["argv"] is not None


def test_error_is_reported_until_a_later_success(root):
    try:
        with jobs.job(root, "index"):
            raise RuntimeError("disk full")
    except RuntimeError:
        pass
    s = status(root)
    assert s["jobs"]["last_error"]["message"].startswith("RuntimeError: disk full")
    assert any("last index failed" in w for w in s["warnings"])
    time.sleep(1.1)
    with jobs.job(root, "index"):
        pass
    assert not any("last index failed" in w for w in status(root)["warnings"])


def test_dead_pid_is_not_running(tmp_path):
    root = str(tmp_path)
    jobs.emit(root, {"job": "x", "verb": "embed", "state": "start", "at": jobs._now(), "pid": 999999, "host": __import__("socket").gethostname()})
    assert jobs.read(root)[1] == []
