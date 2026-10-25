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


def test_fast_lane_recount_keeps_publish_time(withvec):
    """vectors.json was written by the vector lane only, so pending read 0 for hours while new messages landed
    (2026-10-24: 0 shown, 1,062 real). The fast lane recounts it and leaves "at" (last publish) alone."""
    import json as _j
    from conftest import COLS, row, write_parquet
    root, keys, have = withvec
    con = duckdb.connect()
    vec.write_marks(root, con, published=True)
    p = os.path.join(fts.search_dir(root), "vectors.json")
    first = _j.load(open(p))
    before = sum(v["pending"] for v in first["models"][M].values())
    assert before >= len(keys) - len(have) and first["at"] == first["counted_at"]   # per machine: a shared key counts twice
    write_parquet(os.path.join(root, "parts/m7/text/2026-10.parquet"), COLS,   # a new file: the fixture's stay as they are
                  [row("a fresh line that has no vector yet", "2026-10-23T13:59:00.000Z", sid="s9-new")])
    Parts(root).index(con, log=lambda s: None)
    vec.write_marks(root, con, published=False)
    after = _j.load(open(p))
    assert after["at"] == first["at"] and sum(v["pending"] for v in after["models"][M].values()) == before + 1
    f = Relic5(root, duckdb.connect()).search("anything", vector=unit([1.0, 0.0, 0.0]))["freshness"]
    assert f["pending_counted_at"] == after["counted_at"]


def test_an_open_month_shard_rebuilds_only_the_open_table(withvec):
    """Every shard rebuilt both tables: 50 s of history for 100 October chunks (2026-10-24)."""
    root, keys, have = withvec
    con = duckdb.connect()
    oct_keys = [k for (k,) in con.execute(f"SELECT DISTINCT key FROM read_parquet('{root}/parts/*/text/2026-10.parquet')").fetchall()
                if k not in have]
    assert oct_keys, "the fixture has an October key without a vector"
    d = os.path.join(root, "vectors", M)
    con.execute(f"COPY (SELECT '{oct_keys[0]}' AS key, {unit([0.0, 0.1, 1.0])}::FLOAT[] AS vector) TO '{d}/m5-ane-new.parquet' (FORMAT parquet)")
    done = fts.build(root, con, log=lambda s: None, lane="vectors")
    assert done == [f"vec_{vec.slug(M)}_open"]
    assert vec.shard_months(root, M, con, Parts(root))["m5-ane-new.parquet"] == ["2026-10"]
    assert fts.build(root, con, log=lambda s: None, lane="vectors") == []                   # nothing new: nothing rebuilt


def test_parity_is_checked_once_a_day(tmp_path, monkeypatch):
    from relic5 import worker
    monkeypatch.setattr(worker, "PARITY", str(tmp_path / "parity.json"))
    assert not worker.parity_fresh(M, "ane")
    worker.parity_ok(M, "ane", 0.999)
    import time
    assert worker.parity_fresh(M, "ane") and not worker.parity_fresh(M, "mps")
    assert not worker.parity_fresh(M, "ane", now=time.time() + worker.PARITY_TTL_S + 1)


def test_missing_hands_memory_notes_to_the_worker(tmp_path):
    """Each memory note gets its own vector: missing() lists notes.parquet's keys beside the text stream's."""
    import duckdb
    import pyarrow as pa
    import pyarrow.parquet as pq
    d = tmp_path / "index" / "_memory"
    d.mkdir(parents=True)
    pq.write_table(pa.table({"key": ["n1", "n2"], "ts": ["2026-10-01", "2026-10-02"], "text": ["rule one", "decision two"]}), d / "notes.parquet")
    (tmp_path / "parts").mkdir()
    m = vec.missing(str(tmp_path), duckdb.connect(), "g--m@00000000", limit=10)
    assert m["pending"] == 2 and [r["key"] for r in m["rows"]] == ["n2", "n1"]
