"""bin/relic5-push against a fake hub: ssh runs the command here with HOME = the hub's home; rsync is real."""
import os, subprocess

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FAKE_SSH = """#!/bin/sh
while [ "$1" = "-o" ]; do shift 2; done
shift   # host
export HOME="$FAKE_HUB_HOME"
cd "$HOME" && exec sh -c "$*"
"""


@pytest.fixture
def env(tmp_path):
    src, hub, fb = tmp_path / "extract", tmp_path / "hubhome", tmp_path / "fakebin"
    for d in (src / "text", src / "tools", src / "report", hub, fb):
        d.mkdir(parents=True)
    (src / "text/2026-10.parquet").write_bytes(b"x" * 1000)
    (src / "text/.2026-11.parquet.part").write_bytes(b"half")
    (src / "tools/2026-10.parquet").write_bytes(b"y" * 10)
    (src / "report/report.json").write_text("{}")
    (fb / "ssh").write_text(FAKE_SSH)
    (fb / "ssh").chmod(0o755)
    e = dict(os.environ, PATH=f"{fb}:{os.environ['PATH']}", FAKE_HUB_HOME=str(hub), RELIC5_SRC=str(src),
             RELIC5_HUB="hub", RELIC5_MACHINE="m5")
    return src, hub, e


def push(e, *args):
    return subprocess.run([os.path.join(REPO, "bin/relic5-push"), *args], env=e, capture_output=True, text=True)


def test_push_streams_only(env):
    src, hub, e = env
    r = push(e)
    assert r.returncode == 0, r.stderr
    base = hub / "relic5/parts/m5"
    assert (base / "text/2026-10.parquet").stat().st_size == 1000
    assert (base / "tools/2026-10.parquet").exists()
    assert not (base / "report").exists()                       # derived reports stay home
    assert not (base / "text/.2026-11.parquet.part").exists()   # half-written part never sent
    assert os.path.getmtime(base / "text/2026-10.parquet") == pytest.approx(os.path.getmtime(src / "text/2026-10.parquet"), abs=1)
    assert "stream text     files=1" in r.stdout
    v = __import__("json").load(open(base / "_versions.json"))
    assert v["machine"] == "m5" and "relic-scan" in v and v["relic5-push"]


def test_second_push_sends_nothing_and_never_deletes(env):
    src, hub, e = env
    push(e)
    (src / "tools/2026-10.parquet").unlink()
    r = push(e)
    assert r.returncode == 0
    assert "stream text     files=0" in r.stdout
    assert (hub / "relic5/parts/m5/tools/2026-10.parquet").exists()   # no --delete


def test_refuses_symlinked_target(env, tmp_path):
    src, hub, e = env
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (hub / "relic5/parts").mkdir(parents=True)
    os.symlink(elsewhere, hub / "relic5/parts/m5")
    r = push(e)
    assert r.returncode == 1 and "refuse" in r.stderr
    assert list(elsewhere.iterdir()) == []


def test_bad_machine_name(env):
    _, _, e = env
    assert push(dict(e, RELIC5_MACHINE="../x")).returncode == 2


def test_waits_for_extract_lock(env):
    src, _, e = env
    (src / ".lock").touch()
    holder = subprocess.Popen(["perl", "-MFcntl=:flock", "-e", 'open(F,"<",$ARGV[0]); flock(F,LOCK_EX); print "held\\n"; $|=1; sleep 30',
                               str(src / ".lock")], stdout=subprocess.PIPE, text=True)
    try:
        assert holder.stdout.readline() == "held\n"
        r = push(e)
        assert r.returncode == 75 and "relic-extract is running" in r.stderr
    finally:
        holder.kill()
    assert push(e).returncode == 0
