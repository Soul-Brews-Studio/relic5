"""claude.ai's connector flow end to end (oauth.py): register, authorize with PKCE behind one of the hub's tokens,
trade the code, call /mcp, refresh, and the public host showing only the MCP door."""
import base64, hashlib, secrets
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient

CB = "https://claude.ai/api/mcp/auth_callback"


@pytest.fixture
def hub(root, tmp_path, monkeypatch):
    monkeypatch.setenv("RELIC5_OAUTH_JSON", str(tmp_path / "oauth.json"))
    monkeypatch.setenv("RELIC5_PUBLIC_URL", "https://relic5.example.com")
    import importlib
    from relic5 import oauth
    importlib.reload(oauth)
    from relic5 import api
    importlib.reload(api)
    from relic5.doors import Doors
    return TestClient(api.make_app(root, {"m5": "secret-m5"}, Doors({"m5": "secret-m5"}, enabled=False)), base_url="https://relic5.example.com")


def pkce():
    v = secrets.token_urlsafe(48)
    return v, base64.urlsafe_b64encode(hashlib.sha256(v.encode()).digest()).rstrip(b"=").decode()


def test_claude_ai_connects_through_oauth(hub):
    c = hub
    r = c.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    assert r.status_code == 401 and "resource_metadata=" in r.headers["www-authenticate"]
    meta = c.get("/.well-known/oauth-protected-resource").json()
    assert meta["resource"] == "https://relic5.example.com/mcp"
    asm = c.get("/.well-known/oauth-authorization-server").json()
    assert asm["code_challenge_methods_supported"] == ["S256"]

    assert c.post("/oauth/register", json={"redirect_uris": ["https://evil.example/cb"]}).status_code == 400
    assert c.post("/oauth/register", json={"redirect_uris": ["https://chatgpt.com.evil.example/cb"]}).status_code == 400
    assert c.post("/oauth/register", json={"redirect_uris": ["https://chatgpt.com/connector_platform_oauth_redirect"],
                                           "client_name": "ChatGPT"}).status_code == 201   # ChatGPT's connector
    reg = c.post("/oauth/register", json={"redirect_uris": [CB], "client_name": "Claude"}).json()
    v, ch = pkce()
    q = {"response_type": "code", "client_id": reg["client_id"], "redirect_uri": CB, "code_challenge": ch,
         "code_challenge_method": "S256", "state": "xyz"}
    page = c.get("/oauth/authorize", params=q)
    assert page.status_code == 200 and "Connect <b>Claude</b>" in page.text
    assert c.post("/oauth/authorize", data=q | {"token": "wrong"}).status_code == 401
    r = c.post("/oauth/authorize", data=q | {"token": "secret-m5"}, follow_redirects=False)
    assert r.status_code == 302 and r.headers["location"].startswith(CB)
    got = parse_qs(urlparse(r.headers["location"]).query)
    assert got["state"] == ["xyz"]
    code = got["code"][0]

    form = {"grant_type": "authorization_code", "code": code, "client_id": reg["client_id"], "redirect_uri": CB}
    assert c.post("/oauth/token", data=form | {"code_verifier": "nope"}).status_code == 400   # and the code is spent
    r = c.post("/oauth/authorize", data=q | {"token": "secret-m5"}, follow_redirects=False)
    code = parse_qs(urlparse(r.headers["location"]).query)["code"][0]
    tok = c.post("/oauth/token", data=form | {"code": code, "code_verifier": v}).json()
    assert tok["token_type"] == "Bearer" and tok["access_token"].startswith("r5o_")
    assert c.post("/oauth/token", data=form | {"code": code, "code_verifier": v}).status_code == 400   # once

    H = {"Authorization": f"Bearer {tok['access_token']}"}
    tools = c.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"}, headers=H).json()
    assert any(t["name"] == "relic_search" for t in tools["result"]["tools"])
    assert c.get("/api/status", headers=H).status_code == 404            # the public host: MCP and OAuth only
    assert c.get("/", headers=H).status_code == 404

    new = c.post("/oauth/token", data={"grant_type": "refresh_token", "refresh_token": tok["refresh_token"], "client_id": reg["client_id"]}).json()
    assert new["access_token"] != tok["access_token"]
    assert c.post("/oauth/token", data={"grant_type": "refresh_token", "refresh_token": tok["refresh_token"]}).status_code == 400   # rotated

    from relic5 import oauth
    assert oauth.revoke(reg["client_id"])
    assert c.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"}, headers={"Authorization": f"Bearer {new['access_token']}"}).status_code == 401


def test_an_oauth_token_opens_only_mcp_on_the_hub_itself(hub, monkeypatch):
    from relic5 import oauth
    reg = oauth.register({"redirect_uris": [CB]})
    q = {"response_type": "code", "client_id": reg["client_id"], "redirect_uri": CB, "code_challenge": pkce()[1], "code_challenge_method": "S256"}
    v, ch = pkce()
    code = parse_qs(urlparse(oauth.approve(q | {"code_challenge": ch}, "token:m5")).query)["code"][0]
    tok = oauth.token({"grant_type": "authorization_code", "code": code, "client_id": reg["client_id"], "redirect_uri": CB, "code_verifier": v})
    c = TestClient(hub.app, base_url="http://testserver")
    assert c.get("/api/status", headers={"Authorization": f"Bearer {tok['access_token']}"}).status_code == 401


def test_two_public_names_each_describe_themselves(root, tmp_path, monkeypatch):
    monkeypatch.setenv("RELIC5_OAUTH_JSON", str(tmp_path / "oauth.json"))
    monkeypatch.setenv("RELIC5_PUBLIC_URL", "https://mcp.new.example, https://old.example.com")
    import importlib
    from relic5 import api
    importlib.reload(api)
    from relic5.doors import Doors
    app = api.make_app(root, {"m5": "secret-m5"}, Doors({"m5": "secret-m5"}, enabled=False))
    for base in ("https://mcp.new.example", "https://old.example.com"):
        c = TestClient(app, base_url=base)
        assert c.get("/.well-known/oauth-protected-resource").json()["resource"] == base + "/mcp"   # its own name
        assert c.get("/api/status", headers={"Authorization": "Bearer secret-m5"}).status_code == 404   # /mcp only
        assert c.get("/favicon.ico").status_code == 200


def test_public_host_never_offers_discord(hub):
    """Discord stays off the public MCP (discord.py; Nat, 2026-10-26): even a hub token on the public host gets no
    `with: discord`, and the same token on the hub's own address does."""
    from fastapi.testclient import TestClient

    def with_enum(c):
        r = c.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"}, headers={"authorization": "Bearer secret-m5"})
        t = next(t for t in r.json()["result"]["tools"] if t["name"] == "relic_search")
        return t["inputSchema"]["properties"]["with"]["enum"]

    assert "discord" not in with_enum(hub)
    assert "discord" in with_enum(TestClient(hub.app, base_url="http://testserver"))
    r = hub.post("/mcp", json={"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                               "params": {"name": "relic_search", "arguments": {"query": "x", "with": "discord"}}},
                 headers={"authorization": "Bearer secret-m5"})
    assert r.json()["result"]["isError"] and "public MCP" in r.json()["result"]["content"][0]["text"]
