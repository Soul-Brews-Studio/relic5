import json

from fastapi.testclient import TestClient

from relic5 import trace
from relic5.api import make_app
from relic5.doors import Doors

H = {"Authorization": "Bearer t"}
W = H | {"X-Relic5-Request": "1"}


def app(root):
    return TestClient(make_app(root, {"m5": "t"}, Doors({"m5": "t"}, enabled=False)))


def rpc(c, name, args):
    body = {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": name, "arguments": args}}
    r = c.post("/mcp", json=body, headers=H).json()["result"]
    return r, json.loads(r["content"][0]["text"])


def test_a_search_is_recorded_with_its_hits_and_chains_to_what_follows(root, monkeypatch):
    monkeypatch.setenv("RELIC5_WARM", "0")
    c = app(root)
    first = c.get("/api/search", params={"q": "hub"}, headers=H).json()
    t = first["trace"]
    assert len(t["id"]) == 10 and t["root"] == t["id"] and t["parent"] is None
    link = first["hits"][0]["link"]
    _, shown = rpc(c, "relic_show", {"id": link, "parent": t["id"]})        # open a hit from that search
    assert shown["trace"]["root"] == t["id"] and shown["trace"]["parent"] == t["id"]
    narrow = c.get("/api/search", params={"q": "hub white", "parent": shown["trace"]["id"]}, headers=H).json()
    assert narrow["trace"]["root"] == t["id"]
    c.get("/api/search", params={"q": "unrelated"}, headers=H)               # a new chain

    ch = c.get("/api/trace", params={"id": narrow["trace"]["id"]}, headers=H).json()
    assert [s["tool"] for s in ch["steps"]] == ["relic_search", "relic_show", "relic_search"]
    assert [s["depth"] for s in ch["steps"]] == [0, 1, 2] and ch["searches"] == 2 and ch["opened"] == 1
    assert ch["steps"][0]["top"][0]["link"] == link and ch["steps"][0]["args"] == {"query": "hub"}

    _, via_mcp = rpc(c, "relic_trace", {"id": t["id"]})
    assert via_mcp["root"] == t["id"] and len(via_mcp["steps"]) == 3
    _, recent = rpc(c, "relic_trace", {})
    assert recent["chains"][0]["query"] == "unrelated" and recent["chains"][1]["steps"] == 3
    body = {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "relic_trace", "arguments": {"id": "nope"}}}
    assert c.post("/mcp", json=body, headers=H).json()["result"]["isError"]


def test_access_log_pages_and_filters(root, monkeypatch):
    monkeypatch.setenv("RELIC5_WARM", "0")
    c = app(root)
    for q in ("hub", "nothingmatchesthis", "white", "hub"):
        c.get("/api/search", params={"q": q}, headers=H)
    c.get("/api/search", params={"q": "evalonly"}, headers=H | {"X-Relic5-Client": "eval"})
    p1 = c.get("/api/access", params={"limit": 2}, headers=H).json()
    assert [r["query"] for r in p1["rows"]] == ["hub", "white"] and p1["total"] == 5
    p2 = c.get("/api/access", params={"limit": 2, "before": p1["next_before"]}, headers=H).json()
    assert [r["query"] for r in p2["rows"]] == ["nothingmatchesthis", "hub"] and p2["next_before"] is None
    zero = c.get("/api/access", params={"zero": 1}, headers=H).json()
    assert [r["query"] for r in zero["rows"]] == ["nothingmatchesthis"]
    s = c.get("/api/asked", headers=H).json()
    assert s["searches"] == 4 and s["zero"] == 1 and s["zero_share"] == 0.25 and s["hours"][-1]["p95_ms"] is not None
    assert s["by_tool"][0] == {"tool": "relic_search", "n": 4}


def test_a_saved_search_runs_as_a_job_in_the_chain_it_came_from(root, monkeypatch):
    monkeypatch.setenv("RELIC5_WARM", "0")
    c = app(root)
    first = c.get("/api/search", params={"q": "hub", "limit": 1}, headers=H).json()
    assert c.post("/api/saved", json={"action": "add", "from": first["trace"]["id"]}, headers=H).status_code == 400   # no header
    sv = c.post("/api/saved", json={"action": "add", "from": first["trace"]["id"], "every": 30}, headers=W).json()
    assert sv["args"] == {"query": "hub", "limit": 1} and sv["every"] == 30 and sv["seen"] == 1
    ran = c.post("/api/saved", json={"action": "run", "id": sv["id"]}, headers=W).json()
    assert ran["runs"] == 1 and ran["last_hits"] == 1 and ran["last_new"] == 0      # the same top hit as when it was saved
    ch = c.get("/api/trace", params={"id": first["trace"]["id"]}, headers=H).json()
    assert [s["client"] for s in ch["steps"]][-1] == f"saved-search {sv['id']}" and ch["steps"][-1]["parent"] == first["trace"]["id"]
    jobs = [json.loads(l) for l in open(f"{root}/logs/jobs.jsonl")]
    assert jobs[-1]["verb"] == "saved-search" and "0 new" in jobs[-1]["message"]

    _, listed = rpc(c, "relic_saved", {})
    assert listed["saved"][0]["id"] == sv["id"]
    _, added = rpc(c, "relic_saved", {"action": "add", "query": "white", "args": {"repo": "neo"}, "every": 5})
    assert added["args"] == {"repo": "neo", "query": "white"}
    import time
    assert trace.run_due(root, lambda *a: (True, {"hits": []}, None), now=time.time() + 3600) == [sv["id"], added["id"]]
    assert c.post("/api/saved", json={"action": "remove", "id": sv["id"]}, headers=W).json() == {"removed": sv["id"]}
    assert [i["id"] for i in trace.saved(root)] == [added["id"]]


def test_an_agent_notes_what_it_found_and_mcp_tells_it_how(root, monkeypatch):
    monkeypatch.setenv("RELIC5_WARM", "0")
    c = app(root)
    init = c.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}}, headers=H).json()
    assert "relic_found" in init["result"]["instructions"] and "parent" in init["result"]["instructions"]
    _, s = rpc(c, "relic_search", {"query": "hub"})
    _, sh = rpc(c, "relic_show", {"id": s["hits"][0]["link"], "parent": s["trace"]["id"]})
    _, f = rpc(c, "relic_found", {"parent": sh["trace"]["id"], "goal": "where the hub runs", "how": "searched hub, opened the first hit",
                                  "found": "on white", "links": [s["hits"][0]["link"]]})
    assert f["noted"] and f["root"] == s["trace"]["id"] and f["searches"] == 1 and f["opened"] == 1 and f["steps"] == 3
    ch = c.get("/api/trace", params={"id": s["trace"]["id"]}, headers=H).json()
    assert ch["found"][0]["found"] == "on white" and ch["found"][0]["links"] == [s["hits"][0]["link"]]
    assert [x["tool"] for x in ch["steps"]][-1] == "relic_found" and ch["steps"][-1]["depth"] == 2
    _, lst = rpc(c, "relic_trace", {})
    assert lst["chains"][0]["goal"] == "where the hub runs" and lst["chains"][0]["found"] == "on white"
    body = {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "relic_found", "arguments": {"parent": "nope", "goal": "g", "found": "f"}}}
    assert c.post("/mcp", json=body, headers=H).json()["result"]["isError"]


def test_a_period_tells_what_was_asked_and_found_and_tags_label_it(root, monkeypatch):
    monkeypatch.setenv("RELIC5_WARM", "0")
    c = app(root)
    _, s = rpc(c, "relic_search", {"query": "hub"})
    rpc(c, "relic_search", {"query": "hub"})
    rpc(c, "relic_search", {"query": "nothingmatchesthis"})
    link = s["hits"][0]["link"]
    _, f = rpc(c, "relic_found", {"parent": s["trace"]["id"], "goal": "where the hub runs", "found": "white", "links": [link]})
    _, t = rpc(c, "relic_tag", {"target": link, "add": ["Hub", "#deploy", "ทดสอบ"], "note": "the answer"})
    assert t["tags"] == ["hub", "deploy", "ทดสอบ"]
    rpc(c, "relic_tag", {"target": link, "remove": ["deploy"]})
    _, one = rpc(c, "relic_tags", {"target": link})
    assert one["tags"] == ["hub", "ทดสอบ"] and one["notes"][0]["note"] == "the answer" and one["kind"] == "message"
    _, by = rpc(c, "relic_tags", {"tag": "hub"})
    assert [x["target"] for x in by["targets"]] == [link]
    body = {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "relic_tag", "arguments": {"target": link, "add": ["bad tag!"]}}}
    assert c.post("/mcp", json=body, headers=H).json()["result"]["isError"]

    import time
    today = time.strftime("%Y-%m-%d", time.gmtime(time.time() + 7 * 3600))   # a Bangkok day
    _, p = rpc(c, "relic_asked", {"since": today})
    assert p["top"][0]["query"] == "hub" and p["top"][0]["times"] == 2 and p["zero_hits"] == ["nothingmatchesthis"]
    assert p["found"][0]["found"] == "white" and {"tag": "hub", "n": 1} in p["tags"] and p["chains"]
    _, old = rpc(c, "relic_asked", {"since": "2020-01-01", "until": "2020-01-02"})
    assert old["searches"] == 0 and old["found"] == []
    acc = c.get("/api/access", params={"since": today, "tool": "relic_search"}, headers=H).json()
    assert len(acc["rows"]) == 3 and c.get("/api/access", params={"since": "nonsense"}, headers=H).status_code == 400
    assert c.get("/api/tags", headers=H).json()["tags"][0]["tag"] == "hub"


def test_the_searched_can_be_searched_and_a_link_leads_back_to_its_searches(root, monkeypatch):
    """Nat, 2026-10-27: "we should have search from the searched! and we can add relic link trace?", "relic tag it
    seems helper": past queries, found notes and tags are searchable; a link leads back to what returned, opened or cited it."""
    monkeypatch.setenv("RELIC5_WARM", "0")
    c = app(root)
    _, s = rpc(c, "relic_search", {"query": "hub"})
    link = s["hits"][0]["link"]
    _, sh = rpc(c, "relic_show", {"id": link, "parent": s["trace"]["id"]})
    rpc(c, "relic_found", {"parent": sh["trace"]["id"], "goal": "where the relic5 hub runs", "how": "searched hub",
                           "found": "on white", "links": [link]})
    rpc(c, "relic_tag", {"target": s["trace"]["id"], "add": ["deploy"]})
    rpc(c, "relic_tag", {"target": link, "add": ["answer"]})
    _, other = rpc(c, "relic_search", {"query": "unrelated"})

    _, by_word = rpc(c, "relic_searched", {"query": "white"})                    # a word only in the found note
    assert by_word["total"] == 1 and by_word["chains"][0]["root"] == s["trace"]["id"]
    g = by_word["chains"][0]
    assert g["found"][0]["found"] == "on white" and g["tags"] == ["deploy"] and "found note" in g["why"]
    _, by_tag = rpc(c, "relic_searched", {"query": "deploy"})                      # a word only in the tags
    assert [x["root"] for x in by_tag["chains"]] == [s["trace"]["id"]]
    _, back = rpc(c, "relic_searched", {"link": link})                             # the way back from the message
    assert back["chains"][0]["root"] == s["trace"]["id"] and back["tags"] == ["answer"]
    assert set(back["chains"][0]["why"]) >= {"returned", "opened", "cited"}
    assert other["trace"]["id"] not in [x["root"] for x in back["chains"]] or "unrelated" in back["chains"][-1]["queries"]
    api = c.get("/api/searched", params={"q": "relic5 hub"}, headers=H).json()
    assert "where the relic5 hub runs" in api["chains"][0]["queries"]      # a found note is logged with its goal as query
    assert c.get("/api/searched", headers=H).status_code == 400
    body = {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "relic_searched", "arguments": {}}}
    assert c.post("/mcp", json=body, headers=H).json()["result"]["isError"]
