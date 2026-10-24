"""bin/relic5-backup against a fake hub (ssh runs the command here with HOME = the hub's home; rsync is real), and
relic_status's "last backup" line and its 36 h warning."""
import json, os, subprocess
from datetime import datetime, timedelta, timezone

import pytest

from relic5.status import last_backup, status

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FAKE_SSH = """#!/bin/sh
while [ "$1" = "-o" ] || [ "$1" = "-l" ]; do shift 2; done
shift   # host
export HOME="$FAKE_HUB_HOME"
cd "$HOME" && exec sh -c "$*"
"""


@pytest.fixture
def env(tmp_path):
    hub, fb, dest = tmp_path / "hubhome", tmp_path / "fakebin", tmp_path / "backup"
    for d in ("relic5/parts/m5/text", "relic5/vectors/g@1", "relic5/index/_search", "relic5/logs", ".config/relic5"):
        (hub / d).mkdir(parents=True)
    (hub / "relic5/parts/m5/text/2026-10.parquet").write_bytes(b"x" * 5000)
    (hub / "relic5/vectors/g@1/shard.npy").write_bytes(b"v" * 3000)
    (hub / "relic5/index/_search/big.lance").write_bytes(b"i" * 9000)     # rebuilt from parts: never backed up
    (hub / ".config/relic5/tokens").write_text("m5 secret\n")
    st = tmp_path / "status.json"
    st.write_text(json.dumps({"rows": {"text": 1}}))
    fb.mkdir()
    (fb / "ssh").write_text(FAKE_SSH)
    (fb / "ssh").chmod(0o755)
    e = dict(os.environ, PATH=f"{fb}:{os.environ['PATH']}", FAKE_HUB_HOME=str(hub), RELIC5_HUB_SSH="hub",
             RELIC5_BACKUP_DIR=str(dest), RELIC5_BACKUP_STATUS_URL=f"file://{st}", RELIC5_BACKUP_KEEP="2")
    return hub, dest, e


def backup(e):
    return subprocess.run([os.path.join(REPO, "bin/relic5-backup")], env=e, capture_output=True, text=True)


def test_snapshot_keeps_data_not_index_and_logs_a_job(env):
    hub, dest, e = env
    r = backup(e)
    assert r.returncode == 0, r.stderr
    snap = dest / "latest"
    assert (snap / "parts/m5/text/2026-10.parquet").stat().st_size == 5000
    assert (snap / "vectors/g@1/shard.npy").exists() and (snap / "config/tokens").read_text() == "m5 secret\n"
    assert not (snap / "index").exists()                                   # rebuilt, not copied
    assert json.load(open(snap / "hub-status.json"))["rows"]["text"] == 1   # what the restore test compares to
    assert not (dest / "latest").resolve().stat().st_mode & 0o077 and not dest.stat().st_mode & 0o077   # 700: only us
    evs = [json.loads(l) for l in open(hub / "relic5/logs/jobs.jsonl")]
    assert [x["state"] for x in evs] == ["start", "done"] and evs[1]["verb"] == "backup" and evs[1]["done"] > 0


def test_second_snapshot_hardlinks_and_old_ones_are_pruned(env):
    import time
    hub, dest, e = env
    for _ in range(3):
        assert backup(e).returncode == 0
        time.sleep(1.1)                                                     # snapshot names are per second
    snaps = sorted(p for p in dest.iterdir() if p.name[0] == "2")
    assert len(snaps) == 2                                                  # RELIC5_BACKUP_KEEP=2
    a, b = (s / "parts/m5/text/2026-10.parquet" for s in snaps)
    assert a.stat().st_ino == b.stat().st_ino                               # unchanged file: one copy on disk


def test_failure_leaves_a_partial_and_an_error_event(env):
    hub, dest, e = env
    r = backup(dict(e, RELIC5_BACKUP_STATUS_URL="file:///no/such/status.json"))
    assert r.returncode == 1 and "no hub status saved" in r.stderr
    assert not (dest / "latest").exists() and any(p.name.endswith(".partial") for p in dest.iterdir())
    evs = [json.loads(l) for l in open(hub / "relic5/logs/jobs.jsonl")]
    assert evs[-1]["state"] == "error"


def ev(at, state="done", verb="backup"):
    return {"job": f"{verb}-x", "verb": verb, "state": state, "at": at.strftime("%Y-%m-%dT%H:%M:%SZ"), "done": 123}


def test_last_backup_and_its_warning(root):
    now = datetime(2026, 10, 24, 12, 0, tzinfo=timezone.utc)
    assert last_backup([], now)["at"] is None
    b = last_backup([ev(now - timedelta(hours=40), "start"), ev(now - timedelta(hours=5))], now)
    assert b["age_s"] == 5 * 3600 and b["bytes"] == 123
    assert any("no backup yet" in w for w in status(root)["warnings"])
    os.makedirs(os.path.join(root, "logs"), exist_ok=True)
    with open(os.path.join(root, "logs/jobs.jsonl"), "a") as f:
        f.write(json.dumps(ev(datetime.now(timezone.utc) - timedelta(hours=40))) + "\n")
    s = status(root)
    assert s["backup"]["at"] and any(w.startswith("last backup 40 h ago") for w in s["warnings"])


def test_restore_test_rebuilds_a_snapshot_and_matches(root, tmp_path):
    """The whole loop on the fixture hub: index it, back it up (hub-status.json from its own status), restore-test."""
    import shutil
    from relic5.cli import main as _  # noqa: F401  (the CLI is importable: the restore test calls it as a process)
    hub = tmp_path / "hubhome2"
    (hub / ".config/relic5").mkdir(parents=True)
    (hub / ".config/relic5/tokens").write_text("m5 t\n")
    shutil.copytree(os.path.join(root, "parts"), hub / "relic5/parts")
    venv = os.path.join(REPO, ".venv/bin")
    assert subprocess.run([f"{venv}/relic5", "index", "--root", str(hub / "relic5")], capture_output=True).returncode == 0
    st = tmp_path / "st.json"
    st.write_text(json.dumps(status(str(hub / "relic5"))))
    fb = tmp_path / "fb2"
    fb.mkdir()
    (fb / "ssh").write_text(FAKE_SSH)
    (fb / "ssh").chmod(0o755)
    e = dict(os.environ, PATH=f"{fb}:{os.environ['PATH']}", FAKE_HUB_HOME=str(hub), RELIC5_HUB_SSH="hub",
             RELIC5_BACKUP_DIR=str(tmp_path / "bk"), RELIC5_BACKUP_STATUS_URL=f"file://{st}")
    assert backup(e).returncode == 0
    r = subprocess.run([os.path.join(REPO, "bin/relic5-restore-test"), str(tmp_path / "bk/latest")], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "restore test PASSED" in r.stdout and "parts/m5 text" in r.stdout
    (tmp_path / "bk/latest/hub-status.json").write_text(json.dumps(dict(json.load(open(st)), rows={"text": 999})))
    r = subprocess.run([os.path.join(REPO, "bin/relic5-restore-test"), str(tmp_path / "bk/latest")], capture_output=True, text=True)
    assert r.returncode == 1 and "DIFFERS" in r.stdout                        # a wrong count fails loudly
