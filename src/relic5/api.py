"""api.py: the hub over HTTP. MCP at POST /mcp, the same tools as plain GET routes, one bearer token per machine.

  POST /mcp            MCP JSON-RPC (streamable HTTP, JSON replies): initialize, ping, tools/list, tools/call
  GET  /api/search?q=  /api/show?id=  /api/sessions  /api/session?id=  /api/status      (v3 src/serve/http.ts routes)
  GET  /health

Token: ported from agent-relic-v4 src/relic4/api.py (PR #5 localhost-no-token @febfdb7, PR #6 relic-toml @b399119):
the bearer check with hmac.compare_digest, the 0600 token file. Changed on purpose, per relic4's advice (2026-10-23):
no loopback exemption. A hub serves many machines, and a proxy on the same box would make every client look like
127.0.0.1, so every request shows a token, /health too (an open /health would confirm the service exists; v3 http.ts).

Parts arrive over ssh (bin/relic5-push), never over HTTP. The routes that write are the hub's own records: tokens
(Connect), artifacts, and saved searches (trace.py); a POST that changes settings needs X-Relic5-Request: 1.
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
        a[k] = int(v) if k in INT_KEYS and v.isdigit() else (v in ("1", "true")) if k in ("semantic", "by_repo") else v
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
    # gzip what is worth it (the page's JS and CSS went out as 142 KB raw over tailscale, measured 2026-10-25; gz
    # they are about 42 KB), and API answers over 1 KB. Small replies stay as they are.
    from starlette.middleware.gzip import GZipMiddleware
    app.add_middleware(GZipMiddleware, minimum_size=1024, compresslevel=6)
    if os.environ.get("RELIC5_WARM", "1") != "0":   # the Map and the Knowledge map, made before anyone asks (universe.py)
        from . import universe
        universe.keep_warm(relic)

    from . import selfknow

    def client_of(request: Request, via: str) -> str:
        """Who is calling, for the Connected devices list: the X-Relic5-Client header (eval, relic-feeder, ...) when
        sent, else the User-Agent's first product ("claude-code", "python-urllib", "Mozilla"), with how (mcp | http)."""
        c = request.headers.get("x-relic5-client")
        if not c:
            ua = request.headers.get("user-agent", "").split(" ")[0].split("/")[0]
            c = ua.lower() or "unknown"
        return f"{c} ({via})"

    # Tokens from the UI (Connect tab). Only a tokenless door (loopback, Nat's tailnet) may list or change them: a
    # token never mints a token. Every change is a JSON POST with an X-Relic5-Request header, which a page on another
    # site cannot send without a CORS preflight this hub never answers. The secret is returned once and never logged.
    def token_admin(request: Request) -> "tuple[Tokens | None, JSONResponse | None]":
        from .tokens import Tokens as T   # imported here: tokens.py reads its paths at import (see the top of this file)
        if (request.state.door or "").startswith("token:") or not isinstance(tokens, T):
            return None, JSONResponse({"error": "tokens are managed from the hub itself or Nat's tailnet, not with a token"}, status_code=403)
        if request.method == "POST" and (request.headers.get("x-relic5-request") != "1"
                                         or not request.headers.get("content-type", "").startswith("application/json")):
            return None, JSONResponse({"error": "a token change needs Content-Type: application/json and X-Relic5-Request: 1"}, status_code=400)
        return tokens, None

    @app.get("/api/tokens", response_model=None)
    def tokens_list(request: Request) -> Response | list[Json]:
        t, bad = token_admin(request)
        if t is None:
            return bad or JSONResponse({"error": "refused"}, status_code=403)
        return t.list()

    @app.post("/api/tokens", response_model=None)
    async def tokens_change(request: Request) -> Response | Json:
        t, bad = token_admin(request)
        if t is None:
            return bad or JSONResponse({"error": "refused"}, status_code=403)
        try:
            body: Json = await request.json()
        except ValueError:
            return JSONResponse({"error": "body is not JSON"}, status_code=400)
        action, name = body.get("action"), str(body.get("name") or "")
        secret: str | None = None
        try:
            if action == "new":
                secret = t.new(name, body.get("expires") or None)
            elif action == "rotate":
                secret = t.rotate(name, body.get("grace") or "24h")
            elif action == "revoke":
                t.revoke(name)
            else:
                return JSONResponse({"error": "action is new | rotate | revoke"}, status_code=400)
        except SystemExit as ex:
            return JSONResponse({"error": str(ex)}, status_code=400)
        from .jobs import emit
        import socket, time as _t
        emit(relic.parts.root, {"job": f"token-{action}-{name}-{int(_t.time())}", "verb": "token", "state": "done", "rc": 0,
                                "at": _t.strftime("%Y-%m-%dT%H:%M:%SZ", _t.gmtime()), "host": socket.gethostname(),
                                "message": f"token {name}: {action} (by {request.state.door})"})
        return {"name": name, "action": action, **({"token": secret} if secret else {})}

    @app.get("/api/clients", response_model=None)
    def clients_route() -> Json:
        from . import selfknow
        return selfknow.clients(relic.parts.root)

    TRACED = {"relic_search", "relic_show", "relic_session", "relic_sessions", "relic_found"}

    def logged(relic_: Relic5, tool: str, args: Json, door: str | None, client: str | None = None) -> mcp.ToolReply:
        """Every tool call, MCP or GET, goes through here: one line in logs/queries.jsonl (selfknow.py), with its trace
        record (trace.py). A search, show or session result carries trace {id, root, parent} to pass on as parent."""
        from . import trace
        parent = args.get("parent") if isinstance(args, dict) and isinstance(args.get("parent"), str) else None
        rid = trace.new_id()
        qid, t0 = selfknow.start(tool, door, (args.get("query") or args.get("goal") or args.get("id") or "") if isinstance(args, dict) else "", client)
        ok, r = mcp.call_tool(relic_, tool, args, door)
        top = None
        try:
            top = selfknow.finish(relic_.parts.root, qid, t0, r if ok else None, args if isinstance(args, dict) else {},
                                  None if ok else r[1], rid, parent)
        except OSError:
            pass
        if ok and tool in TRACED and isinstance(r, dict):
            r = r | {"trace": {"id": rid, "root": top or rid, "parent": parent}}
        return ok, r

    def saved_call(tool: str, args: Json, parent: str | None, client: str) -> tuple[bool, object, str | None]:
        ok, r = logged(relic, tool, args | ({"parent": parent} if parent else {}), "saved-search", client)
        return ok, r, (r.get("trace") or {}).get("id") if ok and isinstance(r, dict) else None

    if os.environ.get("RELIC5_WARM", "1") != "0":   # saved searches run as jobs (trace.py)
        from . import trace as _trace
        _trace.keep_running(relic.parts.root, saved_call)

    @app.get("/api/trace", response_model=None)
    def trace_route(id: str = "", limit: int = 30) -> Response | Json:
        """One record's whole chain (id), or the newest chains."""
        from . import trace
        if id:
            out = trace.chain(relic.parts.root, id)
            return JSONResponse(out, status_code=404) if "error" in out else out
        return {"chains": trace.chains(relic.parts.root, max(1, min(limit, 200)))}

    @app.get("/api/access", response_model=None)
    def access_route(limit: int = 100, before: int | None = None, tool: str = "", client: str = "", door: str = "", q: str = "",
                     zero: int = 0, errors: int = 0, evals: int = 0, since: str = "", until: str = "") -> Response | Json:
        """The query log, newest first, filtered (since/until: a Bangkok day YYYY-MM-DD, an ISO time or Nd/Nh);
        page with before=<next_before>."""
        from . import trace
        from .window import WindowError
        try:
            return trace.access(relic.parts.root, max(1, min(limit, 500)), before, tool or None, client or None, door or None, q or None,
                                bool(zero), bool(errors), bool(evals), since or None, until or None)
        except WindowError as ex:
            return JSONResponse({"error": str(ex)}, status_code=400)

    @app.get("/api/tags", response_model=None)
    def tags_route(tag: str = "", target: str = "", since: str = "", until: str = "") -> Json:
        from . import trace
        if target:
            return trace.tags_of(relic.parts.root).get(target) or {"target": target, "tags": [], "notes": []}
        return trace.tagged(relic.parts.root, tag or None, since or None, until or None)

    @app.get("/api/period", response_model=None)
    def period_route(since: str = "", until: str = "", limit: int = 50) -> Response | Json:
        """What was asked in a period and what came of it (trace.asked): searches, zero hits, found notes, chains."""
        from . import trace
        from .window import WindowError
        try:
            return trace.asked(relic.parts.root, since or None, until or None, max(1, min(limit, 500)))
        except WindowError as ex:
            return JSONResponse({"error": str(ex)}, status_code=400)

    @app.get("/api/explain", response_model=None)
    def explain_route(q: str = "", with_: str = "", w: str = "") -> Response | Json:
        """How the hub reads a search: its tokens, each token's rows and BM25 weight, the exact-phrase count."""
        from .explain import explain
        from .query import UsageError
        try:
            return explain(relic, q, w or with_ or None)
        except UsageError as ex:
            return JSONResponse({"error": str(ex)}, status_code=400)

    @app.get("/api/asked", response_model=None)
    def asked_route(hours: int = 24) -> Json:
        """Per-hour counts and latency, zero-hit share, by client and tool: the Asked page's charts."""
        from . import trace
        return trace.stats(relic.parts.root, max(1, min(hours, 24 * 14)))

    @app.get("/api/saved", response_model=None)
    def saved_list() -> Json:
        from . import trace
        return {"saved": trace.public(trace.saved(relic.parts.root))}

    @app.post("/api/saved", response_model=None)
    async def saved_change(request: Request) -> Response | Json:
        """add {from | query, args, every, name} | remove {id} | run {id}. A JSON POST with X-Relic5-Request: 1, as the
        token routes: a page on another site cannot send that without a preflight this hub never answers."""
        from . import trace
        from .query import NotFound, UsageError
        if request.headers.get("x-relic5-request") != "1" or not request.headers.get("content-type", "").startswith("application/json"):
            return JSONResponse({"error": "needs Content-Type: application/json and X-Relic5-Request: 1"}, status_code=400)
        try:
            body: Json = await request.json()
        except ValueError:
            return JSONResponse({"error": "body is not JSON"}, status_code=400)
        act = body.get("action")
        try:
            if act == "add":
                every = body.get("every", 60)
                return trace.save(relic.parts.root, body.get("from") or None, body.get("query") or None, body.get("args") or None,
                                  every if isinstance(every, int) else -1, body.get("name") or None, request.state.door)
            if act == "remove":
                return trace.remove(relic.parts.root, str(body.get("id") or ""))
            if act == "run":
                return trace.run_one(relic.parts.root, str(body.get("id") or ""), saved_call)
        except UsageError as ex:
            return JSONResponse({"error": str(ex)}, status_code=400)
        except NotFound as ex:
            return JSONResponse({"error": str(ex)}, status_code=404)
        return JSONResponse({"error": "action is add | remove | run"}, status_code=400)

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

    @app.get("/api/artifacts", response_model=None)
    def artifacts_route(oracle: str | None = None, limit: int = 500) -> Json:
        from . import artifacts
        return artifacts.listing(relic.parts.root, oracle, max(1, min(limit, 2000)))

    @app.get("/api/artifact/{aid}", response_model=None)
    def artifact_file(aid: str) -> Response:
        """One artifact's bytes. A web piece or SVG is served under a CSP sandbox, so its scripts never run with the
        hub's origin; nosniff so a browser never guesses another type."""
        from fastapi.responses import FileResponse
        from . import artifacts
        from .query import NotFound
        try:
            path, mime, kind = artifacts.file_of(relic.parts.root, aid)
        except NotFound:
            return JSONResponse({"error": "no such artifact"}, status_code=404)
        h = {"X-Content-Type-Options": "nosniff", "Cache-Control": "private, max-age=31536000, immutable"}
        if kind == "web" or mime.startswith("image/svg"):
            h["Content-Security-Policy"] = "sandbox allow-scripts; default-src 'self' data: blob: 'unsafe-inline' 'unsafe-eval'; connect-src 'none'"
        return FileResponse(path, media_type=mime, headers=h)

    @app.post("/api/artifact", response_model=None)
    async def artifact_post(request: Request, oracle: str, filename: str, title: str = "", note: str = "", prompt: str = "", session: str = "") -> Response:
        """The same as relic_artifact_put for a file too big for an MCP message: the raw bytes as the body.
        curl --data-binary @portrait.png 'http://hub:8795/api/artifact?oracle=neo-oracle&filename=portrait.png&title=…'"""
        from . import artifacts
        from .query import UsageError
        try:
            rec = artifacts.put(relic.parts.root, oracle, title, os.path.splitext(filename)[1], await request.body(), note or None,
                                prompt or None, session or None, getattr(request.state, "door", None))
        except UsageError as ex:
            return JSONResponse({"error": str(ex)}, status_code=400)
        return JSONResponse(rec)

    @app.get("/api/lineage", response_model=None)
    def lineage_route() -> Json:
        from . import family
        return family.lineage(relic.parts.root)

    @app.get("/api/team", response_model=None)
    def team_route(days: int = 90) -> Json:
        from . import family
        return family.team(relic, max(7, min(days, 400)))

    @app.get("/api/oracles", response_model=None)
    def oracles_route() -> Json:
        from . import oracles
        return oracles.listing(relic)

    @app.get("/api/oracle", response_model=None)
    def oracle_route(name: str) -> Json:
        """One oracle brought to the human: its notes by section, sessions, rules, and the character and
        enlightenment prompts built from them (oracles.py)."""
        from . import oracles
        out = oracles.portrait(relic, name)
        return JSONResponse(out, status_code=404) if "error" in out else out   # type: ignore[return-value]

    @app.get("/api/map", response_model=None)
    def map_route(model: str | None = None, limit: int = 3000) -> Json:
        """The sessions as points: per-session mean vector, PCA to 3D (universe.py), for the Map view."""
        from . import universe
        from .query import UsageError
        try:
            return universe.sessions_map(relic, model, max(10, min(limit, 20000)))
        except UsageError as ex:
            return JSONResponse({"error": str(ex)}, status_code=400)   # type: ignore[return-value]

    @app.post("/api/place", response_model=None)
    async def place_route(request: Request) -> Response | Json:
        """{uids, scores?} -> those messages as points in the Map's 3D space (universe.place): a search's hits over
        the map. A POST only because 40 uids do not fit a URL; it reads, never writes."""
        from . import universe
        from .query import UsageError
        try:
            body: Json = await request.json()
        except ValueError:
            return JSONResponse({"error": "body is not JSON"}, status_code=400)
        uids = [str(u) for u in (body.get("uids") or [])][:200]
        scores = body.get("scores")
        try:
            return universe.search_space(relic, uids, [float(x) for x in scores] if isinstance(scores, list) else None)
        except UsageError as ex:
            return JSONResponse({"error": str(ex)}, status_code=400)

    @app.get("/api/memory", response_model=None)
    def memory_route() -> "Listing":
        from . import memory
        return memory.listing(relic.parts.root)

    @app.get("/api/memory/map", response_model=None)
    def memory_map_route() -> Json:
        """Every memory note with its own vector as a point (universe.memory_map), for the Knowledge page's map."""
        from . import universe
        return universe.memory_map(relic)

    @app.get("/api/memory/file", response_model=None)
    def memory_file(path: str) -> Response:
        """One memory note as its file holds it (frontmatter and all), for the Knowledge page's raw view. Only a .md under
        parts/<machine>/memory/: anything else, or a path that resolves outside, is refused."""
        base = os.path.realpath(os.path.join(relic.parts.root, "parts"))
        full = os.path.realpath(os.path.join(relic.parts.root, path))
        rel = os.path.relpath(full, base)
        if rel.startswith("..") or "/memory/" not in "/" + rel or not full.endswith(".md") or not os.path.isfile(full):
            return JSONResponse({"error": "not a memory note on this hub"}, status_code=404)
        return Response(open(full, encoding="utf-8", errors="replace").read(), media_type="text/markdown; charset=utf-8")

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
        door, client = request.state.door, client_of(request, "mcp")
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
            ok, r = logged(relic, tool, args_of(request.query_params), request.state.door, client_of(request, "http"))
            if ok:
                return Response(dumps(r), media_type="application/json")
            return JSONResponse({"error": r[1]}, status_code=STATUS_OF[r[0]])
        return route

    for path, tool in ROUTES.items():
        app.add_api_route(path, make_route(tool), methods=["GET"])

    return app
