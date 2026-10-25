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


def test_home_kinds_and_owners():
    from relic5.query import home_kind
    assert home_kind("/Users/beta/.claude") == {"user": "beta", "kind": "user", "label": "~/.claude"}
    assert home_kind("/Users/nat/.claude1")["kind"] == "extra"
    assert home_kind("/Users/beta/.relic3-mirror/Users/nat/.claude") | {} == {"user": "nat", "kind": "mirror", "label": "~beta/.relic3-mirror/Users/nat/.claude"}
    assert home_kind("/Users/Shared/nat-export/.claude")["user"] == "nat" and home_kind("/Users/Shared/nat-export/.claude")["kind"] == "export"
    assert home_kind("/opt/Code/_archive/oracle-world/neo-2026-06-10/.claude", "beta@m5") == {"user": "beta", "kind": "project", "label": "/opt/Code/_archive/oracle-world/neo-2026-06-10/.claude"}
    assert home_kind("/Users/nat/Code/exp/.claude-hello/.claude")["kind"] == "project"
    assert home_kind(None, "nat@m5")["kind"] == "unknown"
    assert home_kind("/Users/nat/.codex-team/1")["kind"] == "extra"
    assert home_kind("/Users/nat/.codex-team-attic/slot-3-dead-20260726-130229")["kind"] == "backup"
    assert home_kind("/opt/Code/_archive/oracle-world/nat-2026-06-10/.codex/path-migration-backup-20260530-134816")["kind"] == "backup"
    assert home_kind("/Users/Shared/nat-export/.claude/rescued-from-white-20260726/full-backup-2026-02-06")["kind"] == "backup"
    assert home_kind("/Users/Shared/nat-export/.claude/rescued-from-white-20260726/full-backup-2026-02-06")["user"] == "nat"


def test_a_home_with_folders_before_its_sessions():
    import duckdb
    from relic5.fts import HOME_SQL
    def home(p):
        return duckdb.sql(f"SELECT {HOME_SQL} FROM (SELECT '{p}' AS src_path)").fetchone()[0]
    assert home("/Users/nat/.claude/projects/-Users-nat-x/sid/subagents/a.jsonl") == "/Users/nat/.claude"
    assert home("/Users/beta/.codex/sessions/2026/05/18/r.jsonl") == "/Users/beta/.codex"
    assert home("/Users/nat/.codex-team/1/sessions/2026/06/18/r.jsonl") == "/Users/nat/.codex-team/1"
    assert home("/Users/Shared/nat-export/.claude/rescued-from-white/full-backup-2026-02-06/-Users-nat-x/s.jsonl") == \
        "/Users/Shared/nat-export/.claude/rescued-from-white/full-backup-2026-02-06"
    assert home("/Users/beta/notes/s.jsonl") is None
    assert home("/Users/beta/.omp/agent/sessions/--opt-x--/2026-10-14T09_01a1/s.jsonl") == "/Users/beta/.omp/agent"
    assert home("/opt/Code/github.com/x/thClaws/.thclaws/state/sessions/s.jsonl") == "/opt/Code/github.com/x/thClaws/.thclaws"
    assert home("/Users/beta/.relic-mirrors/white-ampere-codex/2026/09/19/r.jsonl") == "/Users/beta/.relic-mirrors/white-ampere-codex"
    assert home("/home/nat/.tmp/projects-bak/-home-nat-x/s.jsonl") == "/home/nat/.tmp"


def test_other_agents_homes_and_copies():
    from relic5.query import home_kind
    assert home_kind("/Users/beta/.omp/agent")["kind"] == "user"
    assert home_kind("/opt/Code/github.com/x/thClaws/.thclaws")["kind"] == "project"
    assert home_kind("/Users/beta/.relic-mirrors/white-ampere-codex")["kind"] == "mirror"
    assert home_kind("/Users/beta/.codex/from-white")["kind"] == "mirror"
    assert home_kind("/home/nat/.tmp")["kind"] == "backup"
    assert home_kind("/Users/nat/.claude-backup-2026-02-06/.claude")["kind"] == "backup"
    assert home_kind("/Users/nat/.codex-team-removed/7_20260706_1914")["kind"] == "backup"
