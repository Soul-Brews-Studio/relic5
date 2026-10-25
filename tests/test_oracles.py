"""oracles.py: who owns a vault, which sections count as soul/learnings/retros, and prompts quoted from the notes."""
import json

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq

from relic5 import oracles
from relic5.query import Relic5


def hub(tmp_path):
    root = tmp_path / "hub"
    for m in ("m5", "white"):
        (root / "parts" / m / "meta").mkdir(parents=True)
        (root / "parts" / m / "vault").mkdir(parents=True)
    vs = [{"id": 0, "name": "neo-oracle", "path": "/opt/Code/github.com/laris-co/neo-oracle/ψ", "kind": "own", "notes": 9,
           "newest_ms": 1, "sections": {"memory/learnings": 2, "soul-brews-studio/arra-oracle-v3": 5, "memory/resonance": 1, "memory/retrospectives": 1}},
          {"id": 1, "name": "neo-oracle", "path": "/x/neo-oracle/ψ", "kind": "link", "notes": 99, "sections": {}}]
    json.dump({"vaults": vs}, open(root / "parts/m5/meta/vaults.json", "w"))
    json.dump({"vaults": vs[:1]}, open(root / "parts/white/meta/vaults.json", "w"))
    rows = [("k1", 0, "2026-10-01", "memory/learnings", "memory/learnings/a.md", "A lesson", "Keep the hub private."),
            ("k2", 0, "2026-10-02", "memory/learnings", "wt/memory/learnings/a.md", "A lesson", "Keep the hub private."),   # same note, second folder
            ("k3", 0, "2026-10-03", "memory/resonance", "memory/resonance/soul.md", "Who I am", "---\nx: 1\n---\n# I am neo\nI keep the fleet honest."),
            ("k4", 0, "2026-10-04", "soul-brews-studio/arra-oracle-v3", "soul-brews-studio/arra-oracle-v3/x.md", "copied", "not the soul"),
            ("k5", 0, "2026-10-05", "memory/retrospectives", "memory/retrospectives/r.md", "Retro", "It went fine.")]
    t = pa.table({"msgkey": [r[0] for r in rows], "chunk": [r[1] for r in rows], "ts": [r[2] for r in rows], "section": [r[3] for r in rows],
                  "path": [r[4] for r in rows], "title": [r[5] for r in rows], "text": [r[6] for r in rows], "cat": ["neo-oracle"] * len(rows)})
    pq.write_table(t, root / "parts/m5/vault/notes.parquet")
    return Relic5(str(root), duckdb.connect())


def test_listing_folds_copies_and_counts_sections_by_folder(tmp_path):
    r = hub(tmp_path)
    o = oracles.listing(r)["oracles"]
    assert [x["name"] for x in o] == ["neo-oracle"]                       # the link copy (99 notes) does not speak for it
    assert o[0]["notes"] == 9 and o[0]["machines"] == ["m5", "white"]
    assert (o[0]["soul"], o[0]["learnings"], o[0]["retros"]) == (1, 2, 1)   # "soul-brews-studio/…" is not the soul


def test_portrait_quotes_notes_once_with_their_paths(tmp_path):
    p = oracles.portrait(hub(tmp_path), "neo-oracle")
    assert [x["title"] for x in p["learnings"]] == ["A lesson"]           # one note in two folders is one note
    assert p["soul"][0]["text"] == "I am neo I keep the fleet honest."     # frontmatter and heading marks gone
    assert "(ψ/memory/resonance/soul.md)" in p["prompts"]["character"] and "not the soul" not in p["prompts"]["character"]
    assert "It went fine." in p["prompts"]["enlighten"]
    assert oracles.portrait(hub(tmp_path / "b"), "nobody")["error"]
