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
import functools, hmac, json, os, threading, time
from urllib.parse import parse_qs, urlparse
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

import duckdb
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from starlette.datastructures import QueryParams

from . import mcp
from .query import Relic5
from .types_ import JobEvent, Json
from . import store as rfs
from . import swr
from . import oauth
from . import seen

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
    # a memory limit: DuckDB takes up to 80% of the machine by default, and white's hub was OOM-killed (2026-10-25, 46 GB
    # box, serve at 24 GB beside an index); RELIC5_DUCK_MEM overrides
    con = duckdb.connect(":memory:", config={"threads": min(os.cpu_count() or 4, 16), "memory_limit": os.environ.get("RELIC5_DUCK_MEM", "6GB")})
    from . import perf
    perf.keep(root)
    threading.Thread(target=seen.seed, args=(root,), name="seen-seed", daemon=True).start()   # last used, from the logs
    relic = Relic5(root, con)
    app = FastAPI(title="relic5", docs_url=None, redoc_url=None, openapi_url=None)

    def cached(ttl: float) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        """A GET answer kept ttl seconds and refreshed behind the reader (swr.py); the key is the route and its args."""
        def deco(fn: Callable[..., Any]) -> Callable[..., Any]:
            @functools.wraps(fn)
            def wrapped(*a: Any, **kw: Any) -> Any:
                return swr.get(f"{fn.__name__}?{sorted(kw.items())}", ttl, lambda: fn(*a, **kw))
            return wrapped
        return deco
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
        return [r | seen.of("token:" + r["name"]) for r in t.list()]

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
    @cached(60)
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

    if rfs.is_s3(relic.parts.root):
        # the search index is local (fts.search_dir): seed it from the bucket once, in the background, so the hub answers
        # at once (a whole index is GBs: 7.5 GB for white's, 2026-10-25); Index opens it when current.json lands
        from .fts import seed_in_background
        seed_in_background(relic.parts.root, every=float(os.environ.get("RELIC5_SEED_EVERY", "300")))
    if rfs.is_s3(relic.parts.root) and os.environ.get("RELIC5_WARM", "1") != "0":
        # S3 has no append: each log line is an object (store.append_line). Roll lines older than 10 minutes into one
        # chunk object per log every 10 minutes, so a listing stays short.
        import threading as _th, time as _time

        def _compact_loop() -> None:
            while True:
                _time.sleep(600)
                for rel in ("logs/queries.jsonl", "logs/jobs.jsonl", "logs/tags.jsonl", "logs/sizes.jsonl", "artifacts/index.jsonl"):
                    try:
                        rfs.compact(os.path.join(relic.parts.root, rel), older_than=600)
                    except Exception:
                        pass
        _th.Thread(target=_compact_loop, name="relic5-compact", daemon=True).start()

        # nothing on an S3 hub's machine sees a push land (on a disk hub, relic-extract's after hook runs the index):
        # look every 2 minutes, and when a part changed, run `relic5 index` as its own process (it locks itself)
        def _index_loop() -> None:
            import subprocess, sys as _sys
            while True:
                _time.sleep(120)
                try:
                    stale = relic.parts.stale()
                except Exception:
                    continue
                if stale:
                    subprocess.run([_sys.executable, "-m", "relic5.cli", "index", "--root", relic.parts.root, "--wait"],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
        if os.environ.get("RELIC5_AUTO_INDEX", "1") != "0":
            _th.Thread(target=_index_loop, name="relic5-auto-index", daemon=True).start()

    if os.environ.get("RELIC5_WARM", "1") != "0":   # saved searches run as jobs (trace.py)
        from . import trace as _trace
        _trace.keep_running(relic.parts.root, saved_call)

    if os.environ.get("RELIC5_WARM", "1") != "0":   # a mirror, when one is set (mirror.py): copies on its own clock
        from . import mirror as _mirror
        _mirror.keep_mirrored(relic.parts.root)

    @app.get("/api/homes", response_model=None)
    @cached(60)
    def homes_route() -> Json:
        """Every .claude (or .codex) the history came from, per machine (query.homes)."""
        return relic.homes()

    @app.get("/api/storage", response_model=None)
    def storage_route() -> Json:
        """Where the hub keeps its data, the mirror and its last run, and a switch waiting for the next start."""
        from . import mirror
        from .jobs import read
        c = mirror.config()
        last = next((e for e in read(relic.parts.root)[0] if e.get("verb") == "mirror"), None)
        kind = "s3" if rfs.is_s3(relic.parts.root) else "disk"
        return {"root": relic.parts.root, "kind": kind, "endpoint": rfs.s3_config()["endpoint"] if kind == "s3" else None,
                "cache": rfs.cache_dir(relic.parts.root) if kind == "s3" else None, "mirror": c.get("mirror"),
                "every_min": c.get("every_min") or 60, "switch_to": c.get("switch_to"), "switched_from": c.get("switched_from"),
                "state": mirror.state(), "last_job": last, "verify": c.get("verify")}

    @app.post("/api/storage", response_model=None)
    async def storage_change(request: Request) -> Response | Json:
        """set-mirror {target, every_min} | mirror-now | verify | switch | cancel-switch. Only from the hub itself or
        Nat's tailnet (never with a token: this points the hub's data somewhere else), as a JSON POST with
        X-Relic5-Request: 1."""
        from . import mirror
        if (request.state.door or "").startswith("token:"):
            return JSONResponse({"error": "storage is managed from the hub itself or Nat's tailnet, not with a token"}, status_code=403)
        if request.headers.get("x-relic5-request") != "1" or not request.headers.get("content-type", "").startswith("application/json"):
            return JSONResponse({"error": "needs Content-Type: application/json and X-Relic5-Request: 1"}, status_code=400)
        try:
            body: Json = await request.json()
        except ValueError:
            return JSONResponse({"error": "body is not JSON"}, status_code=400)
        act, c = body.get("action"), mirror.config()
        try:
            if act == "set-mirror":
                t = str(body.get("target") or "").strip()
                if t and not (t.startswith("s3://") or t.startswith("/") or t.startswith("~")):
                    return JSONResponse({"error": "a mirror is a folder (/path) or s3://bucket/prefix"}, status_code=400)
                if t and rfs.root_of(t) == relic.parts.root:
                    return JSONResponse({"error": "that is where the hub already lives"}, status_code=400)
                return mirror.set_config(mirror=t or None, every_min=int(body.get("every_min") or c.get("every_min") or 60), verify=None)
            if act == "mirror-now":
                import threading as _t2
                _t2.Thread(target=lambda: mirror.run(relic.parts.root), daemon=True).start()
                return {"started": True, "mirror": c.get("mirror")}
            if act == "verify":
                if not c.get("mirror"):
                    return JSONResponse({"error": "no mirror set"}, status_code=400)
                v = mirror.verify(relic.parts.root, c["mirror"])
                mirror.set_config(verify=v)
                return v
            if act == "switch":
                v = c.get("verify") or {}
                if not c.get("mirror") or not v.get("ok") or v.get("dst") != rfs.root_of(c["mirror"]):
                    return JSONResponse({"error": "verify the mirror first: a switch needs a verify with nothing missing"}, status_code=400)
                return mirror.set_config(switch_to=c["mirror"])
            if act == "cancel-switch":
                return mirror.set_config(switch_to=None)
        except ValueError as ex:
            return JSONResponse({"error": str(ex)}, status_code=400)
        return JSONResponse({"error": "action is set-mirror | mirror-now | verify | switch | cancel-switch"}, status_code=400)

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

    # the public address a tunnel gives the hub (RELIC5_PUBLIC_URL, e.g. https://relic5.example.com): on that host only
    # /mcp and the OAuth endpoints answer; the page and the rest of the API stay on the tailnet
    # the tunnel's https address(es), comma-separated, the first the one to show; more than one while a connector
    # moves from one name to another (2026-10-25: relic5-mcp.buildwithoracle.com -> mcp.oraclenet.org)
    PUBLICS = {(urlparse(u).hostname or "").lower(): u.strip().rstrip("/")
               for u in os.environ.get("RELIC5_PUBLIC_URL", "").split(",") if u.strip()}
    PUBLIC = next(iter(PUBLICS.values()), "")
    OPEN = ("/.well-known/oauth-protected-resource", "/.well-known/oauth-authorization-server", "/oauth/")
    # the hub's icon, open to anyone and on the public host too: claude.ai shows it beside the connector
    ICONS = {"/favicon.ico": ("favicon.ico", "image/x-icon"), "/favicon.svg": ("favicon.svg", "image/svg+xml"),
             "/apple-touch-icon.png": ("icon-180.png", "image/png"), "/icon-192.png": ("icon-192.png", "image/png"),
             "/icon-512.png": ("icon-512.png", "image/png")}

    # the port `tailscale serve` (HTTPS on the tailnet) forwards to, on loopback only; its callers are named by tailscaled
    SERVE_PORT = int(os.environ.get("RELIC5_SERVE_PORT") or 0)

    def base_of(request: Request) -> str:
        return PUBLICS.get((request.url.hostname or "").lower()) or PUBLIC or f"{request.url.scheme}://{request.url.netloc}"

    def where(request: Request) -> tuple[str, str]:
        """The caller's address: through the tunnel, cloudflared connects from loopback and names the real one."""
        client = request.client.host if request.client else ""
        cf = request.headers.get("cf-connecting-ip")
        return (cf, "tunnel") if cf and client in ("127.0.0.1", "::1") else (client, "direct")

    def who(request: Request) -> str | None:
        """The door this request came through (doors.py), from the socket's addresses only."""
        h = request.headers.get("authorization", "")
        # a browser shows the token once at /login?t=..., then sends it as an HttpOnly, SameSite=Strict cookie
        got = h[7:] if h.startswith("Bearer ") else request.cookies.get("relic5_t", "")
        if got.startswith("r5o_"):   # an OAuth access token (oauth.py): claude.ai's connector, /mcp only
            name = oauth.check(got)
            return f"oauth:{name}" if name and request.url.path == "/mcp" else None
        srv = request.scope.get("server") or ("", 0)
        server = srv[0]
        client = request.client.host if request.client else ""
        if not got and SERVE_PORT and len(srv) > 1 and srv[1] == SERVE_PORT and client in ("127.0.0.1", "::1") and hasattr(doors, "served"):
            xff = request.headers.get("x-forwarded-for", "").split(",")[0].strip()
            return doors.served(xff, request.headers.get("tailscale-user-login", ""), request.url.hostname)
        return doors.door(server, client, request.url.hostname, got)

    @app.middleware("http")
    async def auth(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        path = request.url.path
        if path in ICONS:
            name, mime = ICONS[path]
            return Response(open(os.path.join(os.path.dirname(__file__), "icons", name), "rb").read(), media_type=mime,
                            headers={"cache-control": "public, max-age=86400"})
        if (request.url.hostname or "").lower() in PUBLICS and not (path == "/mcp" or path.startswith(OPEN)):
            return JSONResponse({"error": "not found"}, status_code=404)   # the tunnel shows only the MCP door
        if path == "/login" or path.startswith(OPEN):
            return await call_next(request)   # they check the token themselves, or need none
        if path.startswith("/arra/"):   # Studio's page is another origin: a preflight carries no credentials
            from .arra import cors
            h = cors(request.headers.get("origin"))
            if request.method == "OPTIONS":
                return Response(status_code=204 if h else 403, headers=h)
            d = who(request)
            if d is None:
                return JSONResponse({"error": "relic5: open Studio on the tailnet (https://white.follow-rankine.ts.net/arra)"}, status_code=401, headers=h)
            request.state.door = d
            seen.touch(d, *where(request), path)
            resp = await call_next(request)
            resp.headers.update(h)
            return resp
        d = who(request)
        if d is None:
            hdr = {"WWW-Authenticate": f'Bearer resource_metadata="{base_of(request)}/.well-known/oauth-protected-resource"'} if path == "/mcp" else {}
            return JSONResponse({"error": "missing or bad Authorization: Bearer token"}, status_code=401, headers=hdr)
        request.state.door = d
        seen.touch(d, *where(request), path)
        t0 = time.perf_counter()
        perf.ROUTE.set(request.url.path)   # the queries this request runs are filed under it (perf.query)
        resp = await call_next(request)
        if request.url.path.startswith(("/api/", "/mcp")) and request.url.path != "/api/perf":
            route = request.scope.get("route")
            perf.record(request.method, request.url.path, getattr(route, "path", None), resp.status_code,
                        (time.perf_counter() - t0) * 1000, int(resp.headers.get("content-length") or 0) or None, d, request.url.query)
        return resp

    @app.get("/api/perf", response_model=None)
    def perf_route(minutes: int = 60, route: str = "") -> Json:
        """The request log (perf.py): per route p50/p95/max, the slowest and newest requests, memory and load."""
        return perf.summary(max(1, min(minutes, 24 * 60)), route or None)

    # ---- OAuth for claude.ai (oauth.py) ----
    @app.get("/.well-known/oauth-protected-resource")
    @app.get("/.well-known/oauth-protected-resource/mcp")
    def oauth_resource(request: Request) -> Json:
        return oauth.resource(base_of(request))

    @app.get("/.well-known/oauth-authorization-server")
    @app.get("/.well-known/oauth-authorization-server/mcp")
    def oauth_meta(request: Request) -> Json:
        return oauth.metadata(base_of(request))

    @app.post("/oauth/register")
    async def oauth_register(request: Request) -> Response:
        try:
            return JSONResponse(oauth.register(json.loads(await request.body() or b"{}")), status_code=201)
        except ValueError:
            return JSONResponse({"error": "invalid_client_metadata", "error_description": "a JSON body"}, status_code=400)
        except oauth.OAuthError as ex:
            return JSONResponse(ex.body(), status_code=ex.status)

    def _form(raw: bytes) -> dict[str, str]:
        return {k: v[0] for k, v in parse_qs(raw.decode(errors="replace"), keep_blank_values=True).items()}

    @app.get("/oauth/authorize")
    def oauth_authorize(request: Request) -> Response:
        q = dict(request.query_params)
        try:
            c = oauth.check_authorize(q)
        except oauth.OAuthError as ex:
            return JSONResponse(ex.body(), status_code=ex.status)
        return HTMLResponse(oauth.page(q, c), headers={"cache-control": "no-store", "x-frame-options": "DENY"})

    @app.post("/oauth/authorize")
    async def oauth_approve(request: Request) -> Response:
        q = _form(await request.body())
        try:
            c = oauth.check_authorize(q)
        except oauth.OAuthError as ex:
            return JSONResponse(ex.body(), status_code=ex.status)
        d = doors.door("", "", "", q.get("token", "")) if q.get("token") and not q["token"].startswith("r5o_") else None
        if not d:
            time.sleep(1)   # a wrong token costs a second
            return HTMLResponse(oauth.page({k: v for k, v in q.items() if k != "token"}, c, "That is not one of this hub's tokens."),
                                status_code=401, headers={"cache-control": "no-store", "x-frame-options": "DENY"})
        seen.touch(d, *where(request), "/oauth/authorize")
        return RedirectResponse(oauth.approve({k: v for k, v in q.items() if k != "token"}, d), status_code=302)

    @app.post("/oauth/token")
    async def oauth_token(request: Request) -> Response:
        try:
            return JSONResponse(oauth.token(_form(await request.body())), headers={"cache-control": "no-store"})
        except oauth.OAuthError as ex:
            return JSONResponse(ex.body(), status_code=ex.status)

    @app.get("/api/oauth", response_model=None)
    def oauth_clients(request: Request) -> Response:
        if not str(request.state.door).startswith(("loopback", "tailnet:")):
            return JSONResponse({"error": "connectors are managed from the tailnet"}, status_code=403)
        return JSONResponse({"clients": [c | seen.of("oauth:" + c["name"]) for c in oauth.clients()], "public": PUBLIC or None})

    @app.post("/api/oauth", response_model=None)
    async def oauth_revoke(request: Request) -> Response:
        if not str(request.state.door).startswith(("loopback", "tailnet:")) or request.headers.get("x-relic5-request") != "1":
            return JSONResponse({"error": "connectors are managed from the tailnet, with X-Relic5-Request: 1"}, status_code=403)
        body = json.loads(await request.body() or b"{}")
        return JSONResponse({"revoked": oauth.revoke(str(body.get("client_id", "")))})

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
        if os.path.basename(name) != name or ext not in TYPES or not rfs.isfile(path):
            return JSONResponse({"error": "not found"}, status_code=404)
        return Response(open(path, "rb").read(), media_type=TYPES[ext], headers={"cache-control": "public, max-age=31536000, immutable"})

    @app.get("/api/month-recap", response_model=None)
    def month_recap(month: str) -> Response:
        """A sealed month's recap (bin/relic5-month-recap), markdown; 404 until one is written."""
        from . import sealday
        if len(month) != 7 or month[4] != "-" or not (month[:4] + month[5:]).isdigit():
            return JSONResponse({"error": "month is YYYY-MM"}, status_code=400)
        p = sealday.recap_path(relic.parts.root, month)
        if not rfs.isfile(p):
            return JSONResponse({"error": f"no recap for {month} yet"}, status_code=404)
        return Response(rfs.read_text(p), media_type="text/markdown; charset=utf-8")

    @app.get("/api/artifacts", response_model=None)
    @cached(60)
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
        if rfs.is_s3(path):
            return Response(rfs.read_bytes(path), media_type=mime, headers=h)
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
    @cached(120)
    def lineage_route() -> Json:
        from . import family
        return family.lineage(relic.parts.root)

    @app.get("/api/team", response_model=None)
    def team_route(days: int = 90) -> Json:
        from . import family
        return family.team(relic, max(7, min(days, 400)))

    @app.get("/api/oracles", response_model=None)
    @cached(60)
    def oracles_route() -> Json:
        from . import oracles
        return oracles.listing(relic)

    # ARRA Oracle Studio reading the hub (arra.py): /arra/api/*, its page on another origin
    from . import arra
    from . import __version__ as _ver
    from .status import status as _status
    app.include_router(arra.router(relic, lambda: swr.get("arra-status", 30, lambda: _status(root)), oracles_route, _ver))

    @app.get("/api/oracle", response_model=None)
    def oracle_route(name: str) -> Json:
        """One oracle brought to the human: its notes by section, sessions, rules, and the character and
        enlightenment prompts built from them (oracles.py)."""
        from . import oracles
        out = oracles.portrait(relic, name)
        return JSONResponse(out, status_code=404) if "error" in out else out   # type: ignore[return-value]

    @app.get("/api/map", response_model=None)
    @cached(120)
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
    @cached(60)
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
        import posixpath
        if rfs.is_s3(relic.parts.root):   # no links in a bucket: normalise the path and keep it under parts/
            base = relic.parts.root + "/parts"
            full = relic.parts.root + "/" + posixpath.normpath("/" + path).lstrip("/")
            rel = full[len(base) + 1:] if full.startswith(base + "/") else "../"
        else:
            base = os.path.realpath(os.path.join(relic.parts.root, "parts"))
            full = os.path.realpath(os.path.join(relic.parts.root, path))
            rel = os.path.relpath(full, base)
        if rel.startswith("..") or "/memory/" not in "/" + rel or not full.endswith(".md") or not rfs.isfile(full):
            return JSONResponse({"error": "not a memory note on this hub"}, status_code=404)
        return Response(rfs.read_text(full), media_type="text/markdown; charset=utf-8")

    @app.get("/api/log", response_model=None)
    def log(n: int = 100) -> list[JobEvent]:
        from .jobs import read
        return read(root)[0][:min(max(n, 1), 1000)]

    @app.get("/api/tail", response_model=None)
    @cached(5)
    def tail(n: int = 50, session: str = "", machine: str = "", since: str = "", full: int = 0) -> Json:
        return relic.tail(min(max(n, 1), 500), session or None, machine or None, since or None, bool(full))

    @app.get("/api/queries", response_model=None)
    @cached(15)
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
        if not rfs.exists(p):
            return []
        out: list[Json] = []
        for line in rfs.read_lines(p)[-min(max(n, 1), 2000):]:
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

    SWR_TOOLS = {"relic_status": 10, "relic_sessions": 30}   # seconds an answer stays fresh (swr.py)

    def make_route(tool: str) -> Callable[[Request], Response]:
        """The tool is bound by the closure, never a parameter: FastAPI would read a defaulted `tool` argument as a
        query parameter, and ?tool=... could pick which tool runs (found by the mypy pass, 2026-10-24)."""
        ttl = SWR_TOOLS.get(tool)

        def route(request: Request) -> Response:
            if ttl and not request.query_params.get("parent"):   # the page's polls, not a traced call
                ok, r = swr.get(f"{tool}?{sorted(request.query_params.multi_items())}", ttl, lambda: logged(
                    relic, tool, args_of(request.query_params), request.state.door, client_of(request, "http")))
            else:
                ok, r = logged(relic, tool, args_of(request.query_params), request.state.door, client_of(request, "http"))
            if ok:
                return Response(dumps(r), media_type="application/json")
            return JSONResponse({"error": r[1]}, status_code=STATUS_OF[r[0]])
        return route

    for path, tool in ROUTES.items():
        app.add_api_route(path, make_route(tool), methods=["GET"])


    if os.environ.get("RELIC5_WARM", "1") != "0":
        # the first page after a start asked every heavy route cold (Home 1.1 s, Knowledge 2.2 s, measured in a browser
        # 2026-10-25): ask them once here, through the app itself on the loopback door, so swr.py holds the answers
        WARM = ["/api/status", "/api/sessions?limit=500", "/api/sessions?limit=0", "/api/memory", "/api/oracles", "/api/homes",
                "/api/queries", "/api/map?limit=3000", "/api/clients", "/api/tail?n=50"]

        def _warm() -> None:
            import asyncio
            import httpx
            async def go() -> None:
                t = httpx.ASGITransport(app=app, client=("127.0.0.1", 0))
                async with httpx.AsyncClient(transport=t, base_url="http://127.0.0.1", timeout=300) as c:
                    for u in WARM:
                        try:
                            await c.get(u)
                        except Exception:
                            pass
            time.sleep(3)
            asyncio.run(go())
        threading.Thread(target=_warm, name="relic5-warm-pages", daemon=True).start()

    return app
