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


def test_widening_never_hides_older_hits(built):
    """Issue #19: widening stops in a window with enough hits, but the best older hits still follow them."""
    root, _ = built
    r = Relic5(root, duckdb.connect())
    res = r.search("hub", limit=2)                                       # 2 hits in the last 7 days: widening stops there
    assert res["horizons_tried"] == ["7d"] and res["older_hits"] > 0 and "older ones" in res["note"]
    months = [h["partition"] for h in r.search("hub", limit=50)["hits"]]
    assert "2026-08" in months and "2026-09" in months                   # august and september reached on the first call
    recent = r.search("hub", limit=2)["hits"]
    assert all(h["ts"] >= "2026-10-16" for h in recent[:2])              # the window's hits still come first
    assert r.search("hub", horizon="7d", limit=2)["older_hits"] == 0      # an explicit window means only that window


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


def test_sort_newest_and_ephemeral(built):
    root, _ = built
    from conftest import row, write_parquet, COLS
    write_parquet(os.path.join(root, "parts/m5/text/2026-10.parquet"), COLS, [
        row("hub log at /tmp/claude-501/scratchpad/out.txt", "2026-10-23T12:00:00.000Z"),
        row("hub hub hub hub very relevant hub", "2026-10-20T12:00:00.000Z")])
    con = duckdb.connect()
    Parts(root).index(con, log=lambda s: None)
    fts.build(root, con, log=lambda s: None)
    r = Relic5(root, duckdb.connect())
    rel = r.search("hub", horizon="archive")["hits"]
    new = r.search("hub", horizon="archive", sort="newest")["hits"]
    assert [h["ts"] for h in new] == sorted((h["ts"] for h in new), reverse=True) and rel[0]["ts"] != new[0]["ts"]
    assert new[0]["ephemeral"] == ["/tmp/claude-501/scratchpad/out.txt"] and rel[0]["ephemeral"] is None


def test_exact_phrase_ranks_first(built):
    root, _ = built
    from conftest import row, write_parquet, COLS
    write_parquet(os.path.join(root, "parts/m5/text/2026-10.parquet"), COLS, [
        row("I want to use ego browser to test it", "2026-10-21T12:00:00.000Z", sid="p1"),
        row("use the browser to want ego things to to to to to", "2026-10-22T12:00:00.000Z", sid="p2")])
    con = duckdb.connect()
    Parts(root).index(con, log=lambda s: None)
    fts.build(root, con, log=lambda s: None)
    hits = Relic5(root, duckdb.connect()).search("to use ego browser to", horizon="archive")["hits"]
    assert hits[0]["session_uuid"] == "p1" and {h["session_uuid"] for h in hits} >= {"p1", "p2"}


def test_explain_shows_tokens_weights_and_what_each_hit_matched(root):
    from fastapi.testclient import TestClient
    from relic5.api import make_app
    from relic5.doors import Doors
    from relic5.cli import main
    main(["index", "--root", root])
    import os
    os.environ["RELIC5_WARM"] = "0"
    c = TestClient(make_app(root, {"m5": "t"}, Doors({"m5": "t"}, enabled=False)))
    H = {"Authorization": "Bearer t"}
    e = c.get("/api/explain", params={"q": "Deploy the HUB ค้นหาได้ไหม"}, headers=H).json()
    assert e["tokens"][:3] == ["deploy", "the", "hub"] and "ค้นหา" in e["tokens"]
    t = {x["token"]: x for x in e["terms"]}
    assert t["deploy"]["rows"] == 1 and t["hub"]["rows"] >= 2 and t["deploy"]["idf"] > t["hub"]["idf"]
    assert e["rows"] > 0 and e["phrase_rows"] is not None
    hits = c.get("/api/search", params={"q": "deploy hub"}, headers=H).json()["hits"]
    assert hits and all(set(h["matched"]) <= {"deploy", "hub"} for h in hits) and any(h["matched"] == ["deploy", "hub"] for h in hits)
    assert c.get("/api/explain", params={"q": " "}, headers=H).status_code == 400
