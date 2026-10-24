"""memory.py: Claude Code memory notes as the "memory" layer: parse, fold across machines, index, search, show,
status; and bin/relic5-push sending them."""
import os, subprocess

import duckdb

from relic5 import fts, memory
from relic5.parts import Parts
from relic5.query import Relic5
from relic5.status import status

NOTE = """---
name: tailscale-only-vpn
description: "tailscale is the only VPN; never NetBird or WireGuard"
metadata:
  type: feedback
  originSessionId: e6eaf465
  modified: 2026-10-24T02:05:56.583Z
---

Every box is reached over tailscale. **Why:** one tunnel, one ACL.
"""
PROJ = "-opt-Code-github-com-laris-co-neo-oracle"


def put(root, machine, name, text, project=PROJ, home="claude"):
    d = os.path.join(root, "parts", machine, "memory", home, project, "memory")
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, name), "w") as f:
        f.write(text)


def test_parse_and_fold(tmp_path):
    root = str(tmp_path)
    put(root, "m5", "feedback_vpn.md", NOTE)
    put(root, "white", "feedback_vpn.md", NOTE)                                    # the same note on two machines
    put(root, "white", "feedback_vpn.md", NOTE.replace("one ACL", "one key set"), project="-opt-Code-github-com-x-y")
    put(root, "m5", "MEMORY.md", "- [VPN](feedback_vpn.md)")                         # the folder's index: skipped
    put(root, "m5", "plain.md", "no frontmatter at all")
    rows = memory.rows(root)
    assert len(rows) == 3
    vpn = next(r for r in rows if r["cat"] == "laris-co-neo-oracle" and r["title"] == "tailscale-only-vpn")
    assert vpn["machines"] == ["m5", "white"] and vpn["role"] == "memory-feedback" and vpn["ts"] == "2026-10-24T02:05:56.000Z"
    assert vpn["text"].startswith("tailscale-only-vpn: tailscale is the only VPN") and "**Why:**" in vpn["text"]
    assert next(r for r in rows if r["title"] == "plain")["role"] == "memory-note"


def test_indexed_searched_shown_counted(root, monkeypatch):
    monkeypatch.setenv("RELIC5_NOW", "2026-10-24T03:00:00Z")
    put(root, "m5", "feedback_vpn.md", NOTE)
    con = duckdb.connect()
    Parts(root).index(con, log=lambda s: None)
    assert "memory_history" in fts.build(root, con, log=lambda s: None)
    assert fts.build(root, con, log=lambda s: None) == []                          # unchanged notes: nothing rebuilt
    r = Relic5(root, duckdb.connect())
    hits = r.search("NetBird", with_="memory")["hits"]
    assert len(hits) == 1 and hits[0]["layer"] == "memory" and hits[0]["role"] == "memory-feedback"
    assert not [h for h in r.search("NetBird")["hits"] if h["layer"] == "memory"]   # talk and memory stay apart
    assert r.search("NetBird", with_="memory", role="memory-project")["hits"] == []
    shown = r.show(hits[0]["link"])
    assert shown["layer"] == "memory" and "tailscale" in shown["target"]["text"] and shown["before"] == []
    assert status(root)["memory"] == {"feedback": 1}
    put(root, "m5", "project_x.md", NOTE.replace("type: feedback", "type: project"))
    assert fts.build(root, duckdb.connect(), log=lambda s: None) == ["memory_history"]


def test_push_sends_memory_notes(tmp_path):
    from test_push import FAKE_SSH, REPO
    home, hub, src, fb = (tmp_path / d for d in ("home", "hub", "extract", "fb"))
    for d in (home / ".claude/projects/p1/memory", home / ".claude/projects/p2", home / ".claude-neo/projects/p3/memory",
              hub, src / "text", fb):
        d.mkdir(parents=True)
    (home / ".claude/projects/p1/memory/feedback_a.md").write_text(NOTE)
    (home / ".claude/projects/p1/memory/MEMORY.md").write_text("- [a](feedback_a.md)")
    (home / ".claude/projects/p2/session.jsonl").write_text("{}")                # transcripts are not memory
    (home / ".claude-neo/projects/p3/memory/user_b.md").write_text(NOTE)
    (fb / "ssh").write_text(FAKE_SSH)
    (fb / "ssh").chmod(0o755)
    e = dict(os.environ, PATH=f"{fb}:{os.environ['PATH']}", FAKE_HUB_HOME=str(hub), RELIC5_SRC=str(src), HOME=str(home),
             RELIC5_HUB="hub", RELIC5_MACHINE="m5", RELIC5_SCAN=str(tmp_path / "noscan"))
    r = subprocess.run([os.path.join(REPO, "bin/relic5-push")], env=e, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    base = hub / "relic5/parts/m5/memory"
    assert (base / "claude/p1/memory/feedback_a.md").read_text() == NOTE
    assert (base / "claude-neo/p3/memory/user_b.md").exists()
    assert not (base / "claude/p2").exists()
    assert "stream memory:claude" in r.stdout
