"""config.py: the config layer (issue #269): CLAUDE.md / AGENTS.md / SKILL.md as searchable sections, the fold, the
history of a rule's wording, and the secret gates (names, content, the push's own copy of the check)."""
import json, os, subprocess

import duckdb

from relic5 import config, fts
from relic5.parts import Parts
from relic5.query import Relic5
from relic5.status import status

TREE = """# ghq-tree Fleet Rules

This file sits above every org/repo in the ghq tree — it loads for ANY session
working anywhere under github.com/, regardless of org.

## Search discipline — rg only, NEVER filesystem sweeps (Nat, 2026-07-09)

- **NEVER** run `grep -r`, `find`, or `bfs` starting at `/`, `~`, or the ghq root wholesale

```bash
## not a heading: inside a fence
rg PATTERN <dir>
```

## Browser automation — ego-browser only (Nat, 2026-08-07)

**Use `/ego-browser`** for every browser task.
"""
GLOBAL = """# Global rules — every session on this account

## Never publish to claude.ai — always deliver locally (Nat, 2026-09-05)

Do not use the Artifact tool (claude.ai/code/artifact).

## Tailscale is the only VPN — no NetBird, no WireGuard, no black (Nat, 2026-10-22)

The fleet has exactly one overlay network: **tailscale**.
"""
SKILL = """---
name: ego-browser
description: When you need a browser, read this Skill by default.
---

# ego-browser

Before any browser task, run `ego-browser skill`.
"""
TOKEN = "Zk3Qp9Lw2Xc7Vb4Nm8Rt5Yh1Ju6Ik0Ol3pQ"            # a made-up secret, the shape of a real one
WGKEY = "aB3dE5fG7hJ9kL1mN3pQ5rS7tU9vW1xY3zA5bC7dE9f="


def put(root, machine, user, rel, text, listed=True):
    p = os.path.join(root, "parts", machine, "config", user, rel)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w") as f:
        f.write(text)
    if listed:
        lp = os.path.join(root, "parts", machine, "config", user, "_files.json")
        have = json.load(open(lp))["files"] if os.path.exists(lp) else []
        json.dump({"files": sorted(set(have) | {rel})}, open(lp, "w"))


def test_push_refusals_reach_status(root):
    """A file relic5-push refused never reaches the hub; its _files.json says so, and status names it."""
    put(root, "m5", "beta", "ghq/github.com/CLAUDE.md", TREE)
    lp = os.path.join(root, "parts", "m5", "config", "beta", "_files.json")
    json.dump({"files": ["ghq/github.com/CLAUDE.md"], "refused": [{"rel": "ghq/github.com/s/codexbar/AGENTS.md", "why": "high-entropy line 41"}]}, open(lp, "w"))
    config.build(root)
    assert config.refused(root) == [{"machine": "m5", "user": "beta", "rel": "ghq/github.com/s/codexbar/AGENTS.md", "why": "high-entropy line 41 (at push)"}]
    assert config.counts(root)["refused"] == 1


def unlist(root, machine, user, rel):
    lp = os.path.join(root, "parts", machine, "config", user, "_files.json")
    json.dump({"files": [f for f in json.load(open(lp))["files"] if f != rel]}, open(lp, "w"))


def test_sections_split_on_level_two_headings_not_inside_fences():
    secs = config.sections(TREE)
    assert [s["title"] for s in secs] == ["ghq-tree Fleet Rules", "Search discipline — rg only, NEVER filesystem sweeps (Nat, 2026-07-09)",
                                         "Browser automation — ego-browser only (Nat, 2026-08-07)"]
    assert [s["date"] for s in secs] == [None, "2026-07-09", "2026-08-07"]
    assert "## not a heading" in secs[1]["body"]
    sk = config.sections(SKILL)
    assert sk[0]["title"] == "ego-browser" and sk[0]["body"].startswith("When you need a browser")


def test_fold_scope_and_roles(tmp_path):
    root = str(tmp_path)
    put(root, "m5", "beta", "ghq/github.com/CLAUDE.md", TREE)
    put(root, "white", "nat", "ghq/github.com/CLAUDE.md", TREE)                # the same tree file on two machines
    put(root, "m5", "beta", "home/claude/CLAUDE.md", GLOBAL)
    put(root, "white", "nat", "home/claude/CLAUDE.md", GLOBAL)                 # same text, another account: its own scope
    put(root, "m5", "beta", "ghq/github.com/x/y/AGENTS.md", "# y\n\nrun just test")
    put(root, "m5", "beta", "home/claude/plugins/cache/mk/caveman/17f9f2ec2377/skills/c/SKILL.md", SKILL)
    put(root, "m5", "beta", "home/claude/plugins/cache/mk/caveman/2a1b3c4d5e6f/skills/c/SKILL.md", SKILL)   # two versions, one text
    put(root, "m5", "beta", "home/claude/settings.json", '{"token": "' + TOKEN + '"}')                      # gate 1: never read
    rows, refused = config.rows(root)
    tree = [r for r in rows if r["scope"] == "ghq/github.com/CLAUDE.md"]
    assert len(tree) == 3 and tree[0]["machines"] == ["m5", "white"] and tree[0]["accounts"] == ["beta@m5", "nat@white"]
    assert tree[0]["cat"] == "github.com" and tree[0]["role"] == "config-claudemd" and tree[0]["title"] == "ghq-tree Fleet Rules"
    assert tree[1]["ts"] == "2026-07-08T17:00:00.000Z" and tree[1]["text"].startswith("ghq-tree Fleet Rules › Search discipline")
    glob = [r for r in rows if r["file"] == "CLAUDE.md" and r["scope"].endswith("home/claude/CLAUDE.md")]
    assert sorted({r["scope"] for r in glob}) == ["beta:home/claude/CLAUDE.md", "nat:home/claude/CLAUDE.md"]
    assert {r["cat"] for r in glob} == {"~beta/.claude", "~nat/.claude"}
    assert next(r for r in rows if r["file"] == "AGENTS.md")["role"] == "config-agentsmd"
    skills = [r for r in rows if r["role"] == "config-skill"]
    assert len(skills) == 1 and len(skills[0]["paths"]) == 2 and skills[0]["cat"] == "plugin:caveman:c"
    assert not [r for r in rows if TOKEN in r["text"]] and refused == []


def test_ghq_tree_rules_are_searchable_with_config(root, monkeypatch):
    """Acceptance 1: relic_search {query: "ghq-tree Fleet Rules", with: "config"} returns the org CLAUDE.md."""
    monkeypatch.setenv("RELIC5_NOW", "2026-10-29T05:00:00Z")
    put(root, "m5", "beta", "ghq/github.com/CLAUDE.md", TREE)
    put(root, "m5", "beta", "home/claude/CLAUDE.md", GLOBAL)
    con = duckdb.connect()
    Parts(root).index(con, log=lambda s: None)
    assert "config_history" in fts.build(root, con, log=lambda s: None)
    assert fts.build(root, con, log=lambda s: None) == []                       # unchanged: nothing rebuilt
    r = Relic5(root, duckdb.connect())
    hits = r.search('"ghq-tree Fleet Rules"', with_="config")["hits"]
    assert hits and hits[0]["layer"] == "config" and hits[0]["session_uuid"] == "config:ghq/github.com/CLAUDE.md" and hits[0]["role"] == "config-claudemd"
    hits = r.search("Never publish to claude.ai", with_="config")["hits"]
    assert hits[0]["title"].startswith("Never publish to claude.ai") and hits[0]["ts"] == "2026-09-04T17:00:00.000Z"
    assert not [h for h in r.search("Fleet Rules")["hits"] if h["layer"] == "config"]   # talk and config stay apart
    assert [h for h in r.search("Fleet Rules", with_="all")["hits"] if h["layer"] == "config"]
    shown = r.show(hits[0]["link"])
    assert shown["layer"] == "config" and "Artifact tool" in shown["target"]["text"] and "current" in shown["notes"][0]
    assert status(root)["config"] == {"claudemd": 6}


def test_secrets_are_refused_and_never_reach_the_index(root, monkeypatch):
    """Acceptance 2: a settings.json holding a token and a .conf holding a PrivateKey are skipped (gate 1), a CLAUDE.md
    carrying either is refused whole (gate 2), and neither string is anywhere in the built index."""
    monkeypatch.setenv("RELIC5_NOW", "2026-10-29T05:00:00Z")
    put(root, "m5", "beta", "home/claude/settings.json", '{"env": {"API_TOKEN": "' + TOKEN + '"}}')
    put(root, "m5", "beta", "ghq/github.com/o/mycelium-oracle/ψ/active/wg0.conf", f"[Interface]\nPrivateKey = {WGKEY}\n")
    put(root, "m5", "beta", "ghq/github.com/o/r/.envrc", f"export TOKEN={TOKEN}\n")
    put(root, "m5", "beta", "ghq/github.com/o/leaky/CLAUDE.md", TREE + f"\n## peers\n\n[Peer]\nPrivateKey = {WGKEY}\n")
    put(root, "m5", "beta", "ghq/github.com/o/leaky2/CLAUDE.md", TREE + f"\nuse token: {TOKEN}\n")
    put(root, "m5", "beta", "ghq/github.com/CLAUDE.md", TREE)
    con = duckdb.connect()
    Parts(root).index(con, log=lambda s: None)
    fts.build(root, con, log=lambda s: None)
    ref = config.refused(root)
    assert sorted((r["rel"], r["why"]) for r in ref) == [("ghq/github.com/o/leaky/CLAUDE.md", "wireguard-key line 22"),
                                                       ("ghq/github.com/o/leaky2/CLAUDE.md", "secret-assigned line 19")]
    assert status(root)["config"]["refused"] == 2
    st = status(root)
    assert [r["rel"] for r in st["config_refused"]] == ["ghq/github.com/o/leaky/CLAUDE.md", "ghq/github.com/o/leaky2/CLAUDE.md"]
    assert any(w.startswith("config: 2 file(s) refused") and "wireguard-key line 22" in w for w in st["warnings"])
    for d, _, fs in os.walk(os.path.join(root, "index")):
        for f in fs:
            blob = open(os.path.join(d, f), "rb").read()
            assert TOKEN.encode() not in blob and WGKEY.encode() not in blob, os.path.join(d, f)
    r = Relic5(root, duckdb.connect())
    assert r.search("Fleet Rules", with_="config")["hits"]                        # the clean file is still there
    assert not [h for h in r.search("Fleet Rules", with_="config")["hits"] if "leaky" in (h.get("session_uuid") or "")]


def test_key_shaped_named_rules_and_false_alarms():
    hit = {"PrivateKey = " + WGKEY: "wireguard-key", "-----BEGIN OPENSSH PRIVATE KEY-----": "private-key-block",
           "ghp_" + "a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6q7R8": "github-token", "sk-ant-" + "a" * 30: "api-key",
           f'token: "{TOKEN}"': "secret-assigned", f"secret {TOKEN}": "high-entropy",
           "Authorization: Bearer " + TOKEN: "bearer"}
    for text, rule in hit.items():
        assert (config.key_shaped(text) or "").startswith(rule), text
    for text in ("apiKey: process.env.OPENAI_API_KEY_SECRET", "NODE_OPTIONS=--max-old-space-size=4096",
                 "https://www.facebook.com/x/posts/pfbid0aBcD3EfGh5IjKl7MnOp9QrSt1UvWx3YzAb5CdEf7GhIj9",
                 "commit 3f786850e387550fdab836ed7e6dc881de23001b", "session 50cb5858-2e10-447f-8aa7-d6c0420d6ddd",
                 "\\cite{PLACEHOLDER_NOT_VERIFIED_2024}", "same token = non-deterministic routing",
                 "/opt/Code/github.com/Soul-Brews-Studio/relic5/wt/rule-chains-relic5-29oct-thu2026"):
        assert config.key_shaped(text) is None, text


def test_push_carries_the_same_check():
    """bin/relic5-push refuses before anything leaves the machine, with a verbatim copy of key_shaped."""
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    mark = lambda s: s[s.index("# KEY_SHAPED begin\n"):s.index("# KEY_SHAPED end\n")]
    assert mark(open(os.path.join(here, "bin/relic5-push")).read()) == mark(open(os.path.join(here, "src/relic5/config.py")).read())


def test_history_keeps_every_wording(root, monkeypatch):
    """An edited rule is a new row; the old wording stays (current = false, last_seen); a file its account's push no
    longer lists stays only as history."""
    from datetime import datetime, timezone
    import pyarrow.parquet as pq
    put(root, "m5", "beta", "home/claude/CLAUDE.md", GLOBAL)
    put(root, "m5", "beta", "ghq/github.com/x/y/CLAUDE.md", "# y\n\nuse black.local")
    config.build(root, now=datetime(2026, 10, 22, tzinfo=timezone.utc))
    put(root, "m5", "beta", "home/claude/CLAUDE.md", GLOBAL.replace("exactly one overlay network", "one overlay network only"))
    unlist(root, "m5", "beta", "ghq/github.com/x/y/CLAUDE.md")
    p = config.build(root, now=datetime(2026, 10, 29, tzinfo=timezone.utc))
    rows = pq.read_table(p).to_pylist()
    vpn = sorted((r for r in rows if r["title"].startswith("Tailscale")), key=lambda r: r["first_seen"])
    assert [(r["current"], r["first_seen"][:10], r["last_seen"][:10]) for r in vpn] == [(False, "2026-10-22", "2026-10-22"),
                                                                                          (True, "2026-10-29", "2026-10-29")]
    unchanged = next(r for r in rows if r["title"].startswith("Never publish") and r["current"])
    assert unchanged["first_seen"][:10] == "2026-10-22"                         # the same text keeps its first sighting
    assert [r["current"] for r in rows if r["cat"] == "x/y"] == [False]
    assert config.counts(root) == {"claudemd": 3}


def test_push_sends_config_and_refuses_secrets(tmp_path):
    from test_push import FAKE_SSH, REPO
    home, hub, src, fb, groot = (tmp_path / d for d in ("home", "hub", "extract", "fb", "ghq"))
    for d in (home / ".claude/skills/ego", home / ".claude/plugins/cache/mk/p/1.0.0/skills/s", hub, src / "text", fb,
              groot / "github.com/org/repo/docs"):
        d.mkdir(parents=True)
    (home / ".claude/CLAUDE.md").write_text(GLOBAL)
    (home / ".claude/settings.json").write_text('{"token": "' + TOKEN + '"}')
    (home / ".claude/skills/ego/SKILL.md").write_text(SKILL)
    (home / ".claude/plugins/cache/mk/p/1.0.0/skills/s/SKILL.md").write_text(SKILL)
    (groot / "github.com/CLAUDE.md").write_text(TREE)
    repo = groot / "github.com/org/repo"
    (repo / "CLAUDE.md").write_text("# repo\n\nrules")
    (repo / "docs/AGENTS.md").write_text("# docs\n\nmore rules")
    (repo / ".envrc").write_text(f"export TOKEN={TOKEN}\n")
    (repo / "leak").mkdir()
    (repo / "leak/CLAUDE.md").write_text(f"[Peer]\nPrivateKey = {WGKEY}\n")
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    (fb / "ssh").write_text(FAKE_SSH)
    (fb / "ssh").chmod(0o755)
    (fb / "ghq").write_text(f"#!/bin/sh\ncase \"$1\" in root) echo {groot};; list) echo github.com/org/repo;; esac\n")
    (fb / "ghq").chmod(0o755)
    e = dict(os.environ, PATH=f"{fb}:{os.environ['PATH']}", FAKE_HUB_HOME=str(hub), RELIC5_SRC=str(src), HOME=str(home),
             RELIC5_HUB="hub", RELIC5_MACHINE="m5", RELIC5_NEW_MACHINE="1", RELIC5_SCAN=str(tmp_path / "noscan"), RELIC5_GIT="0")
    r = subprocess.run([os.path.join(REPO, "bin/relic5-push")], env=e, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    user = subprocess.run(["id", "-un"], capture_output=True, text=True).stdout.strip().lower()
    base = hub / "relic5/parts/m5/config" / user
    sent = json.loads((base / "_files.json").read_text())
    assert sent["files"] == ["ghq/github.com/CLAUDE.md", "ghq/github.com/org/repo/CLAUDE.md", "ghq/github.com/org/repo/docs/AGENTS.md",
                             "home/claude/CLAUDE.md", "home/claude/plugins/cache/mk/p/1.0.0/skills/s/SKILL.md",
                             "home/claude/skills/ego/SKILL.md"]
    assert sent["refused"] == [{"rel": "ghq/github.com/org/repo/leak/CLAUDE.md", "why": "wireguard-key line 2"}]
    assert (base / "ghq/github.com/CLAUDE.md").read_text() == TREE
    for d, _, fs in os.walk(hub):
        for f in fs:
            blob = open(os.path.join(d, f), "rb").read()
            assert TOKEN.encode() not in blob and WGKEY.encode() not in blob, os.path.join(d, f)
    assert f"stream config:{user}" in r.stdout and "config refused ghq/github.com/org/repo/leak/CLAUDE.md" in r.stderr
