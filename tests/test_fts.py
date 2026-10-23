import json, os

import duckdb
import pytest

from conftest import COLS, row, write_parquet
from relic5 import fts
from relic5.parts import Parts
from relic5.query import Relic5, UsageError


@pytest.fixture
def built(root, monkeypatch):
    monkeypatch.setenv("RELIC5_NOW", "2026-10-23T14:00:00Z")
    # the same message resumed into another session: another msgkey, same (ts, role, text) -> folds
    write_parquet(os.path.join(root, "parts/m5/text/2026-08.parquet"), COLS, [
        row("an old hub note from august", "2026-08-01T00:00:00.000Z", sid="s4-dddd"),
        row("resumed twice: watermark embed", "2026-08-02T00:00:00.000Z", sid="s5-a"),
        row("resumed twice: watermark embed", "2026-08-02T00:00:00.000Z", sid="s5-b"),
    ])
    con = duckdb.connect()
    Parts(root).index(con, log=lambda s: None)
    done = fts.build(root, con, log=lambda s: None)
    return root, done


def test_build_publishes_history_and_open(built):
    root, done = built
    assert {"prose_history", "prose_open", "tools_open"} <= set(done)
    cur = fts.current(root)
    assert all(os.path.isdir(os.path.join(root, "index/_search", v)) for v in cur.values())


def test_rebuild_only_what_changed(built):
    root, _ = built
    con = duckdb.connect()
    assert fts.build(root, con, log=lambda s: None) == []
    write_parquet(os.path.join(root, "parts/m5/text/2026-10.parquet"), COLS, [row("brand new hub line", "2026-10-23T13:00:00.000Z")])
    Parts(root).index(con, log=lambda s: None)
    assert fts.build(root, con, log=lambda s: None) == ["prose_open"]   # the sealed months are not touched


def test_bm25_thai_and_fold(built):
    root, _ = built
    r = Relic5(root, duckdb.connect())
    hits = r.search("ภาษาไทย")["hits"]
    assert len(hits) == 1 and hits[0]["score"] > 0 and "fallback" not in r.search("ภาษาไทย")
    shared = r.search("shared")["hits"]
    assert len(shared) == 1 and shared[0]["machines"] == ["m5", "mba"]
    assert len(r.search("resumed watermark")["hits"]) == 1               # (ts, role, text) fold across sessions


def test_widening_narrowest_window(built):
    root, _ = built
    r = Relic5(root, duckdb.connect())
    res = r.search("hub")
    assert res["widened"] and res["horizon"] == "archive" and res["horizons_tried"] == ["7d", "15d", "1m", "3m", "archive"]
    one = r.search("deploy")
    assert one["horizons_tried"][-1] == "archive"                       # 1 hit < target: widens to the end
    assert r.search("hub", horizon="7d")["horizons_tried"] == ["7d"]
    assert r.search("hub", since="2026-08-01")["horizon"] == "window"


def test_prose_before_tools(built):
    root, _ = built
    hits = Relic5(root, duckdb.connect()).search("hub", with_="tools", limit=50)["hits"]
    layers = [h["layer"] for h in hits]
    assert "tools" in layers and layers.index("tools") > max(i for i, l in enumerate(layers) if l == "prose")


def test_cursor_pins_horizon(built):
    root, _ = built
    r = Relic5(root, duckdb.connect())
    a = r.search("hub", limit=1)
    b = r.search("hub", limit=1, cursor=a["next_cursor"])
    assert b["horizons_tried"] == [a["horizon"]] and not {h["uid"] for h in a["hits"]} & {h["uid"] for h in b["hits"]}
    with pytest.raises(UsageError):
        r.search("white", cursor=a["next_cursor"])


def test_unparseable_query_falls_back(built):
    root, _ = built
    r = Relic5(root, duckdb.connect()).search('"unbalanced')
    assert "hits" in r
