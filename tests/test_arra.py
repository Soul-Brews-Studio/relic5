"""ARRA Oracle Studio reading relic5 (arra.py): the arra-oracle API shapes Studio's pages read, its page's origin let
in, and the tailscale-serve door."""
import pytest
from fastapi.testclient import TestClient

from relic5.api import make_app
from relic5.doors import Doors

H = {"Authorization": "Bearer tok-m5"}
STUDIO = "https://studio.buildwithoracle.com"


@pytest.fixture
def client(root):
    tokens = {"m5": "tok-m5"}
    return TestClient(make_app(root, tokens, Doors(tokens, enabled=False)))


def test_studio_reads_the_shapes_it_expects(client):
    assert client.get("/arra/api/health", headers=H).json()["server"] == "relic5"
    st = client.get("/arra/api/stats", headers=H).json()
    assert {"total", "by_type", "vector"} <= st.keys()
    feed = client.get("/arra/api/feed?limit=10", headers=H).json()
    assert {"events", "total", "active_oracles"} <= feed.keys()
    lst = client.get("/arra/api/list?limit=5", headers=H).json()
    assert lst["results"] and {"id", "type", "content", "source_file", "concepts"} <= lst["results"][0].keys()
    assert lst["results"][0]["type"] in ("principle", "learning", "retro")
    s = client.get("/arra/api/search?q=hub&limit=5", headers=H).json()
    assert s["query"] == "hub" and isinstance(s["results"], list)
    m = client.get("/arra/api/map3d", headers=H).json()
    assert {"documents", "total"} <= m.keys()                       # empty without a vector index, never an error
    g = client.get("/arra/api/graph", headers=H).json()
    assert {"nodes", "links"} <= g.keys()
    assert client.get("/arra/api/auth/status", headers=H).json()["authenticated"] is True
    assert client.post("/arra/api/learn", json={"pattern": "x"}, headers=H).status_code == 403   # read-only


def test_studio_origin_is_let_in_and_others_are_not(client):
    pre = client.options("/arra/api/stats", headers={"Origin": STUDIO, "Access-Control-Request-Method": "GET"})
    assert pre.status_code == 204 and pre.headers["access-control-allow-origin"] == STUDIO
    assert pre.headers["access-control-allow-private-network"] == "true"
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
