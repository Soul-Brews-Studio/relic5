"""mcp.py: the five relic tools and the MCP JSON-RPC handler.

Tool names and input schemas are agent-relic-v3's (src/mcp/tools.ts @9f0bdb5), so a client switches from relic3 to
relic5 without changing its prompts. The JSON-RPC handling follows v3 src/mcp/server.ts: initialize, ping,
tools/list, tools/call; a notification gets no reply; a tool failure is a result with isError, not a protocol error.
Unknown arguments are errors (a typo must not silently mean "no filter").

Accepted but not served yet, each with a clear error: semantic (embed milestone), via / chat / from_user / cwd
(relic-extract's parts do not carry them).
"""
import json

from . import __version__
from .query import DEFAULT_LIMIT, NotFound, UsageError
from .status import status

SERVER_INFO = {"name": "relic5", "version": __version__}
SUPPORTED = ["2025-06-18", "2025-03-26", "2024-11-05"]

STR = {"type": "string"}
INT = {"type": "integer", "minimum": 0}
SEARCH_PROPS = {
    "query": {**STR, "description": "keyword query: every word must occur (Thai substrings work)"},
    "horizon": {**STR, "description": "7d | 15d | 1m | 3m | archive (default archive: every month); exclusive with since/until"},
    "since": {**STR, "description": "YYYY-MM-DD (from 00:00:00Z of that UTC day), an ISO time, or Nd/Nh/Nm before now (1m = one minute)"},
    "until": {**STR, "description": "YYYY-MM-DD (through 23:59:59Z of that UTC day), an ISO time, or Nd/Nh/Nm before now"},
    "repo": STR, "session": {**STR, "description": "session uuid prefix"}, "role": STR, "tier": STR, "via": STR, "chat": STR,
    "from_user": STR,
    "cwd": {**STR, "description": "where a session ran (not in relic5 yet)"},
    "with": {**STR, "enum": ["tools", "thinking", "vault", "all"], "description": "also search tool calls, thinking, ψ notes, or all"},
    "limit": {"type": "integer", "minimum": 1, "description": f"default {DEFAULT_LIMIT}"},
    "cursor": {**STR, "description": "next_cursor from a previous result"},
    "semantic": {"type": "boolean", "description": "route to semantic search (errors if unavailable)"},
    "model": {"type": "string", "description": "with semantic: which vector table (its model or slug), when the root holds more than one"},
    "hybrid": {"type": "boolean", "description": "with semantic + vector: fuse BM25 and vector ranks (reciprocal-rank fusion)"},
    "vector": {"type": "array", "items": {"type": "number"}, "description": "with semantic: the query embedded by the client "
               "(same model@hash, unit length); `relic5 mcp` on a Mac adds it. Without it semantic answers by keyword and says so"},
}
TOOLS = [
    {"name": "relic_search", "description": "Search every machine's history on the relic5 hub (keyword; Thai-aware), month partitions.",
     "inputSchema": {"type": "object", "properties": SEARCH_PROPS, "required": ["query"], "additionalProperties": False}},
    {"name": "relic_show", "description": "Show one message (msgkey | relic5:// link | session id + seq) with its neighbours in the session.",
     "inputSchema": {"type": "object", "properties": {"id": STR, "seq": INT, "before": INT, "after": INT}, "required": ["id"],
                     "additionalProperties": False}},
    {"name": "relic_sessions", "description": "List top-level sessions, newest first. Subagent and workflow-agent sessions are not listed: each folds "
                    "into its parent's `children` count, so `total` is smaller than relic-scan's session count (it counts every tier).",
     "inputSchema": {"type": "object", "properties": {"repo": STR, "since": STR, "until": STR, "limit": INT}, "additionalProperties": False}},
    {"name": "relic_session", "description": "Resolve a session id prefix to its session record and subagent tree.",
     "inputSchema": {"type": "object", "properties": {"id": STR}, "required": ["id"], "additionalProperties": False}},
    {"name": "relic_status", "description": "Months, per-machine watermarks, totals, jobs and warnings (StatusReport).",
     "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False}},
]
UNAVAILABLE = {
    "relic_chain": "relic_chain is not available in relic5 (as in relic3 v3)",
    "relic_now": "relic_now is not available in relic5; use relic_sessions with since=1h",
    "relic_trace": "relic_trace is not available in relic5; use relic_search then relic_show",
    "relic_pending": "relic_pending is not available in relic5; relic_status reports pending/warnings",
}


def _check(args, allowed):
    for k in args:
        if k not in allowed:
            raise UsageError(f"unknown argument {json.dumps(k)} (allowed: {', '.join(allowed) or 'none'})")


def _str(a, k):
    v = a.get(k)
    if v is not None and not isinstance(v, str):
        raise UsageError(f"{k} must be a string")
    return v


def _int(a, k, minimum=0):
    v = a.get(k)
    if v is None:
        return None
    if isinstance(v, bool) or not isinstance(v, int) or v < minimum:
        raise UsageError(f"{k} must be a whole number >= {minimum}")
    return v


def run_tool(relic, name, a, door=None):
    if name == "relic_search":
        _check(a, list(SEARCH_PROPS))
        vec = a.get("vector")
        if ("model" in a or vec is not None) and not a.get("semantic"):
            raise UsageError("model and vector only apply with semantic")
        if vec is not None and (not isinstance(vec, list) or not vec or not all(isinstance(x, (int, float)) for x in vec)):
            raise UsageError("vector must be a non-empty list of numbers")
        note = None
        if a.get("semantic") and vec is None:   # the hub embeds nothing: no vector, answer by keyword and say so
            note = "semantic needs the query embedded by the client (relic5 mcp on a Mac adds `vector`): these are keyword hits"
        for k in ("via", "chat", "from_user", "cwd"):
            if a.get(k) is not None:
                raise UsageError(f"{k} is not available on relic5 yet: relic-extract's parts do not carry it")
        r = relic.search(_str(a, "query"), since=_str(a, "since"), until=_str(a, "until"), horizon=_str(a, "horizon"),
                         repo=_str(a, "repo"), session=_str(a, "session"), role=_str(a, "role"), tier=_str(a, "tier"),
                         with_=_str(a, "with"), limit=min(_int(a, "limit", 1) or DEFAULT_LIMIT, 100), cursor=_str(a, "cursor"),
                         vector=vec, model=_str(a, "model") if vec is not None else None,
                         hybrid=bool(a.get("hybrid")) and vec is not None)
        return {"note": note, **r} if note else r
    if name == "relic_show":
        _check(a, ["id", "seq", "before", "after"])
        before, after = _int(a, "before"), _int(a, "after")
        return relic.show(_str(a, "id"), seq=_int(a, "seq"), before=min(2 if before is None else before, 50),
                          after=min(2 if after is None else after, 50))
    if name == "relic_sessions":
        _check(a, ["repo", "since", "until", "limit"])
        return relic.sessions(repo=_str(a, "repo"), since=_str(a, "since"), until=_str(a, "until"), limit=min(_int(a, "limit") or DEFAULT_LIMIT, 500))
    if name == "relic_session":
        _check(a, ["id"])
        return relic.session(_str(a, "id"))
    if name == "relic_status":
        _check(a, [])
        return {"you": door, **status(relic.parts.root)}
    raise UsageError(f"unknown tool {json.dumps(name)}")


def call_tool(relic, name, args, door=None):
    """-> (ok, data | (kind, error))."""
    if name in UNAVAILABLE:
        return False, ("unavailable", UNAVAILABLE[name])
    if not isinstance(args, dict):
        return False, ("usage", "arguments must be an object")
    try:
        return True, run_tool(relic, name, args, door)
    except UsageError as ex:
        return False, ("usage", str(ex))
    except NotFound as ex:
        return False, ("not_found", str(ex))
    except Exception as ex:   # the caller sees it as a failed tool, the server stays up
        return False, ("failed", f"{type(ex).__name__}: {ex}")


def _ok(i, result):
    return {"jsonrpc": "2.0", "id": i, "result": result}


def _err(i, code, message):
    return {"jsonrpc": "2.0", "id": i, "error": {"code": code, "message": message}}


def handle(relic, msg, door=None):
    """One JSON-RPC message -> its reply, or None for a notification."""
    if not isinstance(msg, dict) or msg.get("jsonrpc") != "2.0" or not isinstance(msg.get("method"), str):
        return _err(msg.get("id") if isinstance(msg, dict) else None, -32600, "invalid request")
    note, i, method, params = "id" not in msg, msg.get("id"), msg["method"], msg.get("params") or {}
    if method == "initialize":
        want = params.get("protocolVersion")
        return _ok(i, {"protocolVersion": want if want in SUPPORTED else SUPPORTED[0],
                       "capabilities": {"tools": {"listChanged": False}}, "serverInfo": SERVER_INFO})
    if method == "ping":
        return None if note else _ok(i, {})
    if method == "tools/list":
        return _ok(i, {"tools": TOOLS})
    if method == "tools/call":
        name = params.get("name")
        if not isinstance(name, str):
            return _err(i, -32602, "tools/call needs params.name")
        if name not in {t["name"] for t in TOOLS} and name not in UNAVAILABLE:
            return _err(i, -32602, f"unknown tool {json.dumps(name)}")
        ok, r = call_tool(relic, name, params.get("arguments") or {}, door)
        if ok:
            return _ok(i, {"content": [{"type": "text", "text": json.dumps(r, ensure_ascii=False, default=str)}]})
        return _ok(i, {"isError": True, "content": [{"type": "text", "text": r[1]}]})
    return None if note else _err(i, -32601, f"method not found: {method}")
