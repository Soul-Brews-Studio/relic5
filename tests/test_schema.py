"""schema.py: the Lance tables as typed classes, and the indexer refusing a table that drifts from its class."""
import pyarrow as pa


def test_every_built_table_matches_its_class(root):
    import lancedb, os
    from relic5.cli import main
    from relic5.fts import current, search_dir
    from relic5.schema import LayerRow, check
    main(["index", "--root", root])
    cur = current(root)
    assert cur
    for name, rel in cur.items():
        t = lancedb.connect(os.path.join(search_dir(root), rel.split("/")[0])).open_table(rel.split("/")[1].removesuffix(".lance"))
        assert check(name, t.schema) == [], name
        if not name.startswith("vec_"):
            assert t.search().limit(1).to_pydantic(LayerRow)[0].month


def test_a_drifted_table_is_named():
    from relic5.schema import check
    s = pa.schema([("uid", pa.string()), ("msgkey", pa.string()), ("chunk", pa.string()), ("month", pa.string()), ("extra", pa.int64())])
    bad = check("prose_open", s)
    assert any("chunk is string" in b for b in bad) and any("column extra" in b for b in bad)
    vec = pa.schema([("uid", pa.string()), ("msgkey", pa.string()), ("chunk", pa.int64()), ("month", pa.string()),
                     ("vector", pa.list_(pa.float32(), 768)), ("chars", pa.int64())])
    assert check("vec_m_open", vec) == []


def test_a_hit_reads_as_a_model():
    from relic5.schema import LayerRow
    r = LayerRow.of({"uid": "u", "msgkey": "k", "chunk": 0, "month": "2026-10", "text": "hi", "_score": 3.2, "link": "x"})
    assert r.text == "hi" and not hasattr(r, "_score")
