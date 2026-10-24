"""seals.py: relic-scan's month seals on the hub: record, reseal, re-cut, verify, status."""
import json, os

import duckdb

from conftest import COLS, row, write_parquet
from relic5 import seals
from relic5.parts import Parts
from relic5.status import status


def months_json(root, machine, entries):
    d = os.path.join(root, "parts", machine, "meta")
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "months.json"), "w") as f:
        json.dump({"version": 1, "months": entries}, f)


def sealed(month, keys, rows, resealed=0):
    return {"month": month, "sealed": True, "sealed_at": "2026-10-24T02:41:47Z", "sealed_keys": keys, "sealed_rows": rows, "resealed": resealed}


def test_record_reseal_recut_verify(root):
    con = duckdb.connect()
    Parts(root).index(con, log=lambda s: None)
    months_json(root, "mba", [sealed("2026-09", "k1", 10), {"month": "2026-10", "sealed": False, "sealed_keys": ""}])
    ev, v = seals.update(root, log=lambda s: None)
    assert ev == [] and v == {"at": v["at"], "checked": 1, "problems": []}
    rec = seals.load(root)["mba"]["2026-09"]
    assert rec["sealed_keys"] == "k1" and rec["held"]["text"][2] == 1                 # the part's rows as the hub holds them
    assert status(root)["seals"]["machines"]["mba"]["sealed"] == 1

    # a late row: relic-scan reseals, relic-extract re-cuts, the push brings both
    write_parquet(os.path.join(root, "parts/mba/text/2026-09.parquet"), COLS,
                  [row("hub from the mba", "2026-09-01T00:00:00.000Z", sid="s3-cccc"), row("a late one", "2026-09-30T23:00:00.000Z", sid="s3-cccc")])
    months_json(root, "mba", [sealed("2026-09", "k2", 11, resealed=1)])
    ev, v = seals.update(root, log=lambda s: None)
    assert ev == ["month 2026-09 resealed on mba, +1 rows (resealed 1)"] and v["problems"] == []
    log = [json.loads(l) for l in open(os.path.join(root, "logs/jobs.jsonl"))]
    assert log[-1]["verb"] == "seal" and "resealed on mba" in log[-1]["message"]

    # the part changes behind the seal (no reseal): verify catches it before the next index records it
    write_parquet(os.path.join(root, "parts/mba/text/2026-09.parquet"), COLS, [row("only one now", "2026-09-01T00:00:00.000Z")])
    v = seals.verify(root)
    assert v["problems"] == ["mba 2026-09 text: 1 rows, sealed with 2"]
    assert any(w.startswith("seal: mba 2026-09 text") for w in status(root)["warnings"])
    ev, v = seals.update(root, log=lambda s: None)                                       # recorded as a re-cut, then clean
    assert ev == ["month 2026-09 on mba: parts re-cut under an unchanged seal"] and v["problems"] == []


def test_machine_without_seals_and_a_missing_part(root):
    assert seals.update(root, log=lambda s: None) == ([], {"at": seals.verify(root)["at"], "checked": 0, "problems": []})
    months_json(root, "mba", [sealed("2026-09", "k1", 10)])
    seals.update(root, log=lambda s: None)
    os.remove(os.path.join(root, "parts/mba/text/2026-09.parquet"))
    assert seals.verify(root)["problems"] == ["mba 2026-09 text: part missing"]


def test_retire_a_machine_moved_to_the_attic(root):
    """m5-nat, 2026-10-24: its parts went to the attic, its seal records stayed and verify said 'part missing'."""
    import shutil
    months_json(root, "mba", [sealed("2026-09", "k1", 10)])
    seals.update(root, log=lambda s: None)
    shutil.move(os.path.join(root, "parts/mba"), os.path.join(root, "attic-mba"))
    missing = seals.verify(root)["problems"]
    assert missing and all(p.startswith("mba 2026-09 ") and p.endswith("part missing") for p in missing)
    assert seals.retire(root, "mba", "moved to the attic") == 1
    assert "mba" not in seals.load(root) and seals.verify(root)["problems"] == []
    kept = json.load(open(os.path.join(root, "index/_seals/retired.json")))
    (k, v), = kept.items()
    assert k.startswith("mba@") and v["why"] == "moved to the attic" and v["months"]["2026-09"]["sealed_keys"] == "k1"
    assert seals.retire(root, "mba", "again") == 0
