"""oauth.py: OAuth 2.1 for a claude.ai custom connector (Nat, 2026-10-25: "can we make cf tunnel? ... can we connect
using claude.ai?"; asked and confirmed: tunnel + claude.ai connector). claude.ai cannot send a fixed Bearer token; it
registers itself (RFC 7591), sends the person to /oauth/authorize, and trades a code for a token with PKCE (S256).

  /.well-known/oauth-protected-resource      the resource (/mcp) and its authorization server (RFC 9728)
  /.well-known/oauth-authorization-server    the endpoints (RFC 8414)
  POST /oauth/register                       a client, only with redirect URIs on claude.ai / claude.com, or ChatGPT's
                                             (chatgpt.com / openai.com: Nat, 2026-10-25 "connect relic5 to chatgpt too")
  GET|POST /oauth/authorize                  the approve page: approving needs one of the hub's own tokens
                                             (Settings > Access tokens), so only the hub's owner can let a client in
  POST /oauth/token                          authorization_code (PKCE) and refresh_token grants

Access tokens last 7 days, refresh tokens 90 and rotate on use; only their sha256 is kept, in oauth.json beside
tokens.json. A token from here opens the door "oauth:<client name>" and is good for /mcp only (api.py).
"""
import base64, hashlib, html, json, os, secrets, threading, time
from urllib.parse import urlencode, urlparse

from .types_ import Json

PATH = os.path.expanduser(os.environ.get("RELIC5_OAUTH_JSON") or os.path.join(
    os.path.dirname(os.path.expanduser(os.environ.get("RELIC5_TOKENS_JSON", "~/.config/relic5/tokens.json"))), "oauth.json"))
REDIRECT_HOSTS = {"claude.ai", "claude.com", "chatgpt.com", "openai.com"}
ACCESS_S, REFRESH_S, CODE_S = 7 * 86400, 90 * 86400, 600
_LOCK = threading.Lock()


def sha(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()


def _load() -> Json:
    try:
        d: Json = json.load(open(PATH))
    except (OSError, ValueError):
        d = {}
    for k in ("clients", "codes", "access", "refresh"):
        d.setdefault(k, {})
    return d


def _save(d: Json) -> None:
    now = time.time()
    for k in ("codes", "access", "refresh"):   # expired entries go
        d[k] = {h: v for h, v in d[k].items() if v.get("exp", 0) > now}
    os.makedirs(os.path.dirname(PATH), exist_ok=True)
    tmp = PATH + ".tmp"
    with open(tmp, "w") as f:
        json.dump(d, f, indent=1)
    os.chmod(tmp, 0o600)
    os.replace(tmp, PATH)


def redirect_ok(uri: str) -> bool:
    u = urlparse(uri)
    if os.environ.get("RELIC5_OAUTH_LOCAL_REDIRECT") == "1" and u.scheme == "http" and u.hostname in ("127.0.0.1", "localhost"):
        return True   # tests and a local MCP inspector only
    return u.scheme == "https" and (u.hostname in REDIRECT_HOSTS or any((u.hostname or "").endswith("." + h) for h in REDIRECT_HOSTS))


def metadata(base: str) -> Json:
    return {"issuer": base, "authorization_endpoint": f"{base}/oauth/authorize", "token_endpoint": f"{base}/oauth/token",
            "registration_endpoint": f"{base}/oauth/register", "response_types_supported": ["code"],
            "grant_types_supported": ["authorization_code", "refresh_token"], "code_challenge_methods_supported": ["S256"],
            "token_endpoint_auth_methods_supported": ["none"], "scopes_supported": ["relic5"]}


def resource(base: str) -> Json:
    return {"resource": f"{base}/mcp", "authorization_servers": [base], "scopes_supported": ["relic5"],
            "bearer_methods_supported": ["header"], "resource_name": "relic5"}


class OAuthError(Exception):
    def __init__(self, error: str, description: str, status: int = 400) -> None:
        super().__init__(description)
        self.error, self.description, self.status = error, description, status

    def body(self) -> Json:
        return {"error": self.error, "error_description": self.description}


def register(body: Json) -> Json:
    uris = body.get("redirect_uris") or []
    if not isinstance(uris, list) or not uris or not all(isinstance(u, str) and redirect_ok(u) for u in uris):
        raise OAuthError("invalid_redirect_uri", "redirect_uris must be https URIs on claude.ai, claude.com, chatgpt.com or openai.com")
    name = str(body.get("client_name") or "claude.ai")[:80]
    cid = "c_" + secrets.token_urlsafe(16)
    with _LOCK:
        d = _load()
        d["clients"][cid] = {"name": name, "redirect_uris": uris, "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
        _save(d)
    return {"client_id": cid, "client_name": name, "redirect_uris": uris, "grant_types": ["authorization_code", "refresh_token"],
            "response_types": ["code"], "token_endpoint_auth_method": "none", "client_id_issued_at": int(time.time())}


def client(cid: str) -> Json | None:
    c: Json | None = _load()["clients"].get(cid)
    return c


def check_authorize(q: dict[str, str]) -> Json:
    """The authorize request's own checks, before anyone is asked. -> the client."""
    c = client(q.get("client_id", ""))
    if not c:
        raise OAuthError("invalid_client", "unknown client_id: register first")
    if q.get("redirect_uri") not in c["redirect_uris"]:
        raise OAuthError("invalid_request", "redirect_uri is not one the client registered")
    if q.get("response_type") != "code":
        raise OAuthError("unsupported_response_type", "response_type must be code")
    if q.get("code_challenge_method") != "S256" or not q.get("code_challenge"):
        raise OAuthError("invalid_request", "PKCE with S256 is required")
    return c


def page(q: dict[str, str], c: Json, error: str = "") -> str:
    """The approve page: what asks, what it gets, and a field for one of the hub's tokens."""
    e = html.escape
    hidden = "".join(f'<input type="hidden" name="{e(k)}" value="{e(v)}">' for k, v in q.items() if k != "token")
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Connect to relic5</title><style>
body{{margin:0;min-height:100dvh;display:grid;place-items:center;background:#0a0a0f;color:#e8e8ef;font:15px/1.55 system-ui,-apple-system,sans-serif}}
main{{width:min(440px,calc(100vw - 32px));background:#12121a;border:1px solid #23232f;border-radius:16px;padding:28px}}
h1{{margin:0 0 6px;font-size:20px}} p{{margin:0 0 14px;color:#a8a8b8}} b{{color:#e8e8ef}}
label{{display:block;margin:18px 0 6px;font-weight:600}} input[type=password]{{box-sizing:border-box;width:100%;min-height:44px;padding:10px 12px;border-radius:10px;border:1px solid #2e2e3c;background:#0a0a0f;color:#e8e8ef;font:14px ui-monospace,monospace}}
button{{margin-top:18px;width:100%;min-height:44px;border:0;border-radius:10px;background:#64b5f6;color:#0a0a0f;font-weight:700;font-size:15px;cursor:pointer}}
.err{{color:#ff8a80;margin-top:12px}} small{{display:block;margin-top:14px;color:#77778a}}</style></head><body><main>
<h1>Connect <b>{e(c['name'])}</b> to relic5</h1>
<p>It will be able to search and read every machine's Claude Code and Codex history on this hub, through the MCP tools, until you revoke it.</p>
<form method="post" action="/oauth/authorize">{hidden}
<label for="t">A relic5 token</label><input id="t" name="token" type="password" autocomplete="off" required autofocus placeholder="from Settings, Access tokens">
{f'<p class="err" role="alert">{e(error)}</p>' if error else ''}
<button type="submit">Approve</button></form>
<small>Only someone who holds one of this hub's tokens can approve. Redirects back to {e(urlparse(q.get('redirect_uri', '')).hostname or '')}.</small>
</main></body></html>"""


def approve(q: dict[str, str], who: str) -> str:
    """The owner approved: a one-time code for the client. -> the redirect URL."""
    c = check_authorize(q)
    code = secrets.token_urlsafe(32)
    with _LOCK:
        d = _load()
        d["codes"][sha(code)] = {"client_id": q["client_id"], "redirect_uri": q["redirect_uri"], "challenge": q["code_challenge"],
                                 "by": who, "client": c["name"], "exp": time.time() + CODE_S}
        _save(d)
    out = {"code": code} | ({"state": q["state"]} if q.get("state") else {})
    sep = "&" if "?" in q["redirect_uri"] else "?"
    return q["redirect_uri"] + sep + urlencode(out)


def _issue(d: Json, cid: str, name: str, by: str) -> Json:
    access, refresh = "r5o_" + secrets.token_urlsafe(32), "r5r_" + secrets.token_urlsafe(32)
    now = time.time()
    d["access"][sha(access)] = {"client_id": cid, "client": name, "by": by, "exp": now + ACCESS_S}
    d["refresh"][sha(refresh)] = {"client_id": cid, "client": name, "by": by, "exp": now + REFRESH_S}
    return {"access_token": access, "token_type": "Bearer", "expires_in": ACCESS_S, "refresh_token": refresh, "scope": "relic5"}


def token(form: dict[str, str]) -> Json:
    g = form.get("grant_type")
    with _LOCK:
        d = _load()
        if g == "authorization_code":
            rec = d["codes"].pop(sha(form.get("code", "")), None)
            _save(d)   # a code is spent even when the rest fails
            if not rec or rec["exp"] < time.time():
                raise OAuthError("invalid_grant", "the code is unknown, used or expired")
            if rec["client_id"] != form.get("client_id") or rec["redirect_uri"] != form.get("redirect_uri"):
                raise OAuthError("invalid_grant", "client_id or redirect_uri differ from the authorize request")
            v = form.get("code_verifier", "")
            calc = base64.urlsafe_b64encode(hashlib.sha256(v.encode()).digest()).rstrip(b"=").decode()
            if not v or not secrets.compare_digest(calc, rec["challenge"]):
                raise OAuthError("invalid_grant", "code_verifier does not match the code_challenge")
            out = _issue(d, rec["client_id"], rec["client"], rec["by"])
        elif g == "refresh_token":
            rec = d["refresh"].pop(sha(form.get("refresh_token", "")), None)
            if not rec or rec["exp"] < time.time() or (form.get("client_id") and form["client_id"] != rec["client_id"]):
                _save(d)
                raise OAuthError("invalid_grant", "the refresh token is unknown, used or expired")
            if rec["client_id"] not in d["clients"]:
                _save(d)
                raise OAuthError("invalid_grant", "the client was revoked")
            out = _issue(d, rec["client_id"], rec["client"], rec["by"])
        else:
            raise OAuthError("unsupported_grant_type", "grant_type must be authorization_code or refresh_token")
        _save(d)
    return out


def check(bearer: str) -> str | None:
    """An access token from here -> the client's name, else None."""
    if not bearer.startswith("r5o_"):
        return None
    rec = _load()["access"].get(sha(bearer))
    if not rec or rec["exp"] < time.time() or rec["client_id"] not in _load()["clients"]:
        return None
    return str(rec["client"])


def clients() -> list[Json]:
    d = _load()
    now = time.time()
    return [{"client_id": k, "name": v["name"], "at": v["at"], "redirect_uris": v["redirect_uris"],
             "tokens": sum(1 for a in d["access"].values() if a["client_id"] == k and a["exp"] > now)} for k, v in d["clients"].items()]


def revoke(cid: str) -> bool:
    with _LOCK:
        d = _load()
        gone = d["clients"].pop(cid, None) is not None
        for k in ("codes", "access", "refresh"):
            d[k] = {h: v for h, v in d[k].items() if v.get("client_id") != cid}
        _save(d)
    return gone

