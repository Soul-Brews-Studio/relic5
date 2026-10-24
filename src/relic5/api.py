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
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

import duckdb
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from starlette.datastructures import QueryParams

from . import mcp
from .query import Relic5
from .types_ import JobEvent, Json

if TYPE_CHECKING:
    from .doors import Doors
    from .memory import Listing
    from .tokens import Tokens

ROUTES = {"/api/search": "relic_search", "/api/show": "relic_show", "/api/sessions": "relic_sessions",
          "/api/session": "relic_session", "/api/status": "relic_status"}
INT_KEYS = {"limit", "seq", "before", "after"}
STATUS_OF = {"usage": 400, "unavailable": 501, "not_found": 404, "failed": 500}


def args_of(params: QueryParams) -> Json:
    """Query string -> tool args, as v3 http.ts argsOf: q -> query, ints and the semantic boolean coerced."""
    a: Json = {}
    for k0, v in params.multi_items():
        k = "query" if k0 == "q" else k0.replace("-", "_")
        a[k] = int(v) if k in INT_KEYS and v.isdigit() else (v in ("1", "true")) if k == "semantic" else v
    return a


def dumps(v: object) -> str:
    return json.dumps(v, ensure_ascii=False, default=str)


def make_app(root: str, tokens: "Tokens | dict[str, str]", doors: "Doors | None" = None) -> FastAPI:
    """tokens: {machine: token}; doors: who needs none (doors.py; default: loopback + Nat's own tailnet nodes)."""
    from .doors import Doors
    if not tokens and doors is None:
        raise SystemExit("no tokens: run `relic5 token new <name>` first")
    doors = doors if doors is not None else Doors(tokens)
    con = duckdb.connect(":memory:", config={"threads": min(os.cpu_count() or 4, 16)})
    relic = Relic5(root, con)
    app = FastAPI(title="relic5", docs_url=None, redoc_url=None, openapi_url=None)

    from . import selfknow

    def logged(relic_: Relic5, tool: str, args: Json, door: str | None, client: str | None = None) -> mcp.ToolReply:
        """Every tool call, MCP or GET, goes through here: one line in logs/queries.jsonl (selfknow.py)."""
        qid, t0 = selfknow.start(tool, door, args.get("query") or args.get("id") or "", client)
        ok, r = mcp.call_tool(relic_, tool, args, door)
        try:
            selfknow.finish(relic_.parts.root, qid, t0, r if ok else None, args, None if ok else r[1])
        except OSError:
            pass
        return ok, r

    WEB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web", "index.html")

    def who(request: Request) -> str | None:
        """The door this request came through (doors.py), from the socket's addresses only."""
        h = request.headers.get("authorization", "")
        # a browser shows the token once at /login?t=..., then sends it as an HttpOnly, SameSite=Strict cookie
        got = h[7:] if h.startswith("Bearer ") else request.cookies.get("relic5_t", "")
        server = (request.scope.get("server") or ("",))[0]
        client = request.client.host if request.client else ""
        return doors.door(server, client, request.url.hostname, got)

    @app.middleware("http")
    async def auth(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        if request.url.path == "/login":
            return await call_next(request)   # it checks the token itself
        d = who(request)
        if d is None:
            return JSONResponse({"error": "missing or bad Authorization: Bearer token"}, status_code=401)
        request.state.door = d
        return await call_next(request)

    @app.get("/login")
    def login(t: str = "") -> Response:
        if not t or not doors.door("", "", "", t):
            return JSONResponse({"error": "bad token"}, status_code=401)
        r = RedirectResponse("/", status_code=303)
        r.set_cookie("relic5_t", t, httponly=True, samesite="strict", max_age=90 * 86400)
        return r

    @app.get("/")
    def ui() -> HTMLResponse:
        return HTMLResponse(open(WEB, encoding="utf-8").read())

    ASSETS = os.path.join(os.path.dirname(WEB), "assets")
    TYPES = {".js": "text/javascript", ".css": "text/css", ".svg": "image/svg+xml", ".woff2": "font/woff2"}

    @app.get("/assets/{name}")
    def asset(name: str) -> Response:
        """The React build (web/, `just web`): hashed file names, so they are cached for a year. A name with a
        path in it, or of a type not listed, is refused."""
        ext = os.path.splitext(name)[1]
        path = os.path.join(ASSETS, name)
        if os.path.basename(name) != name or ext not in TYPES or not os.path.isfile(path):
            return JSONResponse({"error": "not found"}, status_code=404)
        return Response(open(path, "rb").read(), media_type=TYPES[ext], headers={"cache-control": "public, max-age=31536000, immutable"})

    @app.get("/api/month-recap", response_model=None)
    def month_recap(month: str) -> Response:
        """A sealed month's recap (bin/relic5-month-recap), markdown; 404 until one is written."""
        from . import sealday
        if len(month) != 7 or month[4] != "-" or not (month[:4] + month[5:]).isdigit():
            return JSONResponse({"error": "month is YYYY-MM"}, status_code=400)
        p = sealday.recap_path(relic.parts.root, month)
        if not os.path.isfile(p):
            return JSONResponse({"error": f"no recap for {month} yet"}, status_code=404)
        return Response(open(p, encoding="utf-8").read(), media_type="text/markdown; charset=utf-8")

    @app.get("/api/memory", response_model=None)
    def memory_route() -> "Listing":
        from . import memory
        return memory.listing(relic.parts.root)

    @app.get("/api/log", response_model=None)
    def log(n: int = 100) -> list[JobEvent]:
        from .jobs import read
        return read(root)[0][:min(max(n, 1), 1000)]

    @app.get("/api/tail", response_model=None)
    def tail(n: int = 50, session: str = "", machine: str = "", since: str = "") -> Json:
        return relic.tail(min(max(n, 1), 500), session or None, machine or None, since or None)

    @app.get("/api/queries", response_model=None)
    def queries_route() -> Json:
        return selfknow.queries(relic.parts.root)

    @app.get("/api/recap", response_model=None)
    def recap_route(id: str, limit: int = 20) -> Json | JSONResponse:
        from .recap import recap
        from .query import NotFound, UsageError
        try:
            return recap(relic, id, max(limit, 0))
        except (NotFound, UsageError) as ex:
            return JSONResponse({"error": str(ex)}, status_code=404 if isinstance(ex, NotFound) else 400)

    @app.get("/api/handoff", response_model=None)
    def handoff_route(id: str, user_only: int = 0) -> Json | JSONResponse:
        from .recap import handoff
        from .query import NotFound, UsageError
        try:
            return handoff(relic, id, bool(user_only))
        except (NotFound, UsageError) as ex:
            return JSONResponse({"error": str(ex)}, status_code=404 if isinstance(ex, NotFound) else 400)

    @app.get("/api/eval", response_model=None)
    def eval_log(n: int = 200) -> list[Json]:
        """The eval runs (tests/eval/compare.py appends them): newest last."""
        p = os.path.join(relic.parts.root, "logs", "eval.jsonl")
        if not os.path.exists(p):
            return []
        out: list[Json] = []
        for line in open(p, encoding="utf-8").readlines()[-min(max(n, 1), 2000):]:
            try:
                out.append(json.loads(line))
            except ValueError:
                pass
        return out

    @app.get("/api/probe", response_model=None)
    def probe(model: str = "", n: int = 200) -> Json:
        """Texts the hub holds vectors for, with the vectors: another engine's parity probe (read-only)."""
        from . import vec as V
        return {"model": model or V.DEFAULT, "rows": V.probe_rows(relic.parts.root, con.cursor(), model or V.DEFAULT, min(max(n, 1), 2000))}

    @app.get("/api/missing", response_model=None)
    def missing(model: str = "", limit: int = 1000, prefix: str = "") -> Json | JSONResponse:
        """Keys with no vector yet, for an embed worker (read-only; vectors come back over ssh)."""
        from . import vec as V
        if prefix and not all(c in "0123456789abcdef" for c in prefix):
            return JSONResponse({"error": "prefix is hex"}, status_code=400)
        return V.missing(relic.parts.root, con.cursor(), model or V.DEFAULT, min(max(limit, 1), 100000), prefix)

    @app.get("/health", response_model=None)
    def health() -> Json:
        return {"ok": True}

    @app.post("/mcp")
    async def mcp_post(request: Request) -> Response:
        try:
            msg = json.loads(await request.body())
        except ValueError:
            return Response(dumps(mcp._err(None, -32700, "parse error")), media_type="application/json")
        door, client = request.state.door, request.headers.get("x-relic5-client")
        call: mcp.ToolCall = lambda r_, n, a, d: logged(r_, n, a, d, client)
        out: list[Json] | Json | None
        if isinstance(msg, list):
            out = [r for r in (mcp.handle(relic, m, door, call) for m in msg) if r is not None]
        else:
            out = mcp.handle(relic, msg, door, call)
        if not out:
            return Response(status_code=202)   # notifications only: accepted, nothing to say
        return Response(dumps(out), media_type="application/json")

    @app.get("/mcp")
    def mcp_get() -> Response:
        return Response(status_code=405)       # no server-initiated stream

    def make_route(tool: str) -> Callable[[Request], Response]:
        """The tool is bound by the closure, never a parameter: FastAPI would read a defaulted `tool` argument as a
        query parameter, and ?tool=... could pick which tool runs (found by the mypy pass, 2026-10-24)."""
        def route(request: Request) -> Response:
            ok, r = logged(relic, tool, args_of(request.query_params), request.state.door, request.headers.get("x-relic5-client"))
            if ok:
                return Response(dumps(r), media_type="application/json")
            return JSONResponse({"error": r[1]}, status_code=STATUS_OF[r[0]])
        return route

    for path, tool in ROUTES.items():
        app.add_api_route(path, make_route(tool), methods=["GET"])

    return app
