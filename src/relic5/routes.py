"""routes.py: the hub's read-only GET routes as plain functions, shared by the hub (api.py) and by embedded mode (local.py).

Each returns (status, body): 200 and the answer, or 400/404 and {"error": ...}, exactly what the hub sends. api.py wraps
them in FastAPI routes; local.py calls them in-process when no hub runs (issue #311), so one implementation answers
both ways. Nothing here writes: the hub's query log and trace records are api.logged's, around these calls.
"""
from collections.abc import Iterable
from typing import TYPE_CHECKING

from .types_ import Json

if TYPE_CHECKING:
    from .query import Relic5

Reply = tuple[int, Json]

ROUTES = {"/api/search": "relic_search", "/api/show": "relic_show", "/api/sessions": "relic_sessions",
          "/api/session": "relic_session", "/api/status": "relic_status",
          # time travel (timetravel.py, #278 #279 #281)
          "/api/chain": "relic_chain", "/api/at": "relic_at", "/api/arc": "relic_arc",
          # skills a human typed (skills.py, #299)
          "/api/skills": "relic_skills"}
"""GET routes that are one MCP tool each: the query string becomes the tool's arguments (args_of)."""
INT_KEYS = {"limit", "seq", "before", "after", "cap", "top"}
BOOL_KEYS = {"semantic", "by_repo", "sessions", "all", "auto", "ai"}
STATUS_OF = {"usage": 400, "unavailable": 501, "not_found": 404, "failed": 500}


def args_of(items: Iterable[tuple[str, str]]) -> Json:
    """Query string pairs -> tool args, as v3 http.ts argsOf: q -> query, ints and the semantic boolean coerced."""
    a: Json = {}
    for k0, v in items:
        k = "query" if k0 == "q" else k0.replace("-", "_")
        a[k] = int(v) if k in INT_KEYS and v.isdigit() else (v in ("1", "true")) if k in BOOL_KEYS else v
    return a


def conversation(relic: "Relic5", id: str, offset: int = 0, limit: int = 200, tools: int = 0, role: str = "",
                 since: str = "", until: str = "") -> Reply:
    from .recap import conversation as conv
    from .query import NotFound, UsageError
    try:
        return 200, conv(relic, id, max(offset, 0), min(max(limit, 0), 1000), bool(tools), role or None, since or None, until or None)
    except (NotFound, UsageError) as ex:
        return (404 if isinstance(ex, NotFound) else 400), {"error": str(ex)}


def recap(relic: "Relic5", id: str, limit: int = 20) -> Reply:
    from .recap import recap as rc
    from .query import NotFound, UsageError
    try:
        return 200, rc(relic, id, max(limit, 0))
    except (NotFound, UsageError) as ex:
        return (404 if isinstance(ex, NotFound) else 400), {"error": str(ex)}


def handoff(relic: "Relic5", id: str, user_only: int = 0) -> Reply:
    from .recap import handoff as ho
    from .query import NotFound, UsageError
    try:
        return 200, ho(relic, id, bool(user_only))
    except (NotFound, UsageError) as ex:
        return (404 if isinstance(ex, NotFound) else 400), {"error": str(ex)}


def readings(relic: "Relic5", since: str = "", until: str = "", grain: str = "", model: str = "", q: str = "",
             limit: int = 50, offset: int = 0) -> Reply:
    from . import readings as rd
    try:
        return 200, rd.readings(relic.parts.root, since or None, until or None, grain or None, model or None, q or None,
                                min(max(limit, 1), 500), max(offset, 0))
    except ValueError as ex:
        return 400, {"error": str(ex)}


def tail(relic: "Relic5", n: int = 50, session: str = "", machine: str = "", since: str = "", full: int = 0) -> Reply:
    return 200, relic.tail(min(max(n, 1), 500), session or None, machine or None, since or None, bool(full))


def searched(relic: "Relic5", q: str = "", link: str = "", since: str = "", until: str = "", limit: int = 20) -> Reply:
    """Search the searched: past queries, found notes and tags (q), or the way back from a message (link)."""
    from . import trace
    from .query import UsageError
    from .window import WindowError
    try:
        return 200, trace.searched(relic.parts.root, q or None, link or None, since or None, until or None, max(1, min(limit, 200)))
    except (UsageError, WindowError) as ex:
        return 400, {"error": str(ex)}


def trace_chain(relic: "Relic5", id: str = "", limit: int = 30) -> Reply:
    """One record's whole chain (id), or the newest chains."""
    from . import trace
    if id:
        out = trace.chain(relic.parts.root, id)
        return (404 if "error" in out else 200), out
    return 200, {"chains": trace.chains(relic.parts.root, max(1, min(limit, 200)))}


def memory(relic: "Relic5") -> Reply:
    from . import memory as mem
    return 200, dict(mem.listing(relic.parts.root))


GET = {"/api/conversation": conversation, "/api/recap": recap, "/api/handoff": handoff, "/api/readings": readings, "/api/memory": memory,
       "/api/tail": tail, "/api/searched": searched, "/api/trace": trace_chain}
"""path -> function, for embedded mode; the parameters are the function's own (typed as the hub's FastAPI routes)."""
