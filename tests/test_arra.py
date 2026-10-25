"""ARRA Oracle Studio reading relic5 (arra.py): the arra-oracle API shapes Studio's pages read, its page's origin let
in, and the tailscale-serve door."""
import pytest
from fastapi.testclient import TestClient

from relic5.api import make_app
from relic5.doors import Doors

H = {"Authorization": "Bearer tok-m5"}
STUDIO = "https://studio.buildwithoracle.com"


NOTE_COLS = ["key", "msgkey", "chunk", "ts", "cat", "vault", "path", "section", "title", "text"]


@pytest.fixture
def client(root):
    from conftest import write_parquet
    import os
    write_parquet(os.path.join(root, "parts/m5/vault/notes.parquet"), NOTE_COLS, [
        {"key": "k1", "msgkey": "n1", "chunk": 0, "ts": "2026-10-20T00:00:00Z", "cat": "neo-oracle", "vault": "neo", "section": "memory/learnings",
         "path": "memory/learnings/hub.md", "title": "hub", "text": "the hub keeps every session"},
        {"key": "k2", "msgkey": "n2", "chunk": 0, "ts": "2026-10-21T00:00:00Z", "cat": "neo-oracle", "vault": "neo", "section": "memory/retrospectives",
         "path": "memory/retrospectives/day.md", "title": "day", "text": "what went well on the hub"},
        {"key": "k3", "msgkey": "n3", "chunk": 0, "ts": "2026-10-22T00:00:00Z", "cat": "neo-oracle", "vault": "neo", "section": "memory/resonance",
         "path": "memory/resonance/soul.md", "title": "soul", "text": "I am neo"},
    ])
    tokens = {"m5": "tok-m5"}
    return TestClient(make_app(root, tokens, Doors(tokens, enabled=False)))


def test_studio_reads_the_shapes_it_expects(client):
    assert client.get("/arra/api/health", headers=H).json()["server"] == "relic5"
    st = client.get("/arra/api/stats", headers=H).json()
    assert st["total"] == 3 and st["by_type"] == {"learning": 1, "retro": 1, "principle": 1}   # the ψ notes
    assert client.get("/arra/api/list?type=retro", headers=H).json()["results"][0]["source_file"] == "memory/retrospectives/day.md"
    assert client.get("/arra/api/file?path=memory/learnings/hub.md", headers=H).text == "the hub keeps every session"
    feed = client.get("/arra/api/feed?limit=10", headers=H).json()
    assert {"events", "total", "active_oracles"} <= feed.keys()
    lst = client.get("/arra/api/list?limit=5", headers=H).json()
    assert lst["results"] and {"id", "type", "content", "source_file", "concepts"} <= lst["results"][0].keys()
    assert lst["results"][0]["type"] in ("principle", "learning", "retro")
    s = client.get("/arra/api/search?q=hub&limit=5", headers=H).json()
    assert {d["id"] for d in s["results"]} == {"n1", "n2"}
    m = client.get("/arra/api/map3d", headers=H).json()
    assert {"documents", "total"} <= m.keys()                       # empty without a vector index, never an error
    g = client.get("/arra/api/graph", headers=H).json()
    assert {"nodes", "links"} <= g.keys()
    assert client.get("/arra/api/sessions", headers=H).json()["sessions"] is not None
    assert {"traces", "total", "hasMore"} <= client.get("/arra/api/traces", headers=H).json().keys()
    assert client.get("/arra/api/traces/nope", headers=H).status_code == 404
    assert {"files", "total"} <= client.get("/arra/api/inbox", headers=H).json().keys()
    assert client.get("/arra/api/supersede", headers=H).json() == {"supersessions": [], "total": 0}
    assert {"searches", "learnings"} <= client.get("/arra/api/session/stats?since=0", headers=H).json().keys()
    assert client.get("/arra/api/auth/status", headers=H).json()["authenticated"] is True
    assert client.post("/arra/api/learn", json={"pattern": "x"}, headers=H).status_code == 403   # read-only


def test_studio_origin_is_let_in_and_others_are_not(client):
    pre = client.options("/arra/api/stats", headers={"Origin": STUDIO, "Access-Control-Request-Method": "GET"})
    assert pre.status_code == 204 and pre.headers["access-control-allow-origin"] == STUDIO
    assert pre.headers["access-control-allow-private-network"] == "true"
    feed = client.options("/arra/api/list", headers={"Origin": "https://feed.buildwithoracle.com", "Access-Control-Request-Method": "GET"})
    assert feed.status_code == 204                                          # the other ui-oracle apps share the picker
    assert client.options("/arra/api/list", headers={"Origin": "https://evil.buildwithoracle.com.example"}).status_code == 403
    r = client.get("/arra/api/stats", headers=H | {"Origin": STUDIO})
    assert r.headers["access-control-allow-origin"] == STUDIO
    assert client.options("/arra/api/stats", headers={"Origin": "https://evil.example"}).status_code == 403
    assert "access-control-allow-origin" not in client.get("/arra/api/stats", headers=H | {"Origin": "https://evil.example"}).headers
    assert client.get("/arra/api/stats").status_code == 401                 # no door, no data


def test_tailscale_serve_door():
    d = Doors({}, owner="nat@x", names={"white.example.ts.net"}, whois=lambda ip: {"node": "m5.example.ts.net", "login": "nat@x"})
    assert d.served("100.64.0.9", "nat@x", "white.example.ts.net") == "tailnet:m5"
    assert d.served("100.64.0.9", "someone@else", "white.example.ts.net") is None   # the header must name the owner
    assert d.served("203.0.113.9", "nat@x", "white.example.ts.net") is None         # only a tailnet address
    assert d.served("100.64.0.9", "nat@x", "evil.example") is None                  # Host must name the hub
    other = Doors({}, owner="nat@x", names={"white.example.ts.net"}, whois=lambda ip: {"node": "x", "login": "eve@y"})
    assert other.served("100.64.0.9", "nat@x", "white.example.ts.net") is None       # tailscaled has the last word
