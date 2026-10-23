import duckdb
import pytest

from conftest import META_COLS, meta, write_parquet
from relic5 import fts, names
from relic5.parts import Parts
from relic5.query import Relic5, UsageError

T = {"n_rows": "BIGINT", "months": "VARCHAR[]", **{k: "BIGINT" for k in META_COLS[11:]}}


def test_without_cwd_the_filter_says_so(root, monkeypatch):
    monkeypatch.setenv("RELIC5_NOW", "2026-10-23T14:00:00Z")
    con = duckdb.connect()
    Parts(root).index(con, log=lambda s: None)
    fts.build(root, con, log=lambda s: None)
    with pytest.raises(UsageError, match="not in the index yet"):
        Relic5(root, duckdb.connect()).search("hub", cwd="/opt/Code")


def test_title_cwd_and_resume(root, monkeypatch):
    monkeypatch.setenv("RELIC5_NOW", "2026-10-23T14:00:00Z")
    cols = META_COLS + ["cwd", "title", "branch", "version"]
    rows = [meta("s1-aaaa") | {"cwd": "/opt/Code/github.com/x/relic5", "title": "Relic5 hub on white", "branch": "m1", "version": "2.1"},
            meta("s2-bbbb") | {"cwd": "/tmp/elsewhere"}, meta("agent-1", tier="subagent", parent="s1-aaaa")]
    for m in ("m5", "mba"):
        write_parquet(f"{root}/parts/{m}/meta/sessions.parquet", cols, rows, types=T)
    con = duckdb.connect()
    Parts(root).index(con, log=lambda s: None)
    fts.build(root, con, log=lambda s: None)
    names.build(root, con, Parts(root))
    r = Relic5(root, duckdb.connect())
    s = r.session("s1")
    assert s["name"] == "Relic5 hub on white" and s["resume"] == "cd /opt/Code/github.com/x/relic5 && claude --resume s1-aaaa"
    hits = r.search("hub", cwd="/opt/Code", horizon="archive")["hits"]
    assert hits and {h["session_uuid"] for h in hits} == {"s1-aaaa"}
    assert r.search("done", cwd="/opt/Code", horizon="archive")["hits"] == []     # s2 ran in /tmp
