import math, os

import duckdb
import pytest

from relic5 import fts, vec
from relic5.parts import Parts
from relic5.query import Relic5, UsageError

M = vec.DEFAULT


def unit(v):
    n = math.sqrt(sum(x * x for x in v))
    return [x / n for x in v]


@pytest.fixture
def withvec(root, monkeypatch):
    monkeypatch.setenv("RELIC5_NOW", "2026-10-23T14:00:00Z")
    monkeypatch.setattr(vec, "MIN_CHARS", 0)            # the fixture's texts are short
    con = duckdb.connect()
    keys = [k for (k,) in con.execute(f"SELECT DISTINCT key FROM read_parquet('{root}/parts/*/text/*.parquet') ORDER BY key").fetchall()]
    texts = dict(con.execute(f"SELECT key, any_value(text) FROM read_parquet('{root}/parts/*/text/*.parquet') GROUP BY key").fetchall())
    have = [k for k in keys if "white" in texts[k] or "ไทย" in texts[k] or "mba" in texts[k]]   # some keys get a vector
    d = os.path.join(root, "vectors", M)
    os.makedirs(d)
    rows = ", ".join(f"('{k}', {unit([1.0, 0.1, 0.0] if 'white' in texts[k] else [0.0, 1.0, 0.1])}::FLOAT[])" for k in have)
    con.execute(f"COPY (SELECT * FROM (VALUES {rows}) t(key, vector)) TO '{d}/seed-test.parquet' (FORMAT parquet)")
    Parts(root).index(con, log=lambda s: None)
    fts.build(root, con, log=lambda s: None)
    fts.build(root, con, log=lambda s: None, lane="vectors")
    return root, keys, have


def test_missing_and_watermarks(withvec):
    root, keys, have = withvec
    con = duckdb.connect()
    m = vec.missing(root, con, M, limit=100)
    assert m["pending"] == len(keys) - len(have) and not {r["key"] for r in m["rows"]} & set(have)
    assert [r["ts"] for r in m["rows"]] == sorted((r["ts"] for r in m["rows"]), reverse=True)   # newest first
    first = m["rows"][0]["key"]
    assert all(r["key"].startswith(first[0]) for r in vec.missing(root, con, M, prefix=first[0])["rows"])
    w = vec.watermarks(root, con, M)
    assert w["mba"]["pending"] == 1 and w["m5"]["pending"] >= 1


def test_vector_tables_and_semantic_search(withvec):
    root, _, have = withvec
    assert {"vec_unsloth_embeddinggemma_300m_806f5f90_open"} <= set(fts.current(root))
    r = Relic5(root, duckdb.connect())
    res = r.search("anything", vector=unit([1.0, 0.0, 0.0]))
    assert res["semantic"] and res["hits"][0]["text_snippet"].count("white") and res["hits"][0]["score"] > 0.9
    assert res["horizons_tried"] == ["archive"]                                          # semantic does not widen
    th = r.search("x", vector=unit([0.0, 1.0, 0.0]))["hits"]
    assert any("ไทย" in h["text_snippet"] for h in th)
    with pytest.raises(UsageError):
        r.search("x", vector=[1.0, 0, 0], model="qwen")


def test_vector_tables_rebuild_when_shards_change(withvec):
    root, keys, have = withvec
    con = duckdb.connect()
    assert fts.build(root, con, log=lambda s: None) == [] and fts.build(root, con, log=lambda s: None, lane="vectors") == []
    left = [k for k in keys if k not in have][:1]
    con.execute(f"COPY (SELECT '{left[0]}' AS key, {unit([0.0, 0.0, 1.0])}::FLOAT[] AS vector) TO '{root}/vectors/{M}/m5-run2.parquet' (FORMAT parquet)")
    assert fts.build(root, con, log=lambda s: None) == []                               # the fast lane ignores vectors
    done = fts.build(root, con, log=lambda s: None, lane="vectors")
    assert done and all(n.startswith("vec_") for n in done)
    assert {"prose_open", "vec_unsloth_embeddinggemma_300m_806f5f90_open"} <= set(fts.current(root))   # both lanes published


def test_short_rows_are_left_out_of_vector_tables(withvec, monkeypatch):
    root, _, have = withvec
    monkeypatch.setattr(vec, "MIN_CHARS", 20)
    con = duckdb.connect()
    sql = vec.table_sql(Parts(root), root, M, {"2026-10", "2026-09"})
    texts = [t for (t,) in con.execute(f"SELECT text FROM ({sql})").fetchall()]
    assert texts and all(len(t) >= 20 for t in texts) and "hub from the mba" not in texts   # 16 chars: keyword only


def test_hybrid_fuses_both_lists(withvec):
    root, _, _ = withvec
    r = Relic5(root, duckdb.connect()).search("hub", vector=unit([1.0, 0.0, 0.0]), hybrid=True)
    assert r["hybrid"] and r["hits"] and "white" in r["hits"][0]["text_snippet"]   # in both lists: ranked first
