import json, os

import pytest
from fastapi.testclient import TestClient

from relic5.api import make_app
from relic5.doors import Doors

H = {"Authorization": "Bearer tok-m5"}


@pytest.fixture
def client(root):
    tokens = {"m5": "tok-m5", "mba": "tok-mba"}
    return TestClient(make_app(root, tokens, Doors(tokens, enabled=False)))


def rpc(client, method, params=None, i=1, headers=H):
    body = {"jsonrpc": "2.0", "method": method, **({"id": i} if i is not None else {}), **({"params": params} if params else {})}
    return client.post("/mcp", json=body, headers=headers)


def test_token_on_every_route(client):
    for path in ("/health", "/api/status", "/api/search?q=hub"):
        assert client.get(path).status_code == 401
        assert client.get(path, headers={"Authorization": "Bearer wrong"}).status_code == 401
    assert rpc(client, "tools/list", headers={}).status_code == 401
    assert client.get("/health", headers={"Authorization": "Bearer tok-mba"}).json() == {"ok": True}


def test_loopback_gets_no_exemption(root):
    c = TestClient(make_app(root, {"m5": "t"}, Doors({"m5": "t"}, owner="nat@x", names={"white"})), base_url="http://127.0.0.1")
    assert c.get("/health").status_code == 401


def test_mcp_initialize_and_list(client):
    r = rpc(client, "initialize", {"protocolVersion": "2025-06-18"}).json()
    assert r["result"]["protocolVersion"] == "2025-06-18" and r["result"]["serverInfo"]["name"] == "relic5"
    names = [t["name"] for t in rpc(client, "tools/list").json()["result"]["tools"]]
    assert names == ["relic_search", "relic_show", "relic_sessions", "relic_session", "relic_trace", "relic_saved", "relic_asked", "relic_tag", "relic_tags", "relic_found", "relic_homes", "relic_status", "relic_artifact_put", "relic_artifacts"]
    assert rpc(client, "notifications/initialized", i=None).status_code == 202


def test_mcp_call(client):
    r = rpc(client, "tools/call", {"name": "relic_search", "arguments": {"query": "ภาษาไทย"}}).json()["result"]
    assert len(json.loads(r["content"][0]["text"])["hits"]) == 1
    bad = rpc(client, "tools/call", {"name": "relic_search", "arguments": {"query": "x", "typo": 1}}).json()["result"]
    assert bad["isError"] and "unknown argument" in bad["content"][0]["text"]
    sem = rpc(client, "tools/call", {"name": "relic_search", "arguments": {"query": "hub", "semantic": True}}).json()["result"]
    assert "keyword hits" in json.loads(sem["content"][0]["text"])["note"]          # no vector: keyword, said out loud
    bad = rpc(client, "tools/call", {"name": "relic_search", "arguments": {"query": "x", "vector": [1, 0]}}).json()["result"]
    assert bad["isError"] and "only apply with semantic" in bad["content"][0]["text"]
    gone = rpc(client, "tools/call", {"name": "relic_chain", "arguments": {}}).json()["result"]
    assert gone["isError"]
    assert rpc(client, "tools/call", {"name": "nope"}).json()["error"]["code"] == -32602
    assert rpc(client, "nope/nope").json()["error"]["code"] == -32601
    assert client.post("/mcp", content=b"{", headers=H).json()["error"]["code"] == -32700


def test_get_routes(client):
    r = client.get("/api/search", params={"q": "hub", "limit": "1"}, headers=H)
    assert r.status_code == 200 and len(r.json()["hits"]) == 1
    uid = r.json()["hits"][0]["uid"]
    assert client.get("/api/show", params={"id": uid}, headers=H).status_code == 200
    assert client.get("/api/show", params={"id": "0" * 32}, headers=H).status_code == 404
    assert client.get("/api/search", params={"q": "x", "with": "raw"}, headers=H).status_code == 400
    assert client.get("/api/sessions", headers=H).json()["total"] == 2
    assert client.get("/api/status", headers=H).json()["layout"]["unit"] == "month"


def test_read_only(client):
    for path in ("/api/search", "/api/status", "/health"):
        assert client.post(path, headers=H).status_code == 405


def test_refuses_no_tokens(root):
    with pytest.raises(SystemExit):
        make_app(root, {})                                  # no tokens and no doors: nobody could call it


def test_ui_login_cookie(client):
    assert client.get("/").status_code == 401                              # no token, no page
    assert client.get("/login", params={"t": "nope"}).status_code == 401
    r = client.get("/login", params={"t": "tok-mba"}, follow_redirects=False)
    assert r.status_code == 303 and "httponly" in r.headers["set-cookie"].lower() and "samesite=strict" in r.headers["set-cookie"].lower()
    assert "relic5 hub" in client.get("/").text                            # the cookie now opens the page
    assert client.get("/api/status").status_code == 200
    assert isinstance(client.get("/api/log").json(), list)


def test_ui_assets(client):
    """The React build's files are served from web/assets with long caching; nothing else under that path is."""
    import re
    client.get("/login", params={"t": "tok-mba"})
    page = client.get("/").text
    names = re.findall(r'assets/([\w.-]+\.(?:js|css))', page)
    assert names, "the built index.html names its bundle"
    for n in names:
        r = client.get("/assets/" + n)
        assert r.status_code == 200 and "immutable" in r.headers["cache-control"]
    assert client.get("/assets/nope.js").status_code == 404
    assert client.get("/assets/..%2Fapi.py").status_code == 404
    assert client.get("/assets/index.html").status_code == 404                # only listed types


def test_a_query_parameter_cannot_pick_the_tool(client):
    """?tool= is an ordinary (unknown) argument, never the tool the route runs."""
    client.get("/login", params={"t": "tok-mba"})
    r = client.get("/api/status", params={"tool": "relic_show"})
    assert r.status_code == 400 or "you" in r.json()          # status ran (or refused the argument); show never did
    assert "target" not in r.text


def test_status_says_which_door(client):
    assert client.get("/api/status", headers={"Authorization": "Bearer tok-mba"}).json()["you"] == "token:mba"
    r = rpc(client, "tools/call", {"name": "relic_status", "arguments": {}}).json()["result"]
    assert json.loads(r["content"][0]["text"])["you"] == "token:m5"


def test_connected_devices(client):
    """/api/clients: each door + client that called, with its tools; the client is the header, else the User-Agent."""
    client.get("/login", params={"t": "tok-mba"})
    client.get("/api/status", headers={"X-Relic5-Client": "relic-feeder"})
    client.get("/api/search", params={"q": "hub"}, headers={"User-Agent": "claude-code/2.1.308 (darwin)"})
    rpc(client, "tools/call", {"name": "relic_status", "arguments": {}})
    devs = {(d["door"], d["client"]): d for d in client.get("/api/clients").json()["devices"]}
    assert devs[("token:mba", "relic-feeder (http)")]["tools"] == {"relic_status": 1}
    assert devs[("token:mba", "claude-code (http)")]["tools"] == {"relic_search": 1}
    assert any(door == "token:m5" and c.endswith("(mcp)") for door, c in devs)
    assert all(d["calls_24h"] >= 1 and d["last"] for d in devs.values())


@pytest.fixture
def hub_with_tokens(root, tmp_path):
    from relic5.tokens import Tokens
    t = Tokens(str(tmp_path / "tokens.json"), str(tmp_path / "legacy"))

    class Local(Doors):        # the test client is not 127.0.0.1: no bearer = the loopback door; tokens checked for real
        def door(self, server, client, host, bearer):
            return super().door(server, client, host, bearer) if bearer else "loopback"
    return TestClient(make_app(root, t, Local(t, enabled=False))), t


def test_tokens_from_the_ui(hub_with_tokens):
    c, t = hub_with_tokens
    J = {"X-Relic5-Request": "1", "Host": "127.0.0.1"}
    assert c.get("/api/tokens", headers={"Host": "127.0.0.1"}).json() == []            # loopback door: allowed
    r = c.post("/api/tokens", json={"action": "new", "name": "phone", "expires": "90d"}, headers=J).json()
    secret = r["token"]
    assert r["name"] == "phone" and len(secret) > 30 and t.check(secret) == "phone"   # works as a token at once
    assert [x["name"] for x in c.get("/api/tokens", headers={"Host": "127.0.0.1"}).json()] == ["phone"]
    assert secret not in open(t.path).read()                                          # stored hashed only
    # a token never mints a token
    assert c.post("/api/tokens", json={"action": "new", "name": "x"}, headers={"Authorization": f"Bearer {secret}", "X-Relic5-Request": "1"}).status_code == 403
    # a cross-site form post (no header, not JSON) is refused
    assert c.post("/api/tokens", data="action=new&name=evil", headers={"Host": "127.0.0.1", "Content-Type": "text/plain"}).status_code == 400
    assert c.post("/api/tokens", json={"action": "new", "name": "phone"}, headers=J).status_code == 400   # exists
    new = c.post("/api/tokens", json={"action": "rotate", "name": "phone", "grace": "1h"}, headers=J).json()["token"]
    assert t.check(new) == "phone" and t.check(secret) == "phone"                     # the old one lasts the grace hour
    assert c.post("/api/tokens", json={"action": "revoke", "name": "phone"}, headers=J).json() == {"name": "phone", "action": "revoke"}
    assert t.check(new) is None and c.get("/api/tokens", headers={"Host": "127.0.0.1"}).json() == []


def test_tokens_show_when_last_used(hub_with_tokens):
    c, t = hub_with_tokens
    J = {"X-Relic5-Request": "1", "Host": "127.0.0.1"}
    secret = c.post("/api/tokens", json={"action": "new", "name": "laptop"}, headers=J).json()["token"]
    row = lambda: next(x for x in c.get("/api/tokens", headers={"Host": "127.0.0.1"}).json() if x["name"] == "laptop")
    assert "last_used" not in row()                                                   # never used yet
    assert c.get("/api/status", headers={"Authorization": f"Bearer {secret}", "cf-connecting-ip": "203.0.113.9"}).status_code == 200
    r = row()
    assert r["last_used"] and r["last_path"] == "/api/status" and r["last_via"] == "direct"   # cf header only trusted from loopback
    assert r["last_ip"] != "203.0.113.9"


def test_big_answers_are_gzipped(client):
    import glob, os
    import relic5
    js = sorted(glob.glob(os.path.join(os.path.dirname(relic5.__file__), "web", "assets", "index-*.js")))[0]
    r = client.get("/assets/" + os.path.basename(js), headers={**H, "Accept-Encoding": "gzip"})
    assert r.status_code == 200 and r.headers.get("content-encoding") == "gzip"     # the page's JS: gzipped
    small = client.get("/health", headers={**H, "Accept-Encoding": "gzip"})
    assert small.headers.get("content-encoding") is None                            # under 1 KB: as it is


def test_every_request_is_timed_and_written(client, root):
    from relic5 import perf
    perf.RING.clear(); perf._PENDING.clear()
    client.get("/api/status", headers=H)
    client.get("/api/search", params={"q": "hub", "t": "secret"}, headers=H)
    assert client.get("/api/status").status_code == 401                       # refused before timing: not logged
    p = client.get("/api/perf", headers=H).json()
    routes = {r["route"]: r for r in p["routes"]}
    assert routes["/api/status"]["count"] == 1 and routes["/api/search"]["p50"] is not None
    assert "secret" not in json.dumps(p) and p["recent"][0]["route"] == "/api/search" and p["rss_mb"] > 0
    assert perf.flush(root) == 2 and len(open(os.path.join(root, "logs", "requests", sorted(os.listdir(os.path.join(root, "logs", "requests")))[-1])).read().splitlines()) == 2


def test_heavy_answers_are_served_stale_while_they_refresh(monkeypatch):
    import threading, time
    from relic5 import swr
    monkeypatch.setenv("RELIC5_SWR", "1")
    swr.clear()
    calls, gate = [], threading.Event()
    def slow():
        calls.append(1)
        if len(calls) > 1:
            gate.wait(5)
        return len(calls)
    assert swr.get("k", 0.05, slow) == 1 and swr.get("k", 0.05, slow) == 1 and len(calls) == 1   # fresh: memory
    time.sleep(0.06)
    t = time.time()
    assert swr.get("k", 0.05, slow) == 1 and time.time() - t < 0.5                           # stale: at once
    gate.set()
    for _ in range(50):
        if swr.get("k", 60, slow) == 2:
            break
        time.sleep(0.02)
    assert swr.get("k", 60, slow) == 2 and len(calls) == 2                                    # refreshed behind


def test_each_query_is_timed_under_its_name_and_route(client):
    from relic5 import perf
    perf.QRING.clear()
    client.get("/api/search", params={"q": "hub"}, headers=H)
    client.get("/api/tail", headers=H)
    qs = {q["name"]: q for q in client.get("/api/perf", headers=H).json()["queries"]}
    assert any(n.startswith(("Index.query", "Relic5.")) for n in qs if n != "Relic5.tail") and "Relic5.tail" in qs
    assert "/api/tail" in qs["Relic5.tail"]["routes"] and qs["Relic5.tail"]["sql"].startswith("SELECT")


def test_status_counts_sessions_once_indexed(client, root):
    from relic5.cli import main
    main(["index", "--root", root])
    assert client.get("/api/status", headers=H).json()["rows"]["sessions"] > 0
