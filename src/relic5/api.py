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
from fastapi.responses import JSONResponse, Response

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


def make_app(root, tokens):
    """tokens: {machine: token}. Refuses to build an app nobody could call."""
    if not tokens:
        raise SystemExit("no tokens: run `relic5 token add <machine>` first")
    con = duckdb.connect(":memory:", config={"threads": min(os.cpu_count() or 4, 16)})
    relic = Relic5(root, con)
    app = FastAPI(title="relic5", docs_url=None, redoc_url=None, openapi_url=None)

    def who(request):
        h = request.headers.get("authorization", "")
        got = h[7:].encode() if h.startswith("Bearer ") else b""
        # compare against every token, so the time taken does not tell which machine nearly matched
        ok = [m for m, t in tokens.items() if hmac.compare_digest(got, t.encode())]
        return ok[0] if got and ok else None

    @app.middleware("http")
    async def auth(request: Request, call_next):
        if who(request) is None:
            return JSONResponse({"error": "missing or bad Authorization: Bearer token"}, status_code=401)
        return await call_next(request)

    @app.get("/health")
    def health():
        return {"ok": True}

    @app.post("/mcp")
    async def mcp_post(request: Request):
        try:
            msg = json.loads(await request.body())
        except ValueError:
            return Response(dumps(mcp._err(None, -32700, "parse error")), media_type="application/json")
        if isinstance(msg, list):
            out = [r for r in (mcp.handle(relic, m) for m in msg) if r is not None]
        else:
            out = mcp.handle(relic, msg)
        if not out:
            return Response(status_code=202)   # notifications only: accepted, nothing to say
        return Response(dumps(out), media_type="application/json")

    @app.get("/mcp")
    def mcp_get():
        return Response(status_code=405)       # no server-initiated stream

    for path, tool in ROUTES.items():
        def route(request: Request, tool=tool):
            ok, r = mcp.call_tool(relic, tool, args_of(request.query_params))
            if ok:
                return Response(dumps(r), media_type="application/json")
            return JSONResponse({"error": r[1]}, status_code=STATUS_OF[r[0]])
        app.add_api_route(path, route, methods=["GET"])

    return app
