import json

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
    assert names == ["relic_search", "relic_show", "relic_sessions", "relic_session", "relic_status"]
    assert rpc(client, "notifications/initialized", i=None).status_code == 202


def test_mcp_call(client):
    r = rpc(client, "tools/call", {"name": "relic_search", "arguments": {"query": "ภาษาไทย"}}).json()["result"]
    assert len(json.loads(r["content"][0]["text"])["hits"]) == 1
    bad = rpc(client, "tools/call", {"name": "relic_search", "arguments": {"query": "x", "typo": 1}}).json()["result"]
    assert bad["isError"] and "unknown argument" in bad["content"][0]["text"]
    sem = rpc(client, "tools/call", {"name": "relic_search", "arguments": {"query": "x", "semantic": True}}).json()["result"]
    assert sem["isError"] and "embed milestone" in sem["content"][0]["text"]
    gone = rpc(client, "tools/call", {"name": "relic_trace", "arguments": {}}).json()["result"]
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
        make_app(root, {}, Doors({}, enabled=False))


def test_ui_login_cookie(client):
    assert client.get("/").status_code == 401                              # no token, no page
    assert client.get("/login", params={"t": "nope"}).status_code == 401
    r = client.get("/login", params={"t": "tok-mba"}, follow_redirects=False)
    assert r.status_code == 303 and "httponly" in r.headers["set-cookie"].lower() and "samesite=strict" in r.headers["set-cookie"].lower()
    assert "relic5 hub" in client.get("/").text                            # the cookie now opens the page
    assert client.get("/api/status").status_code == 200
    assert isinstance(client.get("/api/log").json(), list)


def test_status_says_which_door(client):
    assert client.get("/api/status", headers={"Authorization": "Bearer tok-mba"}).json()["you"] == "token:mba"
    r = rpc(client, "tools/call", {"name": "relic_status", "arguments": {}}).json()["result"]
    assert json.loads(r["content"][0]["text"])["you"] == "token:m5"
