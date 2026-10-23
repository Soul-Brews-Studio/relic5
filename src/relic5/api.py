"""api.py: the hub over HTTP. MCP at POST /mcp, the same tools as plain GET routes, one bearer token per machine.

  POST /mcp            MCP JSON-RPC (streamable HTTP, JSON replies): initialize, ping, tools/list, tools/call
  GET  /api/search?q=  /api/show?id=  /api/sessions  /api/session?id=  /api/status      (v3 src/serve/http.ts routes)
  GET  /health

Token: ported from agent-relic-v4 src/relic4/api.py (PR #5 localhost-no-token @febfdb7, PR #6 relic-toml @b399119):
the bearer check with hmac.compare_digest, the 0600 token file. Changed on purpose, per relic4's advice (2026-10-23):
no loopback exemption. A hub serves many machines, and a proxy on the same box would make every client look like
127.0.0.1, so every request shows a token, /health too (an open /health would confirm the service exists; v3 http.ts).

Read-only: no route writes. Parts arrive over ssh (bin/relic5-push), never over HTTP.
"""
import hmac, json, os

import duckdb
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response

from . import mcp
from .query import Relic5

ROUTES = {"/api/search": "relic_search", "/api/show": "relic_show", "/api/sessions": "relic_sessions",
          "/api/session": "relic_session", "/api/status": "relic_status"}
INT_KEYS = {"limit", "seq", "before", "after"}
STATUS_OF = {"usage": 400, "unavailable": 501, "not_found": 404, "failed": 500}


def args_of(params):
    """Query string -> tool args, as v3 http.ts argsOf: q -> query, ints and the semantic boolean coerced."""
    a = {}
    for k0, v in params.multi_items():
        k = "query" if k0 == "q" else k0.replace("-", "_")
        a[k] = int(v) if k in INT_KEYS and v.isdigit() else (v in ("1", "true")) if k == "semantic" else v
    return a


def dumps(v):
    return json.dumps(v, ensure_ascii=False, default=str)


def make_app(root, tokens, doors=None):
    """tokens: {machine: token}; doors: who needs none (doors.py; default: loopback + Nat's own tailnet nodes)."""
    from .doors import Doors
    if not tokens and doors is None:
        raise SystemExit("no tokens: run `relic5 token new <name>` first")
    doors = doors if doors is not None else Doors(tokens)
    con = duckdb.connect(":memory:", config={"threads": min(os.cpu_count() or 4, 16)})
    relic = Relic5(root, con)
    app = FastAPI(title="relic5", docs_url=None, redoc_url=None, openapi_url=None)

    WEB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web", "index.html")

    def who(request):
        """The door this request came through (doors.py), from the socket's addresses only."""
        h = request.headers.get("authorization", "")
        # a browser shows the token once at /login?t=..., then sends it as an HttpOnly, SameSite=Strict cookie
        got = h[7:] if h.startswith("Bearer ") else request.cookies.get("relic5_t", "")
        server = (request.scope.get("server") or ("",))[0]
        client = request.client.host if request.client else ""
        return doors.door(server, client, request.url.hostname, got)

    @app.middleware("http")
    async def auth(request: Request, call_next):
        if request.url.path == "/login":
            return await call_next(request)   # it checks the token itself
        d = who(request)
        if d is None:
            return JSONResponse({"error": "missing or bad Authorization: Bearer token"}, status_code=401)
        request.state.door = d
        return await call_next(request)

    @app.get("/login")
    def login(t: str = ""):
        if not t or not doors.door("", "", "", t):
            return JSONResponse({"error": "bad token"}, status_code=401)
        r = RedirectResponse("/", status_code=303)
        r.set_cookie("relic5_t", t, httponly=True, samesite="strict", max_age=90 * 86400)
        return r

    @app.get("/")
    def ui():
        return HTMLResponse(open(WEB, encoding="utf-8").read())

    @app.get("/api/log")
    def log(n: int = 100):
        from .jobs import read
        return read(root)[0][:min(max(n, 1), 1000)]

    @app.get("/api/tail")
    def tail(n: int = 50, session: str = "", machine: str = "", since: str = ""):
        return relic.tail(min(max(n, 1), 500), session or None, machine or None, since or None)

    @app.get("/api/recap")
    def recap_route(id: str, limit: int = 20):
        from .recap import recap
        from .query import NotFound, UsageError
        try:
            return recap(relic, id, max(limit, 0))
        except (NotFound, UsageError) as ex:
            return JSONResponse({"error": str(ex)}, status_code=404 if isinstance(ex, NotFound) else 400)

    @app.get("/api/handoff")
    def handoff_route(id: str, user_only: int = 0):
        from .recap import handoff
        from .query import NotFound, UsageError
        try:
            return handoff(relic, id, bool(user_only))
        except (NotFound, UsageError) as ex:
            return JSONResponse({"error": str(ex)}, status_code=404 if isinstance(ex, NotFound) else 400)

    @app.get("/api/eval")
    def eval_log(n: int = 200):
        """The eval runs (tests/eval/compare.py appends them): newest last."""
        p = os.path.join(relic.parts.root, "logs", "eval.jsonl")
        if not os.path.exists(p):
            return []
        out = []
        for line in open(p, encoding="utf-8").readlines()[-min(max(n, 1), 2000):]:
            try:
                out.append(json.loads(line))
            except ValueError:
                pass
        return out

    @app.get("/api/probe")
    def probe(model: str = "", n: int = 200):
        """Texts the hub holds vectors for, with the vectors: another engine's parity probe (read-only)."""
        from . import vec as V
        return {"model": model or V.DEFAULT, "rows": V.probe_rows(relic.parts.root, con.cursor(), model or V.DEFAULT, min(max(n, 1), 2000))}

    @app.get("/api/missing")
    def missing(model: str = "", limit: int = 1000, prefix: str = ""):
        """Keys with no vector yet, for an embed worker (read-only; vectors come back over ssh)."""
        from . import vec as V
        if prefix and not all(c in "0123456789abcdef" for c in prefix):
            return JSONResponse({"error": "prefix is hex"}, status_code=400)
        return V.missing(relic.parts.root, con.cursor(), model or V.DEFAULT, min(max(limit, 1), 100000), prefix)

    @app.get("/health")
    def health():
        return {"ok": True}

    @app.post("/mcp")
    async def mcp_post(request: Request):
        try:
            msg = json.loads(await request.body())
        except ValueError:
            return Response(dumps(mcp._err(None, -32700, "parse error")), media_type="application/json")
        door = request.state.door
        if isinstance(msg, list):
            out = [r for r in (mcp.handle(relic, m, door) for m in msg) if r is not None]
        else:
            out = mcp.handle(relic, msg, door)
        if not out:
            return Response(status_code=202)   # notifications only: accepted, nothing to say
        return Response(dumps(out), media_type="application/json")

    @app.get("/mcp")
    def mcp_get():
        return Response(status_code=405)       # no server-initiated stream

    for path, tool in ROUTES.items():
        def route(request: Request, tool=tool):
            ok, r = mcp.call_tool(relic, tool, args_of(request.query_params), request.state.door)
            if ok:
                return Response(dumps(r), media_type="application/json")
            return JSONResponse({"error": r[1]}, status_code=STATUS_OF[r[0]])
        app.add_api_route(path, route, methods=["GET"])

    return app
