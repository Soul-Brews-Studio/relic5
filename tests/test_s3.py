"""The whole hub on an S3 root (store.py): the test fixture copied to a fresh prefix in a real bucket, indexed there,
and asked through the API exactly as a disk hub is. Runs only with RELIC5_TEST_S3=s3://bucket/prefix and a key
(RELIC5_S3_KEY or ~/.config/relic5/s3-live); the prefix is removed afterwards."""
import json, os, uuid

import pytest

S3 = os.environ.get("RELIC5_TEST_S3")
pytestmark = pytest.mark.skipif(not S3, reason="RELIC5_TEST_S3 not set (an s3:// prefix in a bucket the key can write)")
H = {"Authorization": "Bearer t"}


@pytest.fixture
def s3root(root, monkeypatch, tmp_path):
    from relic5 import store as rfs
    monkeypatch.setenv("RELIC5_WARM", "0")
    monkeypatch.setenv("RELIC5_CACHE", str(tmp_path / "cache"))
    dst = f"{S3.rstrip('/')}/t-{uuid.uuid4().hex[:8]}"
    for d, _, fs in os.walk(root):
        for f in fs:
            p = os.path.join(d, f)
            rfs.write_bytes(dst + "/" + os.path.relpath(p, root), open(p, "rb").read())
    yield dst
    rfs.rmtree(dst)


def test_a_hub_on_s3_indexes_and_answers_like_one_on_a_disk(s3root):
    from fastapi.testclient import TestClient
    from relic5 import store as rfs
    from relic5.api import make_app
    from relic5.cli import main
    from relic5.doors import Doors

    main(["index", "--root", s3root])
    assert rfs.isfile(s3root + "/index/_search/current.json") and rfs.isfile(s3root + "/index/2026-10/manifest.json")
    c = TestClient(make_app(s3root, {"m5": "t"}, Doors({"m5": "t"}, enabled=False)))

    hub = c.get("/api/search", params={"q": "hub"}, headers=H).json()
    assert hub["hits"] and hub["hits"][0]["machines"] and hub["trace"]["id"]
    thai = c.get("/api/search", params={"q": "ค้นหา"}, headers=H).json()
    assert len(thai["hits"]) == 1                                   # ICU on S3: Thai inside words
    shown = c.get("/api/show", params={"id": hub["hits"][0]["link"], "parent": hub["trace"]["id"]}, headers=H).json()
    assert shown["target"]["text"]
    assert c.get("/api/sessions", headers=H).json()["sessions"]
    st = c.get("/api/status", headers=H).json()
    assert st["store"]["backend"]["kind"] == "s3" and st["rows"]["text"] > 0 and st["months"]["total"] >= 2

    # the logs: appended as objects, read back, chained
    ch = c.get("/api/trace", params={"id": hub["trace"]["id"]}, headers=H).json()
    assert [s["tool"] for s in ch["steps"]] == ["relic_search", "relic_show"]
    body = {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
            "params": {"name": "relic_tag", "arguments": {"target": hub["hits"][0]["link"], "add": ["s3"], "note": "on a bucket"}}}
    assert json.loads(c.post("/mcp", json=body, headers=H).json()["result"]["content"][0]["text"])["tags"] == ["s3"]
    assert c.get("/api/tags", params={"tag": "s3"}, headers=H).json()["targets"][0]["notes"][0]["note"] == "on a bucket"
    assert c.post("/api/saved", json={"action": "add", "from": hub["trace"]["id"]}, headers=H | {"X-Relic5-Request": "1"}).status_code == 200
    assert c.get("/api/saved", headers=H).json()["saved"]
    assert any(e["verb"] == "index" for e in c.get("/api/log", headers=H).json())

    # an artifact: bytes into the bucket and back out
    put = c.post("/api/artifact", params={"oracle": "neo-oracle", "filename": "a.svg", "title": "t"}, content=b"<svg/>", headers=H).json()
    assert c.get(f"/api/artifact/{put['id']}", headers=H).content == b"<svg/>"

    # S3 logs compact into chunks and still read the same
    log = s3root + "/logs/queries.jsonl"
    before = rfs.read_lines(log)
    assert rfs.compact(log, older_than=0) >= 2 and rfs.read_lines(log) == before


def test_a_disk_hub_mirrors_to_s3_and_verifies(root):
    from relic5 import mirror, store as rfs
    dst = f"{S3.rstrip('/')}/m-{uuid.uuid4().hex[:8]}"
    try:
        out = mirror.copy(root, dst)
        assert out["files"] > 0 and not out["errors"] and mirror.verify(root, dst)["ok"]
        assert mirror.copy(root, dst)["files"] == 0
    finally:
        rfs.rmtree(dst)
