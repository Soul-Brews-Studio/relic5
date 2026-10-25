"""Whose .claude: the home of each message from relic-scan's src_path, filters on search and sessions, the list of
homes (Nat, 2026-10-25: "separate like .claude from user nat / .claude from user beta or .claude project of some project")."""
import duckdb

from conftest import COLS, META_COLS, meta, row, write_parquet
from relic5.cli import main
from relic5.query import Relic5

C = COLS + ["src_agent", "src_path"]


def at(r, agent, path):
    return r | {"src_agent": agent, "src_path": path}


def test_homes_split_search_and_sessions(tmp_path):
    root = str(tmp_path)
    beta = at(row("deploy the hub from beta", "2026-10-23T10:00:00.000Z", sid="sb-1111"), "beta@m5", "/Users/beta/.claude/projects/-opt-x/sb.jsonl")
    nat = at(row("deploy the hub from nat", "2026-10-23T11:00:00.000Z", sid="sn-2222"), "nat@m5", "/Users/nat/.claude/projects-archive/-opt-x/sn.jsonl")
    proj = at(row("deploy the hub from a project home", "2026-10-23T12:00:00.000Z", sid="sp-3333"), "nat@mba",
              "/Users/nat/Code/exp/.claude-hello/.claude/projects/-x/sp.jsonl")
    shared = row("one message both homes hold", "2026-10-23T13:00:00.000Z", sid="sb-1111")
    write_parquet(f"{root}/parts/m5/text/2026-10.parquet", C, [beta, nat, at(shared, "beta@m5", "/Users/beta/.claude/projects/-opt-x/sb.jsonl")])
    write_parquet(f"{root}/parts/mba/text/2026-10.parquet", C, [proj, at(shared, "nat@mba", "/Users/nat/.claude1/projects/-opt-x/sb.jsonl")])
    write_parquet(f"{root}/parts/m5/meta/sessions.parquet", META_COLS, [meta("sb-1111"), meta("sn-2222"), meta("sp-3333")],
                  types={"n_rows": "BIGINT", "months": "VARCHAR[]", **{k: "BIGINT" for k in META_COLS[11:]}})
    main(["index", "--root", root])
    r = Relic5(root, duckdb.connect())

    hits = r.search("deploy hub", home="/Users/nat/.claude")["hits"]
    assert [h["session_uuid"] for h in hits] == ["sn-2222"] and hits[0]["home"] == "/Users/nat/.claude" and hits[0]["agent"] == "nat@m5"
    assert {h["session_uuid"] for h in r.search("deploy hub", home="beta")["hits"]} == {"sb-1111"}
    assert [h["home"] for h in r.search("deploy", home=".claude-hello")["hits"]] == ["/Users/nat/Code/exp/.claude-hello/.claude"]
    both = r.search("both homes")["hits"][0]
    assert sorted(both["homes"]) == ["/Users/beta/.claude", "/Users/nat/.claude1"]          # a copy is in both
    assert r.search("both homes", home=".claude1")["hits"]                                   # found from either home

    assert [s["uuid"] for s in r.sessions(home="beta/.claude")["sessions"]] == ["sb-1111"]
    hs = {h["home"]: h for h in r.homes()["homes"]}
    assert hs["/Users/beta/.claude"]["user"] == "beta" and hs["/Users/beta/.claude"]["kind"] == "user"
    assert hs["/Users/nat/Code/exp/.claude-hello/.claude"]["kind"] == "project" and hs["/Users/nat/.claude"]["label"] == "~/.claude"
