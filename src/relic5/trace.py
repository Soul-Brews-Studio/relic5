"""trace.py: search records, trace chains, the paged access log, and saved searches that run as jobs.

Nat, 2026-10-24: "when each search and we store the result then can we create a new job to link to that search too?
and can we support the trace and trace chained trace log?", "trace log trace chain? mcp support? and link?"

  record   every tool call already writes one line to logs/queries.jsonl (selfknow.finish). Each line now also has an
           `id` (10 hex), the `parent` it came from (a client passes parent=<id> with its next call), the chain's
           `root`, the call's `args` (no vector) and, for a search, `top`: its first 10 hits as links, enough to open
           or replay it. Tool results carry {"trace": {id, root, parent}} so an agent can pass the id on.
  chain    every record with the same root, in order, as a tree by parent: a search, the hits opened from it, the
           narrower search after it, the saved-search runs made from it (GET /api/trace?id=, MCP relic_trace).
  access   the log itself, newest first, filtered and paged (GET /api/access).
  saved    logs/saved.json: a search kept as a job. keep_running() re-runs each one when due (default hourly) with
           parent = the record it was saved from, so every run sits in that search's chain, and writes a jobs.jsonl
           event saying how many hits are new since the last run (the Jobs page shows it).

The log stays on the hub (0600), never in git: the same rule as selfknow.py.
"""
import json, os, secrets, threading, time
from collections.abc import Callable, Iterable

from .types_ import Json

TOP = 10
KEEP_ROWS = 200_000          # parsed rows held in memory (about 10 weeks at the hub's present rate)
SEEN = 500                   # links remembered per saved search, to tell new hits from old ones
_lock = threading.Lock()
_cache: dict[str, tuple[int, list[Json]]] = {}   # log path -> (bytes read, rows)
_roots: dict[str, dict[str, str]] = {}           # log path -> {record id: its chain's root}


def new_id() -> str:
    return secrets.token_hex(5)


def _log(root: str) -> str:
    return os.path.join(root, "logs", "queries.jsonl")


def rows(root: str) -> list[Json]:
    """Every line of the query log, oldest first, read incrementally: only bytes appended since the last call are parsed."""
    p = _log(root)
    try:
        size = os.path.getsize(p)
    except OSError:
        return []
    with _lock:
        done, have = _cache.get(p, (0, []))
        if size < done:            # rotated or rewritten: start again
            done, have = 0, []
            _roots.pop(p, None)
        if size > done:
            with open(p, "rb") as f:
                f.seek(done)
                chunk = f.read(size - done)
            end = chunk.rfind(b"\n") + 1   # a half-written last line waits for the next call
            fresh: list[Json] = []
            for line in chunk[:end].decode("utf-8", "replace").splitlines():
                try:
                    fresh.append(json.loads(line))
                except ValueError:
                    pass
            have = (have + fresh)[-KEEP_ROWS:]
            ids = _roots.setdefault(p, {})
            for r in fresh:
                if r.get("id"):
                    ids[str(r["id"])] = str(r.get("root") or r["id"])
            done += end
        _cache[p] = (done, have)
        return have


def root_of(root: str, parent: str | None) -> str | None:
    """The chain a parent belongs to: its own root, or the parent itself when it is not in the log (yet)."""
    if not parent:
        return None
    rows(root)
    return _roots.get(_log(root), {}).get(parent, parent)


def top_hits(result: object) -> list[Json] | None:
    if not isinstance(result, dict) or not isinstance(result.get("hits"), list):
        return None
    return [{"link": h.get("link"), "session": (h.get("session_uuid") or "")[:36], "repo": h.get("repo_key"), "role": h.get("role"),
             "ts": h.get("ts"), "score": h.get("score")} for h in result["hits"][:TOP] if isinstance(h, dict)]


def record_args(args: Json) -> Json:
    return {k: v for k, v in args.items() if k not in ("vector", "parent")}


# ---- chains ---------------------------------------------------------------------------------------------------

def _step(r: Json) -> Json:
    return {k: r.get(k) for k in ("id", "parent", "at", "door", "client", "tool", "query", "args", "hits", "ms", "mode", "error", "top")}


def chain(root: str, rid: str) -> Json:
    """The whole chain one record belongs to, oldest first, each step with its depth under the chain's first record."""
    all_ = rows(root)
    top = _roots.get(_log(root), {}).get(rid)
    if top is None:
        return {"error": f"no record {rid} in the query log"}
    steps = [_step(r) for r in all_ if r.get("id") == top or r.get("root") == top]
    depth: dict[str, int] = {}
    for s in steps:
        depth[s["id"]] = depth.get(s["parent"] or "", -1) + 1 if s["parent"] else 0
        s["depth"] = depth[s["id"]]
    return {"root": top, "id": rid, "steps": steps, "searches": sum(1 for s in steps if s["tool"] == "relic_search"),
            "opened": sum(1 for s in steps if s["tool"] in ("relic_show", "relic_session")),
            "first": steps[0]["at"] if steps else None, "last": steps[-1]["at"] if steps else None}


def chains(root: str, limit: int = 30) -> list[Json]:
    """The newest chains that have more than one step, or that hold a search: newest activity first."""
    by: dict[str, Json] = {}
    for n, r in enumerate(rows(root)):
        if not r.get("id") or str(r.get("client") or "").startswith("eval"):
            continue
        k = str(r.get("root") or r["id"])
        c = by.setdefault(k, {"root": k, "steps": 0, "searches": 0, "opened": 0, "query": None, "first": r.get("at"), "last": None,
                              "clients": []})
        c["steps"] += 1
        c["last"], c["_n"] = r.get("at"), n
        if r.get("tool") == "relic_search":
            c["searches"] += 1
            c["query"] = c["query"] or r.get("query")
        elif r.get("tool") in ("relic_show", "relic_session"):
            c["opened"] += 1
        cl = r.get("client")
        if cl and cl not in c["clients"]:
            c["clients"].append(cl)
    keep = [c for c in by.values() if c["steps"] > 1 or c["searches"]]
    keep.sort(key=lambda c: c.pop("_n"), reverse=True)
    return keep[:limit]


# ---- the access log -------------------------------------------------------------------------------------------

def access(root: str, limit: int = 100, before: int | None = None, tool: str | None = None, client: str | None = None,
           door: str | None = None, q: str | None = None, zero: bool = False, errors: bool = False, evals: bool = False) -> Json:
    """The log newest first. `before` is a row number from the previous page's next_before (rows only grow, so a
    page stays the same while new lines arrive)."""
    all_ = rows(root)
    end = len(all_) if before is None else max(0, min(before, len(all_)))
    ql = (q or "").lower()
    out: list[Json] = []
    i = end - 1
    while i >= 0 and len(out) < limit:
        r = all_[i]
        if ((evals or not str(r.get("client") or "").startswith("eval")) and (not tool or r.get("tool") == tool)
                and (not client or client.lower() in str(r.get("client") or "").lower()) and (not door or door in str(r.get("door") or ""))
                and (not ql or ql in str(r.get("query") or "").lower()) and (not zero or r.get("hits") == 0) and (not errors or r.get("error"))):
            out.append(r | {"n": i})
        i -= 1
    return {"rows": out, "total": len(all_), "next_before": i + 1 if i >= 0 else None}


def stats(root: str, hours: int = 24) -> Json:
    """For the Asked page's charts: per hour (count, p50, p95, zero hits), by client, by tool, the zero-hit share."""
    cut = time.strftime("%Y-%m-%dT%H", time.gmtime(time.time() - hours * 3600))
    per: dict[str, list[Json]] = {}
    by_client: dict[str, int] = {}
    by_tool: dict[str, int] = {}
    for r in rows(root):
        at = str(r.get("at") or "")
        if at[:13] < cut or str(r.get("client") or "").startswith("eval"):
            continue
        per.setdefault(at[:13], []).append(r)
        c = str(r.get("client") or "unknown").split(" (")[0]
        by_client[c] = by_client.get(c, 0) + 1
        by_tool[str(r.get("tool"))] = by_tool.get(str(r.get("tool")), 0) + 1

    def pct(v: list[int], p: float) -> int | None:
        return sorted(v)[max(0, int(len(v) * p + 0.5) - 1)] if v else None

    hours_out: list[Json] = []
    for h in sorted(per):
        ms = [int(r["ms"]) for r in per[h] if isinstance(r.get("ms"), (int, float))]
        s = [r for r in per[h] if r.get("tool") == "relic_search"]
        hours_out.append({"hour": h, "n": len(per[h]), "searches": len(s), "zero": sum(1 for r in s if r.get("hits") == 0),
                          "p50_ms": pct(ms, 0.5), "p95_ms": pct(ms, 0.95)})
    searches = sum(h["searches"] for h in hours_out)
    zero = sum(h["zero"] for h in hours_out)
    return {"hours": hours_out, "window_h": hours, "calls": sum(h["n"] for h in hours_out), "searches": searches, "zero": zero,
            "zero_share": round(zero / searches, 3) if searches else None,
            "by_client": sorted(({"client": k, "n": v} for k, v in by_client.items()), key=lambda x: -x["n"]),
            "by_tool": sorted(({"tool": k, "n": v} for k, v in by_tool.items()), key=lambda x: -x["n"])}


# ---- saved searches -------------------------------------------------------------------------------------------

def _saved_path(root: str) -> str:
    return os.path.join(root, "logs", "saved.json")


def saved(root: str) -> list[Json]:
    try:
        with open(_saved_path(root), encoding="utf-8") as f:
            v = json.load(f)
        return v if isinstance(v, list) else []
    except (OSError, ValueError):
        return []


def _write_saved(root: str, items: list[Json]) -> None:
    p = _saved_path(root)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = p + ".tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False, indent=1)
    os.replace(tmp, p)


SAVE_KEYS = {"query", "horizon", "since", "until", "repo", "session", "role", "tier", "with", "limit", "sort", "via", "chat",
             "from_user", "cwd", "branch", "title"}


def save(root: str, from_: str | None = None, query: str | None = None, args: Json | None = None, every: int = 60,
         name: str | None = None, door: str | None = None) -> Json:
    """Keep a search as a job: from a record id (its query and filters), or from a query and args given here."""
    from .query import UsageError
    a: Json = {}
    if from_:
        rec = next((r for r in reversed(rows(root)) if r.get("id") == from_), None)
        if rec is None:
            raise UsageError(f"no record {from_} in the query log")
        if rec.get("tool") != "relic_search":
            raise UsageError(f"record {from_} is a {rec.get('tool')}, not a search")
        a = dict(rec.get("args") or {"query": rec.get("query")})
    else:
        rec = {}
    a |= {k: v for k, v in (args or {}).items() if v not in (None, "")}
    if query:
        a["query"] = query
    a = {k: v for k, v in a.items() if k in SAVE_KEYS}
    if not str(a.get("query") or "").strip():
        raise UsageError("a saved search needs a query (or from: a search record id)")
    if not isinstance(every, int) or every < 5:
        raise UsageError("every is minutes, at least 5")
    with _lock:
        items = saved(root)
        sid = "sv" + new_id()
        item: Json = {"id": sid, "name": (name or a["query"])[:80], "args": a, "every": every, "from": from_, "door": door,
                      "created": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "runs": 0, "last_run": None,
                      "last_hits": None, "last_new": None, "last_record": None,
                      "seen": [h["link"] for h in (rec.get("top") or []) if h.get("link")] if from_ else []}
        _write_saved(root, items + [item])
    return public([item])[0]


def remove(root: str, sid: str) -> Json:
    from .query import NotFound
    with _lock:
        items = saved(root)
        left = [i for i in items if i.get("id") != sid]
        if len(left) == len(items):
            raise NotFound(f"no saved search {sid}")
        _write_saved(root, left)
    return {"removed": sid}


def public(items: Iterable[Json]) -> list[Json]:
    return [{k: v for k, v in i.items() if k != "seen"} | {"seen": len(i.get("seen") or [])} for i in items]


Runner = Callable[[str, Json, str | None, str], tuple[bool, object, str | None]]
"""(tool, args, parent, client) -> (ok, result, record id): the hub's logged() tool call."""


def run_one(root: str, sid: str, call: Runner) -> Json:
    from .query import NotFound
    item = next((i for i in saved(root) if i.get("id") == sid), None)
    if item is None:
        raise NotFound(f"no saved search {sid}")
    ok, r, rid = call("relic_search", dict(item["args"]), item.get("from") or item.get("last_record"), f"saved-search {sid}")
    hits = [h.get("link") for h in (r.get("hits") or [])] if ok and isinstance(r, dict) else []
    with _lock:
        items = saved(root)
        for i in items:
            if i.get("id") != sid:
                continue
            old = set(i.get("seen") or [])
            new = [h for h in hits if h and h not in old]
            i.update(runs=int(i.get("runs") or 0) + 1, last_run=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                     last_hits=len(hits) if ok else None, last_new=len(new) if ok and (i.get("runs") or old) else None,
                     last_record=rid, last_error=None if ok else str(r)[:200], seen=(list(i.get("seen") or []) + new)[-SEEN:])
            item = i
        _write_saved(root, items)
    from .jobs import emit
    import socket
    msg = (f"saved search '{item['name']}': {len(hits)} hits" + (f", {item['last_new']} new" if item.get("last_new") is not None else ", first run")
           if ok else f"saved search '{item['name']}' failed: {str(r)[:200]}")
    emit(root, {"job": f"saved-{sid}-{int(time.time())}", "verb": "saved-search", "state": "done" if ok else "error", "rc": 0 if ok else 1,
                "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "host": socket.gethostname(), "message": msg,
                "run": rid, "who": {"saved": sid, "record": rid}})
    return public([item])[0]


def run_due(root: str, call: Runner, now: float | None = None) -> list[str]:
    now = time.time() if now is None else now
    ran = []
    for i in saved(root):
        last = i.get("last_run")
        t = time.mktime(time.strptime(last, "%Y-%m-%dT%H:%M:%SZ")) - time.timezone if last else 0
        if now - t >= int(i.get("every") or 60) * 60:
            try:
                run_one(root, i["id"], call)
                ran.append(i["id"])
            except Exception:   # one bad saved search must not stop the others
                pass
    return ran


def keep_running(root: str, call: Runner, every: int = 60) -> threading.Thread:
    def loop() -> None:
        while True:
            time.sleep(every)
            try:
                run_due(root, call)
            except Exception:
                pass
    t = threading.Thread(target=loop, name="relic5-saved", daemon=True)
    t.start()
    return t
