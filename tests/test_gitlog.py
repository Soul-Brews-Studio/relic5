"""gitlog.py: git commits as the "git" layer: parse, fold across machines and clones, role, index, search, show, status."""
import os

import duckdb

from relic5 import fts, gitlog
from relic5.parts import Parts
from relic5.query import Relic5
from relic5.status import status

H1, H2, H3 = "a" * 40, "b" * 40, "c" * 40
CLAUDE = "🤖 Generated with [Claude Code](https://claude.ai/code)\n\nCo-Authored-By: Claude <noreply@anthropic.com>"


def rec(h, when, subject, body="", name="Nat"):
    return "\x1f".join([h, when, when, name, "n@x", subject, body]) + "\x1e\n"


def put(root, machine, repo, *recs):
    p = os.path.join(root, "parts", machine, "git", repo + ".log")
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w") as f:
        f.write("".join(recs))


def test_parse_fold_role(tmp_path):
    root = str(tmp_path)
    first = rec(H1, "2025-03-25T16:28:00+07:00", "Fix template paths for ESPHome builds", CLAUDE)
    put(root, "m5", "github.com/laris-co/esphome-fw", first, rec(H2, "2025-04-02T09:00:00+07:00", "plain change"))
    put(root, "white", "github.com/laris-co/esphome-fw", first)                   # the same commit on two machines
    put(root, "white", "github.com/nazt/esphome-fw", first,                       # and in a fork
        rec(H3, "2025-05-01T10:00:00Z", "codex did it", "Co-authored-by: Codex <noreply@openai.com>"), "garbage\x1fonly\x1e")
    rows = gitlog.rows(root)
    assert [r["hash"] for r in rows] == [H1, H2, H3]
    one = rows[0]
    assert one["machines"] == ["m5", "white"] and one["repos"] == ["github.com/laris-co/esphome-fw", "github.com/nazt/esphome-fw"]
    assert one["role"] == "commit-claude" and one["ts"] == "2025-03-25T09:28:00.000Z" and one["month"] == "2025-03"
    assert one["sid"] == "git:github.com/laris-co/esphome-fw" and one["cat"] == "laris-co/esphome-fw" and one["engine"] == "git"
    assert one["text"].startswith("Fix template paths for ESPHome builds\n\n") and one["text"].endswith(f"laris-co/esphome-fw {H1[:12]} by Nat")
    assert [r["role"] for r in rows[1:]] == ["commit", "commit-codex"]


def test_indexed_searched_shown_counted(root, monkeypatch):
    monkeypatch.setenv("RELIC5_NOW", "2026-10-24T03:00:00Z")
    con = duckdb.connect()
    Parts(root).index(con, log=lambda s: None)
    fts.build(root, con, log=lambda s: None)
    assert fts.build(root, con, log=lambda s: None) == []                          # no logs pushed: no git table, no new generation
    put(root, "m5", "github.com/laris-co/esphome-fw", rec(H1, "2025-03-25T16:28:00+07:00", "Fix template paths for ESPHome builds", CLAUDE))
    assert fts.build(root, con, log=lambda s: None) == ["git_history"]
    assert fts.build(root, con, log=lambda s: None) == []                          # unchanged logs: nothing rebuilt
    r = Relic5(root, duckdb.connect())
    hits = r.search("ESPHome template", with_="git")["hits"]
    assert len(hits) == 1 and hits[0]["layer"] == "git" and hits[0]["role"] == "commit-claude"
    assert hits[0]["repo_key"] == "github.com/laris-co/esphome-fw" and hits[0]["partition"] == "2025-03"
    assert not [h for h in r.search("ESPHome")["hits"] if h["layer"] == "git"]     # talk and commits stay apart
    assert [h["layer"] for h in r.search("ESPHome", with_="all")["hits"]].count("git") == 1
    shown = r.show(hits[0]["link"])
    assert shown["layer"] == "git" and shown["target"]["hash"] == H1 and H1 in shown["notes"][0] and shown["before"] == []
    g = status(root)["git"]
    assert g["commits"] == 1 and g["claude"] == 1 and g["first_claude"] == "2025-03-25T16:28:00.000+07:00"
    assert g["months"] == {"2025-03": {"commits": 1, "claude": 1, "codex": 0}}


def test_our_orgs_whole_others_only_ours(tmp_path, monkeypatch):
    """With a git-own file: an org where we wrote >= 10% is kept whole (team included); elsewhere only our commits."""
    root = str(tmp_path)
    own = tmp_path / "git-own"
    own.write_text("# us\nn@x\n*@soulbrews.studio\n")
    monkeypatch.setenv("RELIC5_GIT_OWN", str(own))
    hx = lambda i: f"{i:040x}"
    team = [rec(hx(i), "2025-06-01T00:00:00Z", f"team {i}", name="Mate") for i in range(1, 9)]
    put(root, "m5", "github.com/laris-co/app", rec(hx(100), "2025-06-01T00:00:00Z", "ours"), *[t.replace("n@x", "mate@x") for t in team])
    oss = [rec(hx(200 + i), "2025-06-01T00:00:00Z", f"upstream {i}", CLAUDE).replace("n@x", f"dev{i}@x") for i in range(50)]
    put(root, "m5", "github.com/bigoss/lib", *oss, rec(hx(300), "2025-07-01T00:00:00Z", "my fix upstream").replace("n@x", "neo@soulbrews.studio"))
    rows = gitlog.rows(root)
    got = {r["title"]: r["ours"] for r in rows}
    assert got == {"ours": True, **{f"team {i}": False for i in range(1, 9)}, "my fix upstream": True}
    assert gitlog.sig(root)[-1] == ["git-own", "n@x", "*@soulbrews.studio"]   # a new identity rebuilds the table
