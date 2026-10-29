"""rules.py: relic_rule over the memory, config and trace data relic5 already holds (issue #269 acceptance 3-7).

The fixtures are the real notes of the tailscale rule (names, repos and dates as relic5 holds them on 2026-10-29,
texts cut to the sentences that matter), so a later edit of a live note cannot break the test. The live check is
bin/relic5-rule-check."""
import hashlib, json, os

from relic5 import config, memory, rules

from test_config import GLOBAL, TREE, put as put_config

FORBIDS = ["netbird", "wireguard", "wg0", "black.local", "192.168.", "10.10.0."]


def note(root, repo, name, ts, body, typ="feedback", machine="m5", origin=None, project=None):
    project = project or "-opt-Code-github-com-" + repo.replace("/", "-")
    d = os.path.join(root, "parts", machine, "memory", "claude", project, "memory")
    os.makedirs(d, exist_ok=True)
    o = f"\n  originSessionId: {origin}" if origin else ""
    with open(os.path.join(d, name + ".md"), "w") as f:
        f.write(f"---\nname: {name}\ndescription: \"{body.splitlines()[0]}\"\nmetadata:\n  type: {typ}{o}\n  modified: {ts}\n---\n\n{body}\n")


EIGHT = [   # the #269 table: date, repo, note
    ("2026-04-02T03:00:00Z", "laris-co/homelab", "tailscale-ips-not-wireguard", "Use Tailscale IPs, not WireGuard 10.10.0.x."),
    ("2026-09-17T03:00:00Z", "dryoungdo-wellness-clinic/mycelium-oracle", "no-more-black", "No more black: now we are in tailscale vpn."),
    ("2026-09-26T03:00:00Z", "laris-co/sandbox", "netbird-deprecated", "NetBird is deprecated; reach every box over tailscale."),
    ("2026-10-05T03:00:00Z", "Soul-Brews-Studio/kvmbox-oracle", "netbird-retired-tailscale-only",
     "Nat: \"we dont use netbird anymore we go tailscale\". Tailscale only."),
    ("2026-10-21T03:00:00Z", "laris-co/laris-meshtastic", "serve-on-tailscale-not-netbird", "Serve on tailscale, not netbird."),
    ("2026-10-22T03:00:00Z", "dryoungdo-wellness-clinic/mycelium-oracle", "no-more-black-or-wireguard",
     "No more black, no WireGuard: tailscale only."),
    ("2026-10-23T03:00:00Z", "laris-co/nexus-oracle", "network-tailscale-only", "Fleet networking is Tailscale only (no WireGuard, no NetBird)."),
    ("2026-10-23T04:00:00Z", "laris-co/neo-oracle", "feedback-fleet-network-tailscale", "The fleet network is tailscale; never NetBird."),
    ("2026-10-24T02:14:52Z", "laris-co/neo-oracle", "tailscale-only-vpn",
     "Tailscale is the only VPN. Older memories that name NetBird routes describe history, not current routes."),
]
SERVE = """relic serve + relic-ui run under pm2 as nat@white.local on LAN, because m5 and white are on DIFFERENT NetBird networks

**m5 and white are on two different NetBird networks** (m5 profile commu, white profile default).
m5 reaches white **only over LAN `192.168.1.179`** — both overlays are unroutable from m5.

**Superseded 2026-10-24:** NetBird is retired; tailscale is the only VPN ([[tailscale-only-vpn]]). Keep this as history; route via the tailnet."""
ATS = """iOS ATS blocks plain HTTP to a NetBird 100.x IP even with NSAllowsLocalNetworking

An app pairing over plain HTTP with a server on the Mac's NetBird address `100.111.101.21` failed before any byte left the device.

**Superseded 2026-10-24:** NetBird is retired; tailscale is the only VPN. The ATS finding still holds for ANY 100.x address."""


def fleet(root):
    for ts, repo, name, body in EIGHT:
        note(root, repo, name, ts, body, origin="e6eaf465" if name == "tailscale-only-vpn" else None)
    note(root, "laris-co/neo-oracle", "white-relic-serve-and-mesh", "2026-10-24T02:06:01Z", SERVE, typ="reference")
    note(root, "laris-co/neo-oracle", "ats-netbird-ip-literal", "2026-10-07T20:15:35Z", ATS, typ="reference")
    # acceptance 7, the false positive: a fact ABOUT the retired thing, after its retirement
    note(root, "laris-co/neo-oracle", "oracle-netbird-gone", "2026-10-25T01:00:00Z",
         "`*.oracle.netbird` no longer resolves; it was the old mesh name.", typ="reference")
    # written while NetBird was still the mesh (before 2026-09-26): history, not a contradiction
    note(root, "nat-build-with-oracle/4sep-fri2026-oracle", "netbird-urls-not-localhost", "2026-09-03T07:45:13Z",
         "Hand back netbird URLs (http://m5.oracle.netbird:PORT) for anything served here.")
    # a live contradiction nobody marked: after the rule, names the retired route as the way in
    note(root, "laris-co/ops-oracle", "white-over-lan", "2026-10-26T01:00:00Z", "Reach white over 192.168.1.179:8795 for the hub.", typ="project")
    # repo config files, so the project folders above resolve to their repos (the config layer knows those dirs)
    for repo in ("laris-co/homelab", "dryoungdo-wellness-clinic/mycelium-oracle", "laris-co/sandbox", "Soul-Brews-Studio/kvmbox-oracle",
                 "laris-co/laris-meshtastic", "laris-co/nexus-oracle", "laris-co/neo-oracle", "laris-co/ops-oracle"):
        put_config(root, "m5", "beta", f"ghq/github.com/{repo}/CLAUDE.md", f"# {repo}\n\nrepo rules")
    put_config(root, "m5", "beta", "ghq/github.com/CLAUDE.md", TREE)
    put_config(root, "m5", "beta", "home/claude/CLAUDE.md", GLOBAL)          # the 2026-10-22 global entry
    memory.build(root)
    config.build(root)
    commit(root, "github.com/Soul-Brews-Studio/oracle-app-kit", "fc416ce", "2026-10-08T03:00:00Z", "pairing: HTTP + JSON server",
           "The Mac app serves the pairing API over HTTP + JSON on 127.0.0.1 and its NetBird address only.")
    commit(root, "github.com/laris-co/homelab", "1a2b3c4", "2026-08-01T03:00:00Z", "mesh: peers",
           "Peers reach each other over NetBird; m5 at m5.oracle.netbird.")        # before NetBird was retired: history


def commit(root, repo, h, ts, title, body):
    """One row of gitlog.py's table (index/_git/commits.parquet), appended."""
    import pyarrow as pa, pyarrow.parquet as pq
    p = os.path.join(root, "index", "_git", "commits.parquet")
    os.makedirs(os.path.dirname(p), exist_ok=True)
    rows = pq.read_table(p).to_pylist() if os.path.exists(p) else []
    rows.append({"msgkey": hashlib.md5(h.encode()).hexdigest(), "month": ts[:7], "ts": ts, "repo": repo, "hash": h,
                 "title": title, "text": f"{title}\n\n{body}", "role": "commit-claude"})
    pq.write_table(pa.Table.from_pylist(rows), p)


def queries(root, rows):
    os.makedirs(os.path.join(root, "logs"), exist_ok=True)
    with open(os.path.join(root, "logs", "queries.jsonl"), "a") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")


def link_of(root, name):
    import pyarrow.parquet as pq
    r = next(r for r in pq.read_table(os.path.join(root, "index/_memory/notes.parquet")).to_pylist() if r["title"] == name)
    return f"relic5://{r['month']}/{r['msgkey']}"


def test_restatement_timeline_in_date_order(tmp_path):
    """Acceptance 3: the restatements come back in date order with repo and note name, and the global CLAUDE.md entry
    dated 2026-10-22. They are candidates (unbound) until #270 binds them: the count sits next to the triple."""
    root = str(tmp_path)
    fleet(root)
    r = rules.rule(root, "tailscale only", forbids=FORBIDS)
    got = [(x["ts"][:10], x["repo"], x["name"]) for x in r["restatements"]]
    assert got == [(ts[:10], repo.replace("/", "-"), name) for ts, repo, name, _ in EIGHT]
    assert r["triple"]["reissued"] == 0 and r["triple"]["candidates"] == 9
    g = r["reachability"]["global"]
    assert g == [{"scope": "beta:home/claude/CLAUDE.md", "since": "dated 2026-10-22 by its heading", "basis": "heading date"}]
    assert "white-relic-serve-and-mesh" not in [x["name"] for x in r["restatements"]]   # it contradicts, it does not restate


def test_reachability_is_computed_over_the_real_parent_chain(tmp_path):
    """Acceptance 4: before 2026-10-22 no loading CLAUDE.md carried the rule; from then on the global one does, and the
    answer says it rests on the heading's date. The chain is walked from the cwd: a worktree reaches its repo's file."""
    root = str(tmp_path)
    fleet(root)
    note(root, "laris-co/neo-oracle", "wt-restatement", "2026-10-25T00:00:00Z", "Tailscale only, again.",
         project="-opt-Code-github-com-laris-co-neo-oracle-wt-proof-book-neo-28oct")
    put_config(root, "m5", "beta", "ghq/github.com/laris-co/neo-oracle/CLAUDE.md", "# neo\n\n## Network (Nat, 2026-10-24)\n\nTailscale is the only VPN.")
    memory.build(root)
    config.build(root)
    r = rules.rule(root, "tailscale only", forbids=FORBIDS)
    by = {x["name"]: x for x in r["restatements"]}
    assert by["tailscale-ips-not-wireguard"]["reachable_then"] is False and by["tailscale-ips-not-wireguard"]["cwd"] == "github.com/laris-co/homelab"
    assert by["network-tailscale-only"]["carried_then"] == ["beta:home/claude/CLAUDE.md"]
    wt = by["wt-restatement"]
    assert wt["cwd"] == "github.com/laris-co/neo-oracle"
    assert wt["loading"] == ["beta:home/claude/CLAUDE.md", "ghq/github.com/CLAUDE.md", "ghq/github.com/laris-co/neo-oracle/CLAUDE.md"]
    assert wt["carried_by"] == ["beta:home/claude/CLAUDE.md", "ghq/github.com/laris-co/neo-oracle/CLAUDE.md"]
    assert sorted(r["reachability"]["carried_now"]) == ["beta:home/claude/CLAUDE.md", "ghq/github.com/laris-co/neo-oracle/CLAUDE.md"]
    neo = next(c for c in r["config"] if c["scope"] == "ghq/github.com/laris-co/neo-oracle/CLAUDE.md")
    assert neo["since"] == "dated 2026-10-24 by its heading"


def test_contradictions_are_flagged_with_reasons_and_nothing_is_edited(tmp_path):
    """Acceptance 5 + 7: the two neo-oracle notes are flagged against the rule with their dates and a reason; both
    already carry "Superseded 2026-10-24", so they are acknowledged, not live. The unmarked one is live. A fact about
    the retired thing is not flagged, nor a note written before NetBird was retired. No file changes."""
    root = str(tmp_path)
    fleet(root)
    before = {os.path.join(d, f): hashlib.md5(open(os.path.join(d, f), "rb").read()).hexdigest()
              for d, _, fs in os.walk(os.path.join(root, "parts")) for f in fs}
    r = rules.rule(root, "tailscale only", forbids=FORBIDS)
    fl = {x["name"]: x for x in r["contradictions"]}
    assert set(fl) == {"white-relic-serve-and-mesh", "ats-netbird-ip-literal", "white-over-lan", "fc416ce pairing: HTTP + JSON server"}
    serve, ats, lan = fl["white-relic-serve-and-mesh"], fl["ats-netbird-ip-literal"], fl["white-over-lan"]
    assert serve["ts"][:10] == "2026-10-24" and any("192.168.1.179" in x["sentence"] for x in serve["sentences"])
    assert ats["ts"][:10] == "2026-10-07" and ats["term"] == "netbird" and ats["cue"] == "an IP address"
    assert serve["acknowledged"] == "marked superseded 2026-10-24" and ats["acknowledged"] == "marked superseded 2026-10-24"
    assert lan["acknowledged"] is None and "with no retirement word" in lan["reason"]
    assert all(x["reason"] for x in r["contradictions"])
    assert "oracle-netbird-gone" not in fl and "netbird-urls-not-localhost" not in fl
    assert r["retired"]["netbird"][:10] == "2026-09-26" and r["retired"]["192.168."] is None
    app = fl["fc416ce pairing: HTTP + JSON server"]
    assert app["kind"] == "commit" and app["repo"] == "github.com/Soul-Brews-Studio/oracle-app-kit" and app["acknowledged"] is None
    assert app["ts"][:10] == "2026-10-08" and "NetBird address only" in app["sentence"]   # the one real positive (nexus, 2026-10-29)
    assert r["retired_by"]["netbird"] == "memory laris-co-sandbox/netbird-deprecated"
    assert r["triple"]["contradicted"] == 2 and r["triple"]["flagged"] == 4
    after = {p: hashlib.md5(open(p, "rb").read()).hexdigest() for p in before}
    assert after == before


def test_the_triple_counts_digs_from_recorded_chains(tmp_path):
    """Acceptance 6: dug-for comes from the stored search chains: c15b98d7c4 (2026-10-29, 9 searches and a found note)
    is one, and a chain that never touched the rule is not."""
    root = str(tmp_path)
    fleet(root)
    vpn = link_of(root, "tailscale-only-vpn")
    queries(root, [
        {"id": "c15b98d7c4", "root": "c15b98d7c4", "parent": None, "at": "2026-10-29T03:10:00Z", "tool": "relic_search",
         "query": "netbird retired", "args": {}, "hits": 10, "top": [{"link": vpn}], "client": "claude"},
        {"id": "af14bff20e", "root": "c15b98d7c4", "parent": "c15b98d7c4", "at": "2026-10-29T03:40:00Z", "tool": "relic_found",
         "query": "how often was the tailscale rule restated", "args": {"goal": "how often was the tailscale rule restated",
         "how": "9 searches", "found": "eight restatements", "links": [vpn]}, "client": "claude"},
        {"id": "aaaaaaaaaa", "root": "aaaaaaaaaa", "parent": None, "at": "2026-10-29T04:00:00Z", "tool": "relic_search",
         "query": "gb300 power cap", "args": {}, "hits": 3, "top": [], "client": "claude"},
    ])
    r = rules.rule(root, "tailscale only", forbids=FORBIDS)
    assert [d["root"] for d in r["digs"]] == ["c15b98d7c4"] and r["digs"][0]["found"]
    assert {k: r["triple"][k] for k in ("reissued", "candidates", "dug", "contradicted", "flagged")} == \
        {"reissued": 0, "candidates": 9, "dug": 1, "contradicted": 2, "flagged": 4}
    assert r["triple"]["live_by"] == {"memory": 1, "config": 0, "commit": 1}
    assert r["line"].startswith("re-issued 0 bound · candidates 9 · dug for 1 · contradicted 2 live (4 flagged) of ")
    assert "1 of 2 commits" in r["line"] and "retirement dates: 0 given (none), 6 derived" in r["line"]
    given = rules.rule(root, "tailscale only", forbids=FORBIDS, retired_at={"netbird": "2026-10-22"})
    assert given["retired"]["netbird"] == "2026-10-22" and given["retired_by"]["netbird"] == "given"
    assert "retirement dates: 1 given (netbird), 5 derived" in given["line"]
    assert "ats-netbird-ip-literal" not in [x["name"] for x in given["contradictions"]]   # 10-07: before the given date
    other = rules.rule(root, "gb300 power cap")
    assert other["triple"]["dug"] == 1 and other["triple"]["contradicted"] is None   # no forbids: K is not computed


def test_enforcement_flags_come_first_with_their_account(tmp_path):
    """A global CLAUDE.md that still names the retired route loads into every session: it leads the list, labeled with
    the account and home it lives in (nexus, 2026-10-29: nat@white's host table)."""
    root = str(tmp_path)
    fleet(root)
    put_config(root, "white", "nat", "home/claude/CLAUDE.md", "# nat\n\n## Fleet — SSH Hosts\n\n| mba | 192.168.1.187 | mba.local | LAN |\n")
    put_config(root, "white", "nat", "home/claude/skills/hey/SKILL.md", "# hey\n\n## Fleet machine names\n\n| mba | mba.wg / 10.20.0.3 | WireGuard |\n")
    config.build(root)
    r = rules.rule(root, "tailscale only", forbids=FORBIDS + ["10.20.0."], retired_at={"10.20.0.": "2026-10-22"})
    top = r["contradictions"][:2]
    assert [x["loads"] for x in top] == ["loads into every session of nat@white", "a skill of nat@white"]
    assert top[0]["where"] == ["nat@white:~/.claude/CLAUDE.md"] and top[1]["where"] == ["nat@white:~/.claude/skills/hey/SKILL.md"]
    assert r["triple"]["live_by"]["config"] == 2 and r["contradictions"][-1]["kind"] == "commit"


def test_cwd_of_needs_a_known_directory():
    dirs = {"github.com/laris-co/neo-oracle", "github.com/laris-co/neo", "github.com", ""}
    assert rules.cwd_of("-opt-Code-github-com-laris-co-neo-oracle", dirs) == "github.com/laris-co/neo-oracle"
    assert rules.cwd_of("-Users-nat-Code-github-com-laris-co-neo-oracle-wt-x", dirs) == "github.com/laris-co/neo-oracle"
    assert rules.cwd_of("-opt-Code-github-com-laris-co-neon", dirs) == "github.com"
    assert rules.cwd_of("-tmp-scratch", dirs) is None


def test_rule_through_mcp_and_api(root, monkeypatch):
    from fastapi.testclient import TestClient
    from relic5.api import make_app
    from relic5.doors import Doors
    monkeypatch.setenv("RELIC5_WARM", "0")
    fleet(root)
    c = TestClient(make_app(root, {"m5": "t"}, Doors({"m5": "t"}, enabled=False)))
    h = {"Authorization": "Bearer t"}
    a = c.get("/api/rule", params={"phrase": "tailscale only", "forbids": ",".join(FORBIDS)}, headers=h).json()
    assert a["triple"]["candidates"] == 9 and a["triple"]["flagged"] == 4
    assert c.get("/api/rule", headers=h).status_code in (400, 422)
    body = {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
            "params": {"name": "relic_rule", "arguments": {"phrase": "tailscale only", "forbids": FORBIDS}}}
    res = c.post("/mcp", json=body, headers=h).json()["result"]
    assert not res.get("isError") and "candidates 9" in res["content"][0]["text"]
