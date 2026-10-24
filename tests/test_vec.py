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


def test_short_rows_are_skipped_per_query(withvec):
    root, _, _ = withvec
    r = Relic5(root, duckdb.connect())
    allrows = r.search("x", vector=unit([0.0, 1.0, 0.0]), min_chars=0)["hits"]
    longer = r.search("x", vector=unit([0.0, 1.0, 0.0]), min_chars=20)["hits"]
    assert any("mba" in h["text_snippet"] for h in allrows) and not any("mba" in h["text_snippet"] for h in longer)


def test_hybrid_fuses_both_lists(withvec):
    root, _, _ = withvec
    r = Relic5(root, duckdb.connect()).search("hub", vector=unit([1.0, 0.0, 0.0]), hybrid=True)
    assert r["hybrid"] and r["hits"] and "white" in r["hits"][0]["text_snippet"]   # in both lists: ranked first


def test_probe_rows_carry_stored_vectors(withvec):
    root, _, have = withvec
    rows = vec.probe_rows(root, duckdb.connect(), M, n=50)
    assert rows and all(r["key"] in have and len(r["vector"]) == 3 for r in rows)


def test_near_duplicates_collapse():
    """Issue #25: a templated prompt per worktree differs only in its paths; it is one hit that counts the others."""
    from relic5.search import collapse, near_key
    tpl = ('You are auditing ONE git worktree of the maw-js repo to decide if it is SAFE to remove during a full team teardown. '
           'Worktree path: "{}"  (branch hint: "{}"). NOTE: if "{}" does not exist, that worktree is already gone: report it '
           'as gone and stop. Otherwise list uncommitted files, unpushed commits and stashes, then give a verdict.')
    rows = [{"uid": "target", "text": "delete it, no backup, git can restore", "_score": 0.9}] + \
           [{"uid": f"t{i}", "text": tpl.format(p, b, p), "_score": 0.8 - i / 100}
            for i, (p, b) in enumerate([(f"/opt/Code/github.com/Soul-Brews-Studio/maw-js-{2400 + i}-x", ["detached", "alpha", f"fix/{2783 + i}-resolve-myname"][i % 3])
                                        for i in range(8)])] + \
           [{"uid": "other", "text": "The user sent a new message while you were working: ship the release", "_score": 0.5},
            {"uid": "other2", "text": "The user sent a new message while you were working: revert the bump", "_score": 0.4}]
    got = collapse(rows)
    assert [r["uid"] for r in got] == ["target", "t0", "other", "other2"]        # same opening, different words: kept
    assert got[1]["_dups"] == 7 and "_dups" not in got[0]
    assert near_key(rows[9]).startswith("ship the release") or "ship the release" in near_key(rows[9])


def test_semantic_reply_says_how_fresh_it_is(withvec):
    root, _, _ = withvec
    res = Relic5(root, duckdb.connect()).search("anything", vector=unit([1.0, 0.0, 0.0]))
    f = res["freshness"]
    assert f["index_built"] and f["vectors_at"] is None and f["vectors_pending"] is None   # no vectors.json: unknown, not 0
    assert res["collapsed"] == 0
    import json as _j
    _j.dump({"at": "2026-10-24T03:00:00+0700", "models": {M: {"m5": {"at": "x", "pending": 4}, "mba": {"at": "y", "pending": 1}}}},
            open(os.path.join(fts.search_dir(root), "vectors.json"), "w"))
    f = Relic5(root, duckdb.connect()).search("anything", vector=unit([1.0, 0.0, 0.0]))["freshness"]
    assert f["vectors_at"] == "2026-10-24T03:00:00+0700" and f["vectors_pending"] == 5
