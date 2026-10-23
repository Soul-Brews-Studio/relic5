import json, os
from datetime import datetime, timezone

import duckdb

from relic5.parts import Parts, this_month
from relic5.status import status

NOW = datetime(2026, 10, 23, 14, 0, tzinfo=timezone.utc)


def test_bangkok_month():
    assert this_month(datetime(2026, 9, 30, 17, 30, tzinfo=timezone.utc)) == "2026-10"   # 00:30 in Bangkok


def test_index_writes_month_manifests(root):
    p = Parts(root)
    assert p.months() == ["2026-09", "2026-10"] and p.stale() == ["2026-09", "2026-10"]
    assert p.index(duckdb.connect(), log=lambda s: None, now=NOW) == ["2026-09", "2026-10"]
    man = json.load(open(os.path.join(root, "index/2026-10/manifest.json")))
    assert man["sealed"] is False and man["streams"]["text"]["rows"] == 6          # 7 pushed, the shared one folds
    assert man["streams"]["text"]["machines"]["mba"]["rows"] == 1
    assert json.load(open(os.path.join(root, "index/2026-09/manifest.json")))["sealed"] is True
    assert p.stale() == [] and p.index(duckdb.connect(), log=lambda s: None) == []   # nothing changed: nothing rewritten


def test_part_files_ignored(root):
    open(os.path.join(root, "parts/m5/text/.2026-11.parquet.part"), "w").write("half")
    assert "2026-11" not in Parts(root).months()


def test_status(root):
    Parts(root).index(duckdb.connect(), log=lambda s: None, now=NOW)
    s = status(root, now=NOW)
    assert s["layout"]["unit"] == "month" and s["months"]["total"] == 2 and s["months"]["open"] == "2026-10"
    assert s["machines"]["m5"]["text"]["newest_ts"] == "2026-10-23T11:30:00.000Z"
    assert s["rows"]["text"] == 7 and s["watermarks"]["vectors"]["pending"] == 7
    assert any("mba: no meta" in w for w in s["warnings"])


def test_status_warns_on_version_mismatch(root):
    for m, v in (("m5", "26.10.23-alpha.1858"), ("mba", "26.10.23-alpha.1308")):
        json.dump({"relic-scan": v, "relic-extract": "x", "relic5-push": "y"}, open(os.path.join(root, f"parts/{m}/_versions.json"), "w"))
    s = status(root, now=NOW)
    assert s["versions"]["mba"]["relic-scan"] == "26.10.23-alpha.1308"
    assert [w for w in s["warnings"] if w.startswith("relic-scan differs")] and not [w for w in s["warnings"] if w.startswith("relic-extract differs")]


def test_a_part_pushed_late_with_an_old_mtime_is_still_indexed(root):
    p = Parts(root)
    con = duckdb.connect()
    p.index(con, log=lambda s: None, now=NOW)
    assert p.stale() == []
    from conftest import COLS, row, write_parquet
    f = os.path.join(root, "parts/mba/text/2026-10.parquet")
    write_parquet(f, COLS, [row("a late mba row", "2026-10-23T08:00:00.000Z"), row("another", "2026-10-23T08:01:00.000Z")])
    os.utime(f, (1_600_000_000, 1_600_000_000))                 # rsync -a: the sender's (old) mtime
    assert p.stale() == ["2026-10"]
    assert p.index(con, log=lambda s: None, now=NOW) == ["2026-10"]
    assert json.load(open(os.path.join(root, "index/2026-10/manifest.json")))["streams"]["text"]["machines"]["mba"]["rows"] == 2


def test_status_shows_sync_and_warns_on_mismatch(root):
    json.dump({"line": "2026-10-23 23:10 SYNC OK text|1"}, open(os.path.join(root, "parts/m5/_sync.json"), "w"))
    json.dump({"line": "2026-10-23 23:10 SYNC MISMATCH mba: text|2 hub: text|1"}, open(os.path.join(root, "parts/mba/_sync.json"), "w"))
    s = status(root, now=NOW)
    assert s["freshness"]["machines"]["m5"]["sync"].endswith("SYNC OK text|1")
    assert any("SYNC MISMATCH" in w for w in s["warnings"])
