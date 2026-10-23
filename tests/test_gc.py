import os

from relic5 import gc


def test_gc_is_a_dry_run_and_guards_sole_copies(tmp_path):
    root = str(tmp_path)
    sd = os.path.join(root, "index/_search")
    for g in ("20261023-100000-1", "20261023-110000-2"):
        os.makedirs(os.path.join(sd, g, "t.lance"))
        open(os.path.join(sd, g, "t.lance", "x"), "w").write("x" * 100)
    open(os.path.join(sd, "current.json"), "w").write('{"prose_open": "20261023-110000-2/t.lance"}')
    for a in ("relic3-import-20261023", "something-else"):
        os.makedirs(os.path.join(root, "attic", a))
        open(os.path.join(root, "attic", a, "f"), "w").write("y" * 50)
    r = gc.report(root)
    assert [(g["gen"], g["live"]) for g in r["generations"]] == [("20261023-100000-1", False), ("20261023-110000-2", True)]
    assert {a["item"]: a["safe"] for a in r["attic"]} == {"relic3-import-20261023": True, "something-else": False}
    assert r["reclaimable_bytes"] == 150 and r["dry_run"]
    assert os.path.exists(os.path.join(sd, "20261023-100000-1")) and os.path.exists(os.path.join(root, "attic/something-else"))
