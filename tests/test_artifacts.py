"""artifacts.py and its doors: an agent keeps a file for an oracle; the page reads it back, sandboxed when it can run."""
import base64

import pytest
from fastapi.testclient import TestClient

from relic5 import artifacts
from relic5.api import make_app
from relic5.doors import Doors
from relic5.query import UsageError

PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==")


def test_put_dedups_and_lists_newest_first(tmp_path):
    root = str(tmp_path)
    a = artifacts.put(root, "neo-oracle", "portrait", ".png", PNG, prompt="draw neo")
    b = artifacts.put(root, "neo-oracle", "again", "png", PNG)
    assert b["id"] == a["id"] and b["dedup"] is True and a["kind"] == "image" and a["prompt"] == "draw neo"
    c = artifacts.put(root, "neo-oracle", "scene", "html", b"<h1>hi</h1>")
    lst = artifacts.listing(root, "neo-oracle")
    assert [r["id"] for r in lst["artifacts"]] == [c["id"], a["id"]] and lst["oracles"] == {"neo-oracle": 2}
    for bad in [("", "x.png", PNG), ("neo-oracle", "x.exe", PNG), ("../etc", "x.png", PNG), ("neo-oracle", "x.png", b"")]:
        with pytest.raises(UsageError):
            artifacts.put(root, bad[0], "t", bad[1].rsplit(".", 1)[1], bad[2])


def test_mcp_put_and_http_read(tmp_path):
    c = TestClient(make_app(str(tmp_path), {"m5": "t"}, Doors({"m5": "t"}, enabled=False)))
    H = {"Authorization": "Bearer t"}
    call = {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "relic_artifact_put", "arguments": {
        "oracle": "neo-oracle", "title": "a scene", "ext": "html", "text": "<script>alert(1)</script>", "prompt": "make a scene"}}}
    r = c.post("/mcp", json=call, headers=H).json()["result"]
    assert not r.get("isError"), r
    aid = r["structuredContent"]["id"] if "structuredContent" in r else __import__("json").loads(r["content"][0]["text"])["id"]
    f = c.get(f"/api/artifact/{aid}", headers=H)
    assert f.status_code == 200 and f.text.startswith("<script>")
    assert f.headers["content-security-policy"].startswith("sandbox") and f.headers["x-content-type-options"] == "nosniff"
    up = c.post("/api/artifact?oracle=neo-oracle&filename=p.png&title=p", content=PNG, headers=H).json()
    assert up["kind"] == "image"
    assert "content-security-policy" not in c.get(f"/api/artifact/{up['id']}", headers=H).headers
    assert [x["kind"] for x in c.get("/api/artifacts?oracle=neo-oracle", headers=H).json()["artifacts"]] == ["image", "web"]
    assert c.get("/api/artifact/../../etc", headers=H).status_code == 404
