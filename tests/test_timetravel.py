import json, os
from datetime import datetime, timezone

import duckdb
import pytest

from conftest import COLS, META_COLS, row, write_parquet
from relic5 import mcp, names, readings, session_readings as SR, timetravel as TT
from relic5.parts import Parts
from relic5.query import Relic5, UsageError
from relic5.recap import recap

COLS_M = META_COLS + ["cwd", "branch", "title"]
TYPES = {"n_rows": "BIGINT", "months": "VARCHAR[]", **{k: "BIGINT" for k in META_COLS[11:]}}
WT = "/opt/Code/github.com/laris-co/book-library/wt/a"
PROJ = "-opt-Code-github-com-laris-co-book-library"


def m(sid, first, last, cwd=WT, proj=PROJ, branch="feat-a", title=None, machine_tier="main", parent=None):
    return {"base": sid + ".jsonl", "tier": machine_tier, "sid": sid, "parent_sid": parent, "engine": "claude", "proj": proj,
            "cat": "book-library", "first_ts": first, "last_ts": last, "n_rows": 4, "months": [first[:7]],
            **{k: 1 for k in META_COLS[11:]}, "cwd": cwd, "branch": branch, "title": title}


@pytest.fixture
def hub(tmp_path):
    root = str(tmp_path)
    text = [
        row("hello", "2026-10-29T01:00:00.000Z", sid="a1-aaaa"),
        row("built the gallery", "2026-10-29T02:00:00.000Z", sid="a1-aaaa", role="assistant"),
        row("now the books MCP over sqlite", "2026-10-29T10:00:00.000Z", sid="a2-bbbb"),
        row("books MCP done: 7 tools", "2026-10-29T11:00:00.000Z", sid="a2-bbbb", role="assistant"),
        row("parallel: covers", "2026-10-29T10:30:00.000Z", sid="a3-cccc"),
        row("covers drawn", "2026-10-29T10:45:00.000Z", sid="a3-cccc", role="assistant"),
        row("deploy to cloudflare", "2026-10-30T03:00:00.000Z", sid="a4-dddd"),
        row("worker live", "2026-10-30T04:00:00.000Z", sid="a4-dddd", role="assistant"),
        row("elsewhere entirely", "2026-10-29T10:20:00.000Z", sid="x9-zzzz"),
        # the arc: a topic that starts in one project and moves to another
        row("semantic library idea", "2026-08-03T01:00:00.000Z", sid="x9-zzzz"),
        row("semantic library again", "2026-09-03T01:00:00.000Z", sid="x9-zzzz"),
    ]
    write_parquet(f"{root}/parts/m5/text/2026-10.parquet", COLS, [r for r in text if r["month"] == "2026-10"])
    write_parquet(f"{root}/parts/m5/text/2026-09.parquet", COLS, [r for r in text if r["month"] == "2026-09"])
    write_parquet(f"{root}/parts/m5/text/2026-08.parquet", COLS, [r for r in text if r["month"] == "2026-08"])
    tools = [dict(row('{"file_path": "/b/gallery.html"}', "2026-10-29T01:30:00.000Z", sid="a1-aaaa", role=""), name="Write"),
             dict(row('{"file_path": "/b/tools/book_mcp.py"}', "2026-10-29T10:10:00.000Z", sid="a2-bbbb", role=""), name="Edit")]
    write_parquet(f"{root}/parts/m5/tools/2026-10.parquet", COLS, tools)
    write_parquet(f"{root}/parts/m5/meta/sessions.parquet", COLS_M, [
        m("a1-aaaa", "2026-10-29T01:00:00.000Z", "2026-10-29T02:00:00.000Z"),
        m("a2-bbbb", "2026-10-29T10:00:00.000Z", "2026-10-29T11:00:00.000Z"),
        m("a3-cccc", "2026-10-29T10:30:00.000Z", "2026-10-29T10:45:00.000Z"),
        m("a4-dddd", "2026-10-30T03:00:00.000Z", "2026-10-30T04:00:00.000Z"),
        m("x9-zzzz", "2026-08-03T01:00:00.000Z", "2026-10-29T10:20:00.000Z", cwd="/elsewhere", proj="-elsewhere", branch="main"),
    ], types=TYPES)
    names.build(root, duckdb.connect(), Parts(root))
    return root


def test_chain_walks_the_worktree_with_gaps_and_parallel_runs(hub):
    r = Relic5(hub, duckdb.connect())
    c = TT.chain(r, "a2", before=3, after=3)
    assert c["scope"] == "worktree" and c["in_scope"] == 4 and c["position"] == 2
    assert [n["uuid"][:2] for n in c["nodes"]] == ["a1", "a2", "a3", "a4"]
    a1, a2, a3, a4 = c["nodes"]
    assert a2["is_target"] and not a1["is_target"]
    assert a2["gap_before"] == "gap" and a2["gap_before_s"] == 8 * 3600     # 02:00 -> 10:00
    assert a3["gap_before"] == "parallel"                                    # started inside a2
    assert a1["files_edited"] == ["/b/gallery.html"] and a2["files_edited"] == ["/b/tools/book_mcp.py"]
    assert a2["first_ask"] == "now the books MCP over sqlite" and a2["last_reply"] == "books MCP done: 7 tools"
    assert a1["title"] == "hello"   # no reading, and the first ask is generic too: the name stays
    assert a2["start_th"] == "2026-10-29 17:00"
    one = TT.chain(r, "a2", before=0, after=1)
    assert [n["uuid"][:2] for n in one["nodes"]] == ["a2", "a3"] and "1 earlier" in one["more"]
    assert TT.chain(r, "a2", scope="repo")["in_scope"] == 4
    with pytest.raises(UsageError):
        TT.chain(r, "a2", scope="moon")


def test_at_a_moment_shows_sessions_readings_and_the_hit(hub):
    os.makedirs(f"{hub}/readings", exist_ok=True)
    with open(f"{hub}/readings/m5.jsonl", "w") as f:
        for unit, focus in (("2026-10-29 17:00-18:00 1h", "books MCP"), ("2026-10-29 day", "book library day"),
                            ("2026-10-29 09:00-10:00 1h", "too early")):
            f.write(json.dumps({"unit": unit, "model": "zai:glm-5.3", "at": "2026-10-30T00:00:00+0700", "answer": {"focus": focus}}) + "\n")
    r = Relic5(hub, duckdb.connect())
    a = TT.at(r, "2026-10-29 17:20", span="30m")
    assert a["moment"] == "2026-10-29T10:20:00.000Z" and a["moment_th"] == "2026-10-29 17:20"
    assert [x["focus"] for x in a["readings"]] == ["books MCP", "book library day"]
    sids = {x["uuid"][:2] for x in a["sessions"]}
    assert sids == {"a2", "a3", "x9"}   # a3 started at 17:30, inside the span
    assert a["commits"] == [] and a["searches"] == []
    a2 = next(x for x in a["sessions"] if x["uuid"].startswith("a2"))
    assert a2["last_turn"]["text"] == "now the books MCP over sqlite"   # what it said up to the span's end
    hit = r.search_ilike("books MCP done")["hits"][0]
    h = TT.at(r, hit["link"], span="10m")
    assert h["hit"]["target"]["text"] == "books MCP done: 7 tools" and any(x["is_hit"] for x in h["sessions"])
    with pytest.raises(UsageError):
        TT.at(r, "2026-10-29 17:20", span="soon")


def test_at_counts_a_session_that_starts_inside_the_span(hub):
    r = Relic5(hub, duckdb.connect())
    sids = {x["uuid"][:2] for x in TT.at(r, "2026-10-29 17:20", span="15m")["sessions"]}
    assert sids == {"a2", "x9", "a3"}
    wide = {x["uuid"][:2] for x in TT.at(r, "2026-10-29 17:20", span="1h")["sessions"]}
    assert {"a2", "a3", "x9"} <= wide and "a4" not in wide


def test_arc_counts_months_and_finds_the_turn(hub):
    r = Relic5(hub, duckdb.connect())
    a = TT.arc(r, "semantic library")
    assert a["hits"] == 2 and "substring" in a["how"]
    assert [x["month"] for x in a["months"]] == ["2026-08", "2026-09"]
    assert a["first"]["text"] == "semantic library idea" and a["last"]["text"] == "semantic library again"
    assert a["turning_points"][0]["why"] == "first month" and a["first"]["link"].startswith("relic5://2026-08/")
    with pytest.raises(UsageError):
        TT.arc(r, "  ")


def test_session_readings_title_recap_and_listing(hub):
    os.makedirs(f"{hub}/readings/sessions", exist_ok=True)
    with open(f"{hub}/readings/sessions/m5.jsonl", "w") as f:
        f.write(json.dumps({"sid": "a1-aaaa", "model": "zai:glm-5.3", "at": "2026-10-30T01:00:00+0700",
                            "answer": {"focus": "old reading"}}) + "\n")
        f.write(json.dumps({"sid": "a1-aaaa", "model": "zai:glm-5.3", "at": "2026-10-31T01:00:00+0700",
                            "answer": {"focus": "Built the book-library gallery", "ended": "gallery live", "open": ["covers"]}}) + "\n")
        f.write("not json\n")
    r = Relic5(hub, duckdb.connect())
    s = r.session("a1")
    assert s["reading"]["focus"] == "Built the book-library gallery" and s["display_title"] == "Built the book-library gallery"
    c = recap(r, "a1")
    assert c["reading"]["open"] == ["covers"]
    lst = readings.readings(hub, kind="sessions", q="gallery")
    assert lst["total"] == 1 and lst["rows"][0]["sid"] == "a1-aaaa"
    assert SR.search(hub, "book-library gallery")[0]["sid"] == "a1-aaaa"
    assert TT.chain(r, "a1", after=0)["nodes"][0]["reading"]["focus"] == "Built the book-library gallery"
    with pytest.raises(ValueError):
        readings.readings(hub, kind="weeks")


def test_display_title_rules():
    assert SR.display_title("hello", None, {"focus": "Ships the gallery"}) == "Ships the gallery"
    assert SR.display_title("Fix the relic FTS stopwords", None) == "Fix the relic FTS stopwords"
    assert SR.display_title("/model opus", None, None, "deploy relic5 to white please") == "deploy relic5 to white please"
    assert SR.display_title("ok", "Maw token use pb and restart") == "Maw token use pb and restart"
    assert SR.generic("The user sent a new message while you were working: x") and SR.generic("go") and not SR.generic("go build all")


def test_readings_freshness_warns_when_the_lane_stops(tmp_path):
    root = str(tmp_path)
    os.makedirs(f"{root}/readings", exist_ok=True)
    os.makedirs(f"{root}/recaps", exist_ok=True)
    open(f"{root}/recaps/2026-09.md", "w").write("# Sep")
    with open(f"{root}/readings/m5.jsonl", "w") as f:
        for unit in ("2026-09-30 day", "2026-10-25 day", "2026-10-25 10:00-11:00 1h"):
            f.write(json.dumps({"unit": unit, "model": "zai:glm-5.3", "at": "x", "answer": {"focus": "f"}}) + "\n")
    now = datetime(2026, 11, 5, 3, 0, tzinfo=timezone.utc)
    fr = readings.freshness(root, now)
    assert fr["newest_day"] == "2026-10-25" and fr["lag_days"] == 11
    assert fr["by_machine"]["m5"]["zai:glm-5.3"] == {"day": "2026-10-25 00:00", "1h": "2026-10-25 10:00"}
    assert fr["recap_missing"] == ["2026-10"] and fr["recaps"] == ["2026-09"]
    assert any("11 days ago" in w for w in fr["warnings"]) and any("relic5-month-recap 2026-10" in w for w in fr["warnings"])
    fresh = readings.freshness(root, datetime(2026, 10, 26, 3, 0, tzinfo=timezone.utc))
    assert fresh["lag_days"] == 1 and not any("days ago" in w for w in fresh["warnings"])
    assert readings.freshness(str(tmp_path / "none"), now)["newest_day"] is None


def test_mcp_tools(hub):
    r = Relic5(hub, duckdb.connect())
    ok, c = mcp.call_tool(r, "relic_chain", {"id": "a2", "before": 1, "after": 0, "parent": "t1"})
    assert ok and [n["uuid"][:2] for n in c["nodes"]] == ["a1", "a2"]
    ok, c = mcp.call_tool(r, "relic_chain", {"id": "a2", "gap_hours": "12"})
    assert ok and c["nodes"][1]["gap_before"] is None
    ok, c = mcp.call_tool(r, "relic_recap", {"id": "a2", "limit": 0})
    assert ok and c["asked"][0]["text"] == "now the books MCP over sqlite"
    ok, c = mcp.call_tool(r, "relic_at", {"moment": "2026-10-29 17:20", "span": "5m"})
    assert ok and c["moment_th"] == "2026-10-29 17:20"
    ok, c = mcp.call_tool(r, "relic_arc", {"words": "semantic library"})
    assert ok and c["hits"] == 2
    ok, e = mcp.call_tool(r, "relic_chain", {"id": "a2", "colour": "red"})
    assert not ok and e[0] == "usage"
    ok, c = mcp.call_tool(r, "relic_readings", {"kind": "sessions"})
    assert ok and c["kind"] == "sessions" and c["total"] == 0 and "note" in c
    assert {"relic_chain", "relic_at", "relic_arc", "relic_recap"} <= {t["name"] for t in mcp.TOOLS}
    assert "relic_chain" not in mcp.UNAVAILABLE
