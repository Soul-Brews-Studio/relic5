"""activity.py: counts by time bucket and dimension, for charts."""
import pytest

from relic5.activity import activity


def test_counts_by_day_and_role(relic):
    a = activity(relic, by="day", group="role")
    names = {s["name"]: s for s in a["series"]}
    assert set(names) == {"user", "assistant"} and a["total"] == sum(s["total"] for s in a["series"])
    assert "2026-10-23" in a["buckets"] and names["assistant"]["counts"]["2026-10-23"] == 1
    shared = activity(relic, by="month")                     # the message two machines hold counts once
    assert shared["series"][0]["name"] == "all" and shared["total"] == 6
    assert activity(relic, by="hour_of_day", role="assistant")["buckets"] == ["11"]
    assert activity(relic, since="2026-10-23")["total"] == 4
    assert activity(relic, until="2026-09")["total"] == 1
    assert activity(relic, group="machine", top=1)["series"][-1]["name"] == "other"
    with pytest.raises(ValueError):
        activity(relic, by="year")


def test_other_streams(relic):
    t = activity(relic, stream="tools", group="tool")
    assert t["unit"] == "tool calls" and t["total"] == 1
    with pytest.raises(ValueError):
        activity(relic, group="tool")
    with pytest.raises(ValueError):
        activity(relic, stream="video")
    assert activity(relic, stream="git")["total"] == 0          # no commits pushed in the fixture


def test_weekday_hour_heatmap(relic):
    b = activity(relic, by="weekday_hour", role="assistant")["buckets"]
    assert b == ["5-11"]                       # 2026-10-23 is a Friday, the assistant row is at 11:00


def test_files_changed_most(root):
    import duckdb
    from conftest import COLS, row, write_parquet
    from relic5.activity import files
    from relic5.query import Relic5
    write_parquet(f"{root}/parts/m5/tools/2026-07.parquet", COLS, [
        dict(row('{"file_path": "/x/a.py", "old_string": "1"}', "2026-07-01T10:11:00.000Z", sid="r1-x", role=""), name="Edit"),
        dict(row('{"file_path": "/x/a.py", "content": "2"}', "2026-07-02T10:11:00.000Z", sid="r2-x", role=""), name="Write"),
        dict(row('{"file_path": "/x/b.md", "content": "3"}', "2026-07-02T11:11:00.000Z", sid="r2-x", role=""), name="Write"),
        dict(row('{"command": "pytest"}', "2026-07-01T10:12:00.000Z", sid="r1-x", role=""), name="Bash")])
    f = files(Relic5(root, duckdb.connect()))
    assert [(x["file"], x["calls"], x["sessions"], x["days"]) for x in f["files"]] == [("/x/a.py", 2, 2, 2), ("/x/b.md", 1, 1, 1)]
    assert f["files"][0]["tools"] == ["Edit", "Write"] and f["total_calls"] == 3
    assert [x["file"] for x in files(Relic5(root, duckdb.connect()), contains=".md")["files"]] == ["/x/b.md"]


def test_group_by_file(root):
    import duckdb
    from conftest import COLS, row, write_parquet
    from relic5.query import Relic5
    write_parquet(f"{root}/parts/m5/tools/2026-07.parquet", COLS, [
        dict(row('{"file_path": "/x/a.py"}', "2026-07-01T10:11:00.000Z", sid="r1-x", role=""), name="Edit"),
        dict(row('{"command": "ls"}', "2026-07-01T10:12:00.000Z", sid="r1-x", role=""), name="Bash")])
    a = activity(Relic5(root, duckdb.connect()), by="month", group="file", stream="tools")
    assert [(s["name"], s["total"]) for s in a["series"]] == [("/x/a.py", 1)]


def test_usage_by_month_and_engine(relic):
    from relic5.activity import usage
    u = usage(relic)
    assert u["rows"] and {"period", "engine", "sessions", "subagents", "tool_calls"} <= u["rows"][0].keys()
    assert u["totals"]["sessions"] == 2 and u["totals"]["subagents"] == 1
    with pytest.raises(ValueError):
        usage(relic, group="model")


def test_usage_keeps_empty_placeholders_apart(root):
    """2026-10-26: 44,732 of July's sessions were jsonl-truth-import shells with every counter 0; ChatGPT read them as an
    18.7x jump in work. A session with no message and no tool call is counted as empty_sessions, not as a session."""
    import duckdb
    from conftest import META_COLS, meta, write_parquet
    from relic5.activity import usage
    from relic5.query import Relic5
    shell = {**meta("imp-1"), **{k: 0 for k in META_COLS[11:]}}
    write_parquet(f"{root}/parts/m5/meta/sessions.parquet", META_COLS, [meta("s1-aaaa"), shell, {**shell, "sid": "imp-2", "base": "imp-2.jsonl"}],
                  types={"n_rows": "BIGINT", "months": "VARCHAR[]", **{k: "BIGINT" for k in META_COLS[11:]}})
    u = usage(Relic5(root, duckdb.connect()))
    assert u["totals"]["sessions"] == 1 and u["totals"]["empty_sessions"] == 2


def test_a_real_machine_beats_a_one_time_import(root):
    """2026-10-26: the fold took the first machine by name, so "jsonl-truth-import" beat "m5" and its zero-counter copy
    of 43,326 July sessions made them look empty. An import's copy is kept only when no real machine has the session."""
    import duckdb
    from conftest import META_COLS, meta, write_parquet
    from relic5.activity import usage
    from relic5.query import Relic5
    types = {"n_rows": "BIGINT", "months": "VARCHAR[]", **{k: "BIGINT" for k in META_COLS[11:]}}
    zero = {k: 0 for k in META_COLS[11:]}
    write_parquet(f"{root}/parts/jsonl-truth-import/meta/sessions.parquet", META_COLS,
                  [{**meta("s1-aaaa"), **zero}, {**meta("only-imp"), **zero}], types=types)
    r = Relic5(root, duckdb.connect())
    rows = {x["sid"]: x for x in r._rows(f"SELECT sid, machine, user_text FROM {r._meta()}")}
    assert rows["s1-aaaa"]["machine"] == "m5" and rows["s1-aaaa"]["user_text"] == 1
    assert rows["only-imp"]["machine"] == "jsonl-truth-import"            # nobody else has it: the import's copy stays
    u = usage(r)
    assert u["totals"]["empty_sessions"] == 1


def test_repair_meta_fills_an_imports_counters(root):
    """relic4-scan, 2026-10-26: the import's meta carried n_rows and times only, so every counter read 0. repair_meta
    counts them from the import's own parts, keeps the old file, and the sessions stop being empty."""
    import duckdb, os
    from conftest import COLS, row, write_parquet
    from relic5 import importer
    from relic5.activity import usage
    from relic5.query import Relic5
    m = f"{root}/parts/jsonl-truth-import"
    write_parquet(f"{m}/meta/sessions.parquet", ["sid", "tier", "parent_sid", "engine", "proj", "cat", "probe", "first_ts", "last_ts", "n_rows", "months"],
                  [{"sid": "imp-1", "tier": "main", "parent_sid": None, "engine": "claude", "proj": None, "cat": "jsonl-truth-import",
                    "probe": False, "first_ts": "2026-07-01T10:00:00.000Z", "last_ts": "2026-07-01T11:00:00.000Z", "n_rows": 4,
                    "months": ["2026-07"]}], types={"n_rows": "BIGINT", "months": "VARCHAR[]", "probe": "BOOLEAN"})
    write_parquet(f"{m}/text/2026-07.parquet", COLS, [row("hi", "2026-07-01T10:00:00.000Z", sid="imp-1"),
                                                      row("hello", "2026-07-01T10:01:00.000Z", sid="imp-1", role="assistant")])
    write_parquet(f"{m}/tools/2026-07.parquet", COLS, [dict(row('{"command": "ls"}', "2026-07-01T10:02:00.000Z", sid="imp-1", role=""), kind="call", name="Bash")])
    before = usage(Relic5(root, duckdb.connect()), since="2026-07-01", until="2026-07")
    assert before["totals"]["empty_sessions"] == 1
    r = importer.repair_meta(root, "jsonl-truth-import", duckdb.connect(), log=lambda s: None)
    assert (r["user_text"], r["assistant_text"], r["tool_calls"], r["still_empty"]) == (1, 1, 1, 0)
    assert os.path.exists(r["backup"])
    after = usage(Relic5(root, duckdb.connect()), since="2026-07-01", until="2026-07")
    assert after["totals"]["sessions"] == 1 and after["totals"]["empty_sessions"] == 0 and after["totals"]["typed"] == 1
