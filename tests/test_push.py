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
             RELIC5_HUB="hub", RELIC5_MACHINE="m5", RELIC5_GIT="0",
             RELIC5_NEW_MACHINE="1", RELIC5_MACHINE_FILE=str(tmp_path / "no-name-file"))   # never walk this machine's real ghq tree
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


def test_git_logs_of_every_ghq_repo(env, tmp_path):
    """Each repo of `ghq list` goes as one raw git log; a repo whose refs did not move is not read again."""
    src, hub, e = env
    root, fb = tmp_path / "ghq", tmp_path / "fakebin"
    repo = root / "github.com/acme/widget"
    repo.mkdir(parents=True)
    g = lambda *a: subprocess.run(["git", "-C", str(repo), *a], check=True, capture_output=True,
                                  env=dict(os.environ, GIT_AUTHOR_DATE="2025-03-25T16:28:00+07:00", GIT_COMMITTER_DATE="2025-03-25T16:28:00+07:00"))
    g("init", "-q")
    g("-c", "user.name=Nat", "-c", "user.email=n@x", "commit", "-q", "--allow-empty", "-m",
      "Fix template paths\n\n🤖 Generated with [Claude Code](https://claude.ai/code)\n\nCo-Authored-By: Claude <noreply@anthropic.com>")
    (root / "github.com/acme/empty").mkdir(parents=True)   # not a repo: skipped, nothing sent
    (fb / "ghq").write_text(f"#!/bin/sh\n[ \"$1\" = root ] && echo {root} && exit 0\nprintf '%s\\n' {repo} {root}/github.com/acme/empty\n")
    (fb / "ghq").chmod(0o755)
    cache = tmp_path / "gitcache"
    e = dict(e, RELIC5_GIT="1", RELIC5_GIT_CACHE=str(cache))
    r = push(e)
    assert r.returncode == 0, r.stderr
    log = (hub / "relic5/parts/m5/git/github.com/acme/widget.log").read_text()
    h, author, _, name, _, subject, body = log.rstrip("\x1e\n").split("\x1f")
    assert len(h) == 40 and author == "2025-03-25T16:28:00+07:00" and name == "Nat" and subject == "Fix template paths"
    assert "Co-Authored-By: Claude" in body
    assert not list((hub / "relic5/parts/m5/git").rglob("*.refs")) and not (hub / "relic5/parts/m5/git/github.com/acme/empty.log").exists()
    assert "stream git" in r.stdout
    before = os.path.getmtime(cache / "github.com/acme/widget.log")
    os.utime(cache / ".stamp", (0, 0))   # due again, but the refs did not move
    assert push(e).returncode == 0
    assert os.path.getmtime(cache / "github.com/acme/widget.log") == before


def test_git_repo_paths_always_carry_the_host(env, tmp_path):
    """mba's ghq root is ~/Code/github.com: its repos still land as github.com/<org>/<repo>.log."""
    src, hub, e = env
    root, fb = tmp_path / "Code/github.com", tmp_path / "fakebin"
    repo = root / "acme/widget"
    repo.mkdir(parents=True)
    subprocess.run(["git", "-C", str(repo), "init", "-q"], check=True)
    subprocess.run(["git", "-C", str(repo), "-c", "user.name=N", "-c", "user.email=n@x", "commit", "-q", "--allow-empty", "-m", "x"], check=True)
    (fb / "ghq").write_text(f"#!/bin/sh\n[ \"$1\" = root ] && echo {root} && exit 0\necho {repo}\n")
    (fb / "ghq").chmod(0o755)
    r = push(dict(e, RELIC5_GIT="1", RELIC5_GIT_CACHE=str(tmp_path / "c")))
    assert r.returncode == 0, r.stderr
    assert (hub / "relic5/parts/m5/git/github.com/acme/widget.log").exists()


def test_an_unknown_machine_name_is_refused_unless_new_on_purpose(env, tmp_path):
    """2026-10-25: a push run by hand on the Air took its hostname and opened parts/nats-macbook-air beside mba."""
    src, hub, e = env
    e = {k: v for k, v in e.items() if k not in ("RELIC5_NEW_MACHINE", "RELIC5_MACHINE")}
    r = push(e)
    assert r.returncode == 2 and "has no machine" in r.stderr and not (hub / "relic5/parts").exists()
    name = tmp_path / "machine"
    name.write_text("mba\n")
    e["RELIC5_MACHINE_FILE"] = str(name)
    assert push(e).returncode == 2                      # the name file names it, but mba is new to this hub too
    assert push(e | {"RELIC5_NEW_MACHINE": "1"}).returncode == 0 and (hub / "relic5/parts/mba/text").is_dir()
    r = push(e)                                         # known now: pushes without the flag
    assert r.returncode == 0, r.stderr
