import json

from fastapi.testclient import TestClient

from relic5 import selfknow
from relic5.api import make_app
from relic5.doors import Doors
from relic5.status import status

H = {"Authorization": "Bearer t"}


def test_queries_are_logged_and_summarised(root):
    c = TestClient(make_app(root, {"m5": "t"}, Doors({"m5": "t"}, enabled=False)))
    for q in ("hub", "hub", "nothingmatchesthis"):
        assert c.get("/api/search", params={"q": q}, headers=H).status_code == 200
    body = {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "relic_search", "arguments": {"query": "white"}}}
    c.post("/mcp", json=body, headers=H)
    rows = [json.loads(l) for l in open(f"{root}/logs/queries.jsonl")]
    assert [r["query"] for r in rows] == ["hub", "hub", "nothingmatchesthis", "white"] and rows[0]["door"] == "token:m5"
    assert rows[0]["mode"] == "keyword" and rows[0]["hits"] > 0 and rows[2]["hits"] == 0 and rows[0]["vector"] is False
    q = c.get("/api/queries", headers=H).json()
    assert q["top"][0] == {"query": "hub", "n": 2} and q["zero_hits"][0]["query"] == "nothingmatchesthis" and q["running"] == []


def test_store_and_resources_in_status(root):
    s = status(root)
    assert s["store"]["parts"]["m5"]["text"] > 0 and s["store"]["disk"]["free"] > 0 and s["resources"]["load"]
    selfknow.record_size(root)
    selfknow.record_size(root)                       # once a day
    assert len(open(f"{root}/logs/sizes.jsonl").readlines()) == 1
