"""mcp.py: the five relic tools and the MCP JSON-RPC handler.

Tool names and input schemas are agent-relic-v3's (src/mcp/tools.ts @9f0bdb5), so a client switches from relic3 to
relic5 without changing its prompts. The JSON-RPC handling follows v3 src/mcp/server.ts: initialize, ping,
tools/list, tools/call; a notification gets no reply; a tool failure is a result with isError, not a protocol error.
Unknown arguments are errors (a typo must not silently mean "no filter").

Accepted but not served yet, each with a clear error: semantic (embed milestone), via / chat / from_user / cwd
(relic-extract's parts do not carry them).
"""
import json, os
from collections.abc import Callable, Iterable
from typing import Any

from . import __version__
from .query import DEFAULT_LIMIT, NotFound, Relic5, UsageError
from .status import status
from .types_ import Json

SERVER_INFO: Json = {"name": "relic5", "title": "relic5", "version": __version__}
_PUB = os.environ.get("RELIC5_PUBLIC_URL", "").rstrip("/")
if _PUB:   # the icon a client such as claude.ai shows beside the connector (MCP Implementation.icons)
    SERVER_INFO |= {"websiteUrl": "https://relic5.buildwithoracle.com", "icons": [
        {"src": f"{_PUB}/icon-512.png", "mimeType": "image/png", "sizes": ["512x512"]},
        {"src": f"{_PUB}/favicon.svg", "mimeType": "image/svg+xml", "sizes": ["any"]}]}
SUPPORTED = ["2025-06-18", "2025-03-26", "2024-11-05"]

STR = {"type": "string"}
INT = {"type": "integer", "minimum": 0}
SEARCH_PROPS = {
    "query": {**STR, "description": "BM25 (ICU tokens, Thai inside words works): ANY term matches and hits are ranked, so "
              "every extra word widens the result. BM25 finds TOPICS, not facts: for 'did I already do X' search the most unique "
              "literal string (an id, a filename, an error), not topic words (relic3's measured advice). With semantic: meaning."},
    "sort": {**STR, "enum": ["relevant", "newest"], "description": "relevant (default) | newest: the most relevant 600, newest first"},
    "horizon": {**STR, "description": "7d | 15d | 1m | 3m | archive: search only that window. Default (none): widen 7d -> 15d -> 1m -> 3m -> archive until 10 hits, then add the best older hits after them (older_hits, note), so every month is searched; exclusive with since/until"},
    "since": {**STR, "description": "YYYY-MM-DD (from 00:00:00Z of that UTC day), an ISO time, or Nd/Nh/Nm before now (1m = one minute)"},
    "until": {**STR, "description": "YYYY-MM-DD (through 23:59:59Z of that UTC day), an ISO time, or Nd/Nh/Nm before now"},
    "repo": STR, "session": {**STR, "description": "session uuid prefix"}, "role": STR, "tier": STR,
    "via": {**STR, "description": "channel the session came in by, substring, case-blind (discord matches plugin:discord:discord)"},
    "chat": {**STR, "description": "the chat / room / thread id, substring"},
    "from_user": {**STR, "description": "who sent the session's first channel message, substring, case-blind"},
    "cwd": {**STR, "description": "sessions that began in this folder or below it (relic-scan meta cwd)"},
    "branch": {**STR, "description": "sessions on this git branch"},
    "home": {**STR, "description": "whose .claude (or .codex) the message was written in, a substring of its folder, case-blind: "
             "/Users/nat/.claude, beta/.claude, .claude1, a project's own .../.claude-hello/.claude. relic_homes lists them"},
    "title": {**STR, "description": "sessions whose host title contains this (case-blind)"},
    "with": {**STR, "enum": ["tools", "thinking", "vault", "memory", "git", "all"], "description": "also search tool calls, thinking, ψ notes, or all; memory = only the agents' memory notes (rules, decisions, references; role memory-feedback / memory-project / memory-reference / memory-user); git = only git commits of every ghq repo, back to 2025 when no transcript survives (role commit-claude = Claude co-wrote it, commit-codex, commit)"},
    "limit": {"type": "integer", "minimum": 1, "description": f"default {DEFAULT_LIMIT}"},
    "cursor": {**STR, "description": "next_cursor from a previous result"},
    "semantic": {"type": "boolean", "description": "route to semantic search (errors if unavailable)"},
    "model": {"type": "string", "description": "with semantic: which vector table (its model or slug), when the root holds more than one"},
    "min_chars": {"type": "integer", "minimum": 0, "description": "with semantic: skip texts shorter than this (default 80: tiny chatter sits near every short query)"},
    "hybrid": {"type": "boolean", "description": "with semantic + vector: fuse BM25 and vector ranks (reciprocal-rank fusion)"},
    "vector": {"type": "array", "items": {"type": "number"}, "description": "with semantic: the query embedded by the client "
               "(same model@hash, unit length); `relic5 mcp` on a Mac adds it. Without it semantic answers by keyword and says so"},
}
PARENT = {**STR, "description": "trace.id of the call this one follows from (a search you are narrowing, the search whose hit you "
          "open): the hub links them into one trace chain, read back with relic_trace. Every result carries trace {id, root, parent}"}
SEARCH_PROPS["parent"] = PARENT
TOOLS = [
    {"name": "relic_search", "description": "Search every machine's history on the relic5 hub: BM25 over ICU tokens (Thai-aware), widening "
     "7d → 15d → 1m → 3m → archive until 10 hits; semantic=true is a separate mode (never blended unless hybrid=true). "
     "Hits flag `ephemeral` paths (/tmp, scratchpad, claude-<pid>) that may be gone.",
     "inputSchema": {"type": "object", "properties": SEARCH_PROPS, "required": ["query"], "additionalProperties": False}},
    {"name": "relic_show", "description": "Show one message (msgkey | relic5:// link | session id + seq) with its neighbours in the session.",
     "inputSchema": {"type": "object", "properties": {"id": STR, "seq": INT, "before": INT, "after": INT, "parent": PARENT}, "required": ["id"],
                     "additionalProperties": False}},
    {"name": "relic_sessions", "description": "List top-level sessions, newest first. Subagent and workflow-agent sessions are not listed: each folds "
                    "into its parent's `children` count, so `total` is smaller than relic-scan's session count (it counts every tier).",
     "inputSchema": {"type": "object", "properties": {"repo": STR, "since": STR, "until": STR, "limit": INT,
                     "via": SEARCH_PROPS["via"], "chat": SEARCH_PROPS["chat"], "from_user": SEARCH_PROPS["from_user"], "parent": PARENT,
                     "home": SEARCH_PROPS["home"],
                     "by_repo": {"type": "boolean", "description": "also return repos: sessions and events per repo for the same window and filters, most first (a session with no repo counts as '(no repo) <tenant>')"}},
                     "additionalProperties": False}},
    {"name": "relic_session", "description": "Resolve a session id prefix to its session record and subagent tree.",
     "inputSchema": {"type": "object", "properties": {"id": STR, "parent": PARENT}, "required": ["id"], "additionalProperties": False}},
    {"name": "relic_trace", "description": "The trace log. With id (a trace.id from any result): the whole chain it belongs to, oldest "
     "first: each search with its first 10 hits as links, each message or session opened from it, the narrower searches after "
     "it and the saved-search runs made from it, with depth by parent. Without id: the newest chains.",
     "inputSchema": {"type": "object", "properties": {"id": STR, "limit": INT}, "additionalProperties": False}},
    {"name": "relic_saved", "description": "Saved searches: a search kept as a job that the hub re-runs (default every 60 minutes) and "
     "links into the chain of the search it came from; each run says how many hits are new (Jobs page, relic_trace). action list "
     "(default) | add (from: a search's trace.id, or query and the search's filters in args; every: minutes; name) | remove (id).",
     "inputSchema": {"type": "object", "properties": {"action": {**STR, "enum": ["list", "add", "remove"]}, "id": STR, "from": STR,
                                                      "query": STR, "args": {"type": "object"}, "every": {"type": "integer", "minimum": 5},
                                                      "name": STR}, "additionalProperties": False}},
    {"name": "relic_asked", "description": "What was asked of the hub in a period, to pick up later what a person or an agent was "
     "looking into: every distinct search (how often, hits, when, who), the ones that found nothing, the found notes (an "
     "agent's relic_found, or Nat's \"Keep this hit\" on the Search page) with their links, and the chains. since/until: "
     "YYYY-MM-DD (a Bangkok day), an ISO time, or Nd/Nh before now; default the last 24 hours.",
     "inputSchema": {"type": "object", "properties": {"since": STR, "until": STR, "limit": INT}, "additionalProperties": False}},
    {"name": "relic_tag", "description": "Put labels on something found, like digger's node tags: a message (its relic5:// link), "
     "a session (its id) or a search (its trace.id). add and remove are lists of tags (letters, digits, Thai, - . / _); a "
     "note says why. Read them back with relic_tags.",
     "inputSchema": {"type": "object", "properties": {"target": STR, "add": {"type": "array", "items": STR},
                                                      "remove": {"type": "array", "items": STR}, "note": STR},
                     "required": ["target"], "additionalProperties": False}},
    {"name": "relic_tags", "description": "Tags on the hub: with tag, everything carrying it (newest first, with notes); with "
     "target, that thing's tags; with neither, every tag and its count. since/until as relic_asked.",
     "inputSchema": {"type": "object", "properties": {"tag": STR, "target": STR, "since": STR, "until": STR}, "additionalProperties": False}},
    {"name": "relic_found", "description": "Close a search with what came of it, so the next agent (and Nat, on the Asked page) can "
     "see it: what you were looking for (goal), how you searched (how: the words, layers and windows you tried, what did not "
     "work), and what you found (found; links: the relic5:// links or session ids that answer it). parent is the trace.id of "
     "the call that found it. The hub adds the chain's own count of searches and opened hits. found: \"nothing\" is worth "
     "noting too.",
     "inputSchema": {"type": "object", "properties": {"parent": {**STR, "description": "trace.id of the call that answered (or the last one tried)"},
                                                      "goal": STR, "how": STR, "found": STR,
                                                      "links": {"type": "array", "items": {"type": "string"}}},
                     "required": ["parent", "goal", "found"], "additionalProperties": False}},
    {"name": "relic_homes", "description": "Where the history comes from: every .claude (or .codex) folder, per machine, with "
     "relic-scan's user@host, sessions, messages and first/last time: nat's ~/.claude, beta's, ~/.claude1, a project's own "
     ".claude. Use a home with relic_search or relic_sessions (home=).",
     "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False}},
    {"name": "relic_status", "description": "Months, per-machine watermarks, totals, jobs and warnings (StatusReport).",
     "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False}},
    {"name": "relic_artifact_put", "description": "Keep something you made for an oracle on the hub: an image (png jpg webp gif svg), "
     "a video (mp4 webm mov), a 3D model (glb gltf) or a small web piece (html). It shows on the oracle's page in the hub "
     "(Oracles tab). Send the file as base64 in data with filename, or an HTML/SVG piece as text with ext. Add the prompt "
     "that made it, so the record says how. The same bytes again return the first record. Up to 60 MB.",
     "inputSchema": {"type": "object", "properties": {"oracle": STR, "title": STR, "filename": STR, "ext": STR, "data": STR, "text": STR,
                                                      "note": STR, "prompt": STR, "session": STR},
                     "required": ["oracle"], "additionalProperties": False}},
    {"name": "relic_artifacts", "description": "List the artifacts kept on the hub, newest first: one oracle's, or every oracle's with a count each.",
     "inputSchema": {"type": "object", "properties": {"oracle": STR, "limit": INT}, "additionalProperties": False}},
]
INSTRUCTIONS = (
    "relic5 holds every machine's Claude Code and Codex history. Search the rarest literal first (an id, a filename, an "
    "error), not topic words. Every search, show and session result carries trace {id, root, parent}: pass parent=<the "
    "trace.id you are following> on your next call (opening a hit, a narrower search, another try), so the hub keeps one "
    "trace chain per question. When you have the answer, or are giving up, call relic_found {parent, goal, how, found, "
    "links} once: what you looked for, how you searched, and what you found. relic_trace {id} reads a chain back; "
    "relic_asked {since, until} tells what was looked into in a period and what was found.")
UNAVAILABLE = {
    "relic_chain": "relic_chain is not available in relic5 (as in relic3 v3)",
    "relic_now": "relic_now is not available in relic5; use relic_sessions with since=1h",
    "relic_pending": "relic_pending is not available in relic5; relic_status reports pending/warnings",
}
# (True, the tool's reply) or (False, (kind, error)); Any because mypy cannot narrow the second item by the first
ToolReply = tuple[bool, Any]
ToolCall = Callable[[Relic5, str, Json, str | None], ToolReply]


def _check(args: Iterable[str], allowed: list[str]) -> None:
    for k in args:
        if k not in allowed:
            raise UsageError(f"unknown argument {json.dumps(k)} (allowed: {', '.join(allowed) or 'none'})")


def _str(a: Json, k: str) -> str | None:
    v = a.get(k)
    if v is not None and not isinstance(v, str):
        raise UsageError(f"{k} must be a string")
    return v


def _int(a: Json, k: str, minimum: int = 0) -> int | None:
    v = a.get(k)
    if v is None:
        return None
    if isinstance(v, bool) or not isinstance(v, int) or v < minimum:
        raise UsageError(f"{k} must be a whole number >= {minimum}")
    return v


def run_tool(relic: Relic5, name: str, a: Json, door: str | None = None) -> Json:
    if name == "relic_tag":
        from . import trace
        _check(a, ["target", "add", "remove", "note"])
        for k in ("add", "remove"):
            if a.get(k) is not None and (not isinstance(a[k], list) or not all(isinstance(x, str) for x in a[k])):
                raise UsageError(f"{k} must be a list of strings")
        return trace.tag(relic.parts.root, _str(a, "target") or "", a.get("add"), a.get("remove"), door, _str(a, "note"))
    if name == "relic_tags":
        from . import trace
        _check(a, ["tag", "target", "since", "until"])
        if a.get("target"):
            t = trace.tags_of(relic.parts.root).get(str(a["target"]))
            return t or {"target": a["target"], "tags": [], "notes": []}
        return trace.tagged(relic.parts.root, _str(a, "tag"), _str(a, "since"), _str(a, "until"))
    if name == "relic_asked":
        from . import trace
        from .window import WindowError
        _check(a, ["since", "until", "limit"])
        try:
            return trace.asked(relic.parts.root, _str(a, "since") or ("1d" if not a.get("until") else None), _str(a, "until"), min(_int(a, "limit", 1) or 50, 500))
        except WindowError as ex:
            raise UsageError(str(ex))
    if name == "relic_found":
        from . import trace
        _check(a, ["parent", "goal", "how", "found", "links"])
        for k in ("parent", "goal", "how", "found"):
            _str(a, k)
        if not a.get("parent") or not a.get("goal") or not a.get("found"):
            raise UsageError("relic_found needs parent (a trace.id), goal and found")
        links = a.get("links") or []
        if not isinstance(links, list) or not all(isinstance(x, str) for x in links):
            raise UsageError("links must be a list of strings")
        ch = trace.chain(relic.parts.root, str(a["parent"]))
        if "error" in ch:
            raise NotFound(ch["error"])
        return {"noted": True, "root": ch["root"], "searches": ch["searches"], "opened": ch["opened"], "steps": len(ch["steps"]) + 1}
    if "parent" in a:   # the trace link is the hub's (api.logged), not the tool's
        _str(a, "parent")
        a = {k: v for k, v in a.items() if k != "parent"}
    if name == "relic_trace":
        from . import trace
        _check(a, ["id", "limit"])
        rid = _str(a, "id")
        if rid:
            out = trace.chain(relic.parts.root, rid)
            if "error" in out:
                raise NotFound(out["error"])
            return out
        return {"chains": trace.chains(relic.parts.root, min(_int(a, "limit", 1) or 30, 200))}
    if name == "relic_saved":
        from . import trace
        _check(a, ["action", "id", "from", "query", "args", "every", "name"])
        act = _str(a, "action") or "list"
        if act == "add":
            if a.get("args") is not None and not isinstance(a["args"], dict):
                raise UsageError("args must be an object")
            return trace.save(relic.parts.root, _str(a, "from"), _str(a, "query"), a.get("args"), _int(a, "every", 5) or 60, _str(a, "name"), door)
        if act == "remove":
            return trace.remove(relic.parts.root, _str(a, "id") or "")
        if act != "list":
            raise UsageError("action is list | add | remove")
        return {"saved": trace.public(trace.saved(relic.parts.root))}
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
        r = relic.search(_str(a, "query"), since=_str(a, "since"), until=_str(a, "until"), horizon=_str(a, "horizon"),
                         repo=_str(a, "repo"), session=_str(a, "session"), role=_str(a, "role"), tier=_str(a, "tier"),
                         with_=_str(a, "with"), limit=min(_int(a, "limit", 1) or DEFAULT_LIMIT, 100), cursor=_str(a, "cursor"),
                         vector=vec, model=_str(a, "model") if vec is not None else None,
                         hybrid=bool(a.get("hybrid")) and vec is not None, sort=_str(a, "sort"), cwd=_str(a, "cwd"), branch=_str(a, "branch"), title=_str(a, "title"),
                         via=_str(a, "via"), chat=_str(a, "chat"), from_user=_str(a, "from_user"), home=_str(a, "home"),
                         min_chars=_int(a, "min_chars") if vec is not None else None)
        if note:   # keep the search's own note (older hits) after this one; never overwrite it (regression of #20)
            r = r | {"note": note + (f" · {r['note']}" if r.get("note") else "")}
        return r
    if name == "relic_show":
        _check(a, ["id", "seq", "before", "after"])
        before, after = _int(a, "before"), _int(a, "after")
        return relic.show(_str(a, "id"), seq=_int(a, "seq"), before=min(2 if before is None else before, 50),
                          after=min(2 if after is None else after, 50))
    if name == "relic_sessions":
        _check(a, ["repo", "since", "until", "limit", "via", "chat", "from_user", "by_repo", "home"])
        return relic.sessions(repo=_str(a, "repo"), since=_str(a, "since"), until=_str(a, "until"), limit=min(_int(a, "limit") or DEFAULT_LIMIT, 500),
                              via=_str(a, "via"), chat=_str(a, "chat"), from_user=_str(a, "from_user"), by_repo=a.get("by_repo") is True,
                              home=_str(a, "home"))
    if name == "relic_session":
        _check(a, ["id"])
        return relic.session(_str(a, "id"))
    if name == "relic_artifact_put":
        from . import artifacts
        _check(a, ["oracle", "title", "filename", "ext", "data", "text", "note", "prompt", "session"])
        for k in ("oracle", "title", "filename", "ext", "data", "text", "note", "prompt", "session"):
            _str(a, k)
        return artifacts.put_b64(relic.parts.root, a, door)
    if name == "relic_artifacts":
        from . import artifacts
        _check(a, ["oracle", "limit"])
        return artifacts.listing(relic.parts.root, _str(a, "oracle"), min(_int(a, "limit", 1) or 100, 500))
    if name == "relic_homes":
        _check(a, [])
        return relic.homes()
    if name == "relic_status":
        _check(a, [])
        return {"you": door, **status(relic.parts.root)}
    raise UsageError(f"unknown tool {json.dumps(name)}")


def call_tool(relic: Relic5, name: str, args: object, door: str | None = None) -> ToolReply:
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


def _ok(i: object, result: Json) -> Json:
    return {"jsonrpc": "2.0", "id": i, "result": result}


def _err(i: object, code: int, message: str) -> Json:
    return {"jsonrpc": "2.0", "id": i, "error": {"code": code, "message": message}}


def handle(relic: Relic5, msg: object, door: str | None = None, call: ToolCall | None = None) -> Json | None:
    """One JSON-RPC message -> its reply, or None for a notification."""
    if not isinstance(msg, dict) or msg.get("jsonrpc") != "2.0" or not isinstance(msg.get("method"), str):
        return _err(msg.get("id") if isinstance(msg, dict) else None, -32600, "invalid request")
    note, i, method, params = "id" not in msg, msg.get("id"), msg["method"], msg.get("params") or {}
    if method == "initialize":
        want = params.get("protocolVersion")
        return _ok(i, {"protocolVersion": want if want in SUPPORTED else SUPPORTED[0],
                       "capabilities": {"tools": {"listChanged": False}}, "serverInfo": SERVER_INFO, "instructions": INSTRUCTIONS})
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
        ok, r = (call or call_tool)(relic, name, params.get("arguments") or {}, door)
        if ok:
            return _ok(i, {"content": [{"type": "text", "text": json.dumps(r, ensure_ascii=False, default=str)}]})
        return _ok(i, {"isError": True, "content": [{"type": "text", "text": r[1]}]})
    return None if note else _err(i, -32601, f"method not found: {method}")
