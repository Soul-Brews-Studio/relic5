"""sealday.py: reconcile a closed month end to end: sealing, blocked, reconciled (record + fingerprint + job event),
an amendment after a reseal, the overdue warning; and bin/relic5-push sending the seal receipts."""
import hashlib, json, os, subprocess
from datetime import datetime, timezone

import duckdb
import pytest

from conftest import COLS, row, write_parquet
from relic5 import sealday
from relic5.parts import Parts

PART = "parts/mba/text/2026-09.parquet"


def sha(p):
    return hashlib.sha256(open(p, "rb").read()).hexdigest()


def months_json(root, machine, entries):
    d = os.path.join(root, "parts", machine, "meta")
    os.makedirs(d, exist_ok=True)
    json.dump({"version": 1, "months": entries}, open(os.path.join(d, "months.json"), "w"))


def receipt(root, machine, month, keys, parts):
    d = os.path.join(root, "parts", machine, "meta")
    os.makedirs(d, exist_ok=True)
    json.dump({"version": 1, "machine": machine, "months": {month: {"sealed_keys": keys, "parts": parts}}},
              open(os.path.join(d, "receipts.json"), "w"))


def part_receipt(root, rel):
    p = os.path.join(root, rel)
    return {"bytes": os.path.getsize(p), "sha256": sha(p)}


@pytest.fixture
def hub(root, monkeypatch):
    monkeypatch.setenv("RELIC5_NOW", "2026-10-24T03:00:00Z")      # 2026-09 is closed, 2026-10 open
    Parts(root).index(duckdb.connect(), log=lambda s: None)
    months_json(root, "m5", [{"month": "2026-10", "sealed": False}])   # m5 has no rows in 2026-09: nothing to reconcile
    return root


def test_sealing_blocked_reconciled_amended(hub):
    root = hub
    months_json(root, "mba", [{"month": "2026-09", "sealed": False}, {"month": "2026-10", "sealed": False}])
    st = sealday.reconcile(root, "2026-09")
    assert st["state"] == "sealing" and st["waiting"] == ["mba: has not sealed 2026-09"]
    assert sealday.reconcile(root, "2026-10")["state"] == "open"

    months_json(root, "mba", [{"month": "2026-09", "sealed": True, "sealed_keys": "k1", "sealed_rows": 5}])
    assert sealday.reconcile(root, "2026-09")["waiting"] == ["mba: no receipt for this seal yet (next push)"]

    receipt(root, "mba", "2026-09", "k1", {"text": {"bytes": 1, "sha256": "0" * 64}})
    st = sealday.reconcile(root, "2026-09")
    assert st["state"] == "blocked" and "the hub's copy differs" in st["problems"][0]

    receipt(root, "mba", "2026-09", "k1", {"text": part_receipt(root, PART)})
    st = sealday.reconcile(root, "2026-09")
    assert st["state"] == "reconciled" and len(st["fingerprint"]) == 16
    day = sealday.load(root, "2026-09")
    assert day["machines"]["mba"]["rows"] == {"text": 1} and day["folded"]["text"] == 1 and day["amendments"] == []
    log = [json.loads(l) for l in open(os.path.join(root, "logs/jobs.jsonl"))]
    assert log[-1]["verb"] == "seal-day" and log[-1]["message"].startswith("2026-09 reconciled: 1 machine, 1 messages folded")
    assert sealday.reconcile(root, "2026-09")["fingerprint"] == st["fingerprint"]       # nothing new: no second record

    # a late row: relic-scan reseals, relic-extract re-cuts, the push brings the new receipt
    write_parquet(os.path.join(root, PART), COLS, [row("hub from the mba", "2026-09-01T00:00:00.000Z", sid="s3-cccc"),
                                                  row("a late one", "2026-09-30T23:00:00.000Z", sid="s3-cccc")])
    Parts(root).index(duckdb.connect(), log=lambda s: None)
    months_json(root, "mba", [{"month": "2026-09", "sealed": True, "sealed_keys": "k2", "sealed_rows": 6, "resealed": 1}])
    receipt(root, "mba", "2026-09", "k2", {"text": part_receipt(root, PART)})
    st2 = sealday.reconcile(root, "2026-09")
    day = sealday.load(root, "2026-09")
    assert st2["state"] == "reconciled" and st2["amendments"] == 1 and day["fingerprint"] == st["fingerprint"]   # history kept
    a = day["amendments"][0]
    assert (a["machine"], a["sealed_from"], a["sealed_to"], a["delta_rows"]) == ("mba", "k1", "k2", 1)
    assert json.loads(open(os.path.join(root, "logs/jobs.jsonl")).readlines()[-1])["message"].startswith("2026-09 amended: mba resealed, +1 rows")


def test_run_summary_and_overdue(hub):
    root = hub
    months_json(root, "mba", [{"month": "2026-09", "sealed": False}])
    states = {s["month"]: s["state"] for s in sealday.run(root)}
    assert states == {"2026-09": "sealing", "2026-10": "open"}
    assert [s["month"] for s in sealday.summary(root)] == sorted(states)
    late = sealday.overdue(sealday.summary(root), datetime(2026, 10, 5, tzinfo=timezone.utc))
    assert len(late) == 1 and late[0].startswith("seal day 2026-09: still sealing 3+ days")
    assert sealday.overdue(sealday.summary(root), datetime(2026, 10, 2, tzinfo=timezone.utc)) == []    # inside the grace


def test_push_sends_receipts(tmp_path):
    from test_push import FAKE_SSH, REPO
    src, hub, scan, fb = (tmp_path / d for d in ("extract", "hub", "scan/meta", "fb"))
    for d in (src / "text", hub, scan, fb):
        d.mkdir(parents=True)
    (src / "text/2026-09.parquet").write_bytes(b"sealed month bytes")
    (src / "text/2026-10.parquet").write_bytes(b"open month")
    json.dump({"months": [{"month": "2026-09", "sealed": True, "sealed_keys": "k1", "sealed_rows": 3},
                          {"month": "2026-10", "sealed": False, "sealed_keys": ""}]}, open(scan / "months.json", "w"))
    (fb / "ssh").write_text(FAKE_SSH)
    (fb / "ssh").chmod(0o755)
    e = dict(os.environ, PATH=f"{fb}:{os.environ['PATH']}", FAKE_HUB_HOME=str(hub), RELIC5_SRC=str(src),
             RELIC5_HUB="hub", RELIC5_MACHINE="m5", RELIC5_NEW_MACHINE="1", RELIC5_SCAN=str(tmp_path / "scan"), HOME=str(tmp_path))
    for _ in range(2):                                                    # the second push answers from the cache
        r = subprocess.run([os.path.join(REPO, "bin/relic5-push")], env=e, capture_output=True, text=True)
        assert r.returncode == 0, r.stderr
    rec = json.load(open(hub / "relic5/parts/m5/meta/receipts.json"))
    assert list(rec["months"]) == ["2026-09"]                             # sealed months only
    assert rec["months"]["2026-09"]["parts"]["text"] == {"bytes": 18, "sha256": hashlib.sha256(b"sealed month bytes").hexdigest()}
    assert json.load(open(src / ".receipts-cache.json"))


def test_month_recap_route_and_flag(hub):
    from fastapi.testclient import TestClient
    from relic5 import sealday as SD
    from relic5.api import make_app
    from relic5.doors import Doors
    tokens = {"mba": "tok-mba"}
    client = TestClient(make_app(hub, tokens, Doors(tokens, enabled=False)))
    client.get("/login", params={"t": "tok-mba"})
    assert client.get("/api/month-recap", params={"month": "2026/09"}).status_code == 400
    assert client.get("/api/month-recap", params={"month": "2026-09"}).status_code == 404
    os.makedirs(os.path.join(hub, "recaps"), exist_ok=True)
    open(os.path.join(hub, "recaps/2026-09.md"), "w").write("# 2026-09 in relic5\n> fingerprint `abc`\n")
    r = client.get("/api/month-recap", params={"month": "2026-09"})
    assert r.status_code == 200 and r.text.startswith("# 2026-09 in relic5") and "markdown" in r.headers["content-type"]
    months_json(hub, "mba", [{"month": "2026-09", "sealed": False}])
    SD.run(hub)
    assert {m["month"]: m["recap"] for m in SD.summary(hub)}["2026-09"] is True


def test_overdue_months_for_one_reason_are_one_line(hub):
    from relic5 import sealday as SD
    states = [{"month": m, "state": "sealing", "waiting": [f"mba: has not sealed {m}"], "problems": [], "fingerprint": None,
               "reconciled_at": None, "amendments": 0, "recap": False} for m in ("2026-07", "2026-08", "2026-09")]
    late = SD.overdue(states, datetime(2026, 10, 20, tzinfo=timezone.utc))
    assert late == ["seal day 3 months (2026-07 .. 2026-09): still sealing 3+ days after it ended: mba: has not sealed the month"]


def test_a_copy_turns_the_live_checks_off(hub):
    from relic5.status import status
    months_json(hub, "mba", [{"month": "2026-09", "sealed": False}])
    sealday.run(hub)
    live = status(hub, now=datetime(2026, 10, 20, tzinfo=timezone.utc))["warnings"]
    assert any(w.startswith("seal day") for w in live) and any(w.startswith("no backup yet") for w in live)
    json.dump({"of": "white", "snapshot": "20261024-014647", "at": "2026-10-24T01:46:47Z"}, open(os.path.join(hub, "COPY.json"), "w"))
    s = status(hub, now=datetime(2026, 10, 20, tzinfo=timezone.utc))
    assert s["copy"]["of"] == "white"
    assert not [w for w in s["warnings"] if w.startswith(("seal day", "no backup")) or "last push" in w]
