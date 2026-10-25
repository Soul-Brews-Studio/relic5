"""family.py: lineage keeps canonical rows and real parents; team counts sessions per repo per Bangkok day."""
import json

from relic5 import family


def test_lineage_canonical_parents_and_roots(tmp_path):
    d = tmp_path / "parts" / "m5" / "meta"
    d.mkdir(parents=True)
    rows = [{"child": "mother", "origin": "standalone", "parent": None, "date": "2026-01-01", "canonical": True, "commits": 9},
            {"child": "neo", "origin": "bud", "parent": "mother", "date": "2026-03-01", "canonical": True, "awakened": True},
            {"child": "neo", "origin": "bud", "parent": "mother", "date": "2026-03-02", "canonical": False},   # a worktree copy
            {"child": "orphan", "origin": "bud", "parent": "gone-oracle", "date": "2026-04-01", "canonical": True}]
    json.dump(rows, open(d / "lineage.json", "w"))
    L = family.lineage(str(tmp_path))
    by = {n["name"]: n for n in L["nodes"]}
    assert len(L["nodes"]) == 3 and by["neo"]["parent"] == "mother" and by["neo"]["awakened"]
    assert by["orphan"]["parent"] is None and by["orphan"]["parent_named"] == "gone-oracle"   # parent not on record: no edge
    assert L["roots"] == ["mother"] and by["mother"]["children"] == 1 and L["newest_birth"] == "2026-04-01"
    assert family.lineage(str(tmp_path / "none"))["nodes"] == []
