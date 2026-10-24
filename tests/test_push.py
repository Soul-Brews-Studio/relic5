"""bin/relic5-push against a fake hub: ssh runs the command here with HOME = the hub's home; rsync is real."""
import os, subprocess

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FAKE_SSH = """#!/bin/sh
while [ "$1" = "-o" ] || [ "$1" = "-l" ]; do shift 2; done
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
    # the stamp is the commit that last changed the script, not HEAD: identical copies installed at different
    # commits must not read as different versions (2026-10-24: eae351e, 039a4ee, a8e7f33 were one script)
    own = subprocess.run(["git", "-C", os.path.join(REPO, "bin"), "log", "-1", "--format=%h", "--", "relic5-push"],
                         capture_output=True, text=True).stdout.strip()
    assert v["relic5-push"] == own
    evs = [__import__("json").loads(l) for l in open(hub / "relic5/logs/jobs.jsonl")]
    assert [e["state"] for e in evs] == ["start", "done"] and evs[1]["unit"] == "bytes" and evs[1]["done"] > 0


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


def test_local_hub_needs_no_ssh(env, tmp_path):
    src, _, e = env
    home = tmp_path / "selfhome"
    home.mkdir()
    e = dict(e, RELIC5_HUB="local", HOME=str(home), PATH="/usr/bin:/bin:/opt/homebrew/bin")   # no fake ssh on PATH
    r = push(e)
    assert r.returncode == 0, r.stderr
    assert (home / "relic5/parts/m5/text/2026-10.parquet").exists()


def test_an_http_hub_url_means_ssh_to_its_host(env):
    src, hub, e = env
    r = push(dict(e, RELIC5_HUB="http://hub:8795"))       # what relic-chain exports for its SYNC check
    assert r.returncode == 0, r.stderr
    assert "-> nat@hub:" in r.stdout and (hub / "relic5/parts/m5/text/2026-10.parquet").exists()


def test_push_sends_the_chain_sync_line(env, tmp_path):
    src, hub, e = env
    log = tmp_path / "relic-chain.log"
    log.write_text("x\n2026-10-23 23:10:15 SYNC OK  text|868825 thinking|1 tools|2\nchain start\n")
    assert push(dict(e, RELIC5_CHAIN_LOG=str(log))).returncode == 0
    import json as _j
    assert _j.load(open(hub / "relic5/parts/m5/_sync.json"))["line"] == "2026-10-23 23:10:15 SYNC OK  text|868825 thinking|1 tools|2"


def test_extra_memory_root_gets_its_own_home(env, tmp_path):
    """RELIC5_MEMORY_ROOTS: another user's exported notes go to <parent>-<home>, never on top of this account's."""
    src, hub, e = env
    home, export = tmp_path / "me", tmp_path / "nat-export"
    for h, text in ((home / ".claude", "mine"), (export / ".claude", "nat's")):
        d = h / "projects/-opt-x/memory"
        d.mkdir(parents=True)
        (d / "note.md").write_text(text)
    r = push(dict(e, HOME=str(home), RELIC5_MEMORY_ROOTS=str(export / ".claude")))
    assert r.returncode == 0, r.stderr
    mem = hub / "relic5/parts/m5/memory"
    assert (mem / "claude/-opt-x/memory/note.md").read_text() == "mine"
    assert (mem / "nat-export-claude/-opt-x/memory/note.md").read_text() == "nat's"
