"""selfknow.py: what the hub knows about itself (Nat, 2026-10-23: "relic5 should know database size, current and past
query, and resource"). Read by relic_status and the UI. Query text stays on the hub (logs/queries.jsonl, 0600), inside
the tailnet: never in git, never in an eval file.

  queries   logs/queries.jsonl, one line per call: at, door, tool, query (<= 200 chars), mode, horizon, hits, ms, vector
            status: running now, the last 20, p50/p95 per hour (24 h), the most repeated, the zero-hit ones
  store     bytes (and rows where known) per layer: parts per machine and stream, BM25 tables, vector tables, manifests,
            logs; disk used/free; growth per day from logs/sizes.jsonl (one line a day, written by `relic5 index`)
  resources load average, memory, this process (RSS, open files, threads), the container's cgroup memory, running jobs
"""
import json, os, shutil, statistics, threading, time
from collections.abc import Callable
from typing import TypedDict

from .types_ import Json
from . import store as rfs

LOCK = threading.Lock()
RUNNING: dict[str, Json] = {}          # id -> {at, door, tool, query}
_sizes: tuple[float, Json | None] = (0, None)    # cache: (time, value)


class TopQuery(TypedDict):
    query: str
    n: int


def _log(root: str) -> str:
    return os.path.join(root, "logs", "queries.jsonl")


def start(tool: str, door: str | None, query: str | None, client: str | None = None) -> tuple[str, float]:
    qid = f"{time.time():.6f}-{threading.get_ident()}"
    with LOCK:
        RUNNING[qid] = {"at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "door": door, "tool": tool, "query": (query or "")[:200],
                        **({"client": client} if client else {})}
    return qid, time.time()


def finish(root: str, qid: str, t0: float, result: object = None, args: Json | None = None, error: str | None = None,
           rid: str | None = None, parent: str | None = None) -> str | None:
    """Append the call's line; with rid, also its trace fields (trace.py): id, parent, root, args, top hits. -> the root."""
    from . import trace
    with LOCK:
        q = RUNNING.pop(qid, {})
    args = args or {}
    r: Json = result if isinstance(result, dict) else {}
    line = q | {"ms": round((time.time() - t0) * 1000), "hits": len(r.get("hits", [])) if "hits" in r else None,
                "mode": ("hybrid" if r.get("hybrid") else "semantic") if r.get("semantic") else ("keyword" if "hits" in r else None),
                "horizon": r.get("horizon"), "vector": "vector" in args, "error": (error or "")[:200] or None}
    top = None
    if rid:
        top = trace.root_of(root, parent) or rid
        line |= {"id": rid, "parent": parent, "root": top, "args": trace.record_args(args)}
        if (t := trace.top_hits(result)) is not None:
            line["top"] = t
    rfs.append_line(_log(root), json.dumps(line, ensure_ascii=False))
    return top


def _tail(path: str, n: int = 5000) -> list[Json]:
    out: list[Json] = []
    for line in rfs.tail_lines(path, 2_000_000)[-n:]:
        try:
            out.append(json.loads(line))
        except ValueError:
            pass
    return out


def queries(root: str) -> Json:
    rows = _tail(_log(root))
    now = time.time()
    hours: dict[str, list[int]] = {}
    for r in rows:
        try:
            t = time.mktime(time.strptime(r["at"], "%Y-%m-%dT%H:%M:%SZ")) - time.timezone
        except (KeyError, ValueError):
            continue
        if now - t < 86400:
            hours.setdefault(r["at"][:13], []).append(r["ms"])
    per_hour = {h: {"n": len(v), "p50_ms": round(statistics.median(v)), "p95_ms": round(sorted(v)[max(0, int(len(v) * 0.95) - 1)])}
                for h, v in sorted(hours.items())}
    real = [r for r in rows if not str(r.get("client") or "").startswith("eval")]   # eval runs say so (X-Relic5-Client: eval); keep them out of Nat's view
    counts: dict[str, int] = {}
    for r in real:   # what people asked: searches only (a show's "query" is a message id or relic5:// link)
        q = str(r.get("query") or "")
        if r.get("tool") == "relic_search" and q and not q.startswith("relic5://"):
            counts[q] = counts.get(q, 0) + 1
    zero = [r for r in real if r.get("hits") == 0 and r.get("query")]
    with LOCK:
        running = [v | {"for_s": round(now - time.mktime(time.strptime(v["at"], "%Y-%m-%dT%H:%M:%SZ")) + time.timezone)} for v in RUNNING.values()]
    # the newest distinct searches: "last" is every call (shows, sessions, status), so on a busy hub it held no search at all
    searches: list[Json] = []
    seen: set[str] = set()
    for r in reversed(real):
        q = str(r.get("query") or "").strip()
        if r.get("tool") == "relic_search" and q and q not in seen:
            seen.add(q)
            searches.append({"at": r["at"], "query": q, "hits": r.get("hits"), "client": r.get("client")})
            if len(searches) == 20:
                break
    return {"running": running, "total_logged": len(rows), "eval_logged": len(rows) - len(real), "last": real[-20:][::-1], "per_hour": per_hour,
            "searches": searches,
            "top": sorted((TopQuery(query=q, n=n) for q, n in counts.items() if n > 1), key=lambda x: -x["n"])[:40],
            "zero_hits": [{"at": r["at"], "query": r["query"], "tool": r.get("tool")} for r in zero[-20:][::-1]]}


def _du(path: str) -> int:
    """Bytes under path, each inode once: relic3's generations are hardlinked copies (rsync --link-dest), and counting
    every link reported ~/.relic3-gens as 254.7 GB where it uses ~80 GB (2026-10-24). On S3: the objects' sizes."""
    if rfs.is_s3(path):
        return sum(n for _, n, _ in rfs.files(path))
    total, seen = 0, set[tuple[int, int]]()
    for d, _, fs in os.walk(path):
        for f in fs:
            try:
                st = os.lstat(os.path.join(d, f))
            except OSError:
                continue
            if st.st_nlink > 1:
                if (st.st_dev, st.st_ino) in seen:
                    continue
                seen.add((st.st_dev, st.st_ino))
            total += st.st_size
    return total


_measuring = threading.Event()


def store(root: str, ttl: int = 120) -> Json:
    """Sizes, cached for ttl seconds (walking 6 GB of LanceDB files on every status call would be wasteful). On S3 a
    walk is ~100 listings (7 s of an 8 s status, 2026-10-25): the last measurement is served and a new one is made
    in the background every 10 minutes."""
    global _sizes
    if rfs.is_s3(root) and ttl:
        if _sizes[1] is not None:
            if time.time() - _sizes[0] > 600 and not _measuring.is_set():
                _measuring.set()
                def bg() -> None:
                    try:
                        _measure(root)
                    finally:
                        _measuring.clear()
                threading.Thread(target=bg, name="relic5-sizes", daemon=True).start()
            return _sizes[1]
        return _measure(root)
    if _sizes[1] is not None and time.time() - _sizes[0] < ttl:
        return _sizes[1]
    return _measure(root)


def _measure(root: str) -> Json:
    global _sizes
    out: Json = {"parts": {}, "search": {}, "vectors": {}, "manifests": 0, "logs": 0}
    pd = os.path.join(root, "parts")
    for m in sorted(rfs.listdir(pd)) if rfs.isdir(pd) else []:
        out["parts"][m] = {s: _du(os.path.join(pd, m, s)) for s in sorted(rfs.listdir(os.path.join(pd, m))) if rfs.isdir(os.path.join(pd, m, s))}
    from .fts import current, search_dir
    sd = search_dir(root)
    for name, rel in current(root).items():
        out["search"][name] = _du(os.path.join(sd, rel))
    vd = os.path.join(root, "vectors")
    for m in sorted(rfs.listdir(vd)) if rfs.isdir(vd) else []:
        out["vectors"][m] = _du(os.path.join(vd, m))
    out["manifests"] = sum(_du(os.path.join(root, "index", d)) for d in rfs.listdir(os.path.join(root, "index")) if d[:4].isdigit() or d == "undated") \
        if rfs.isdir(os.path.join(root, "index")) else 0
    out["logs"] = _du(os.path.join(root, "logs"))
    out["search_total"] = _du(sd) if rfs.isdir(sd) else 0
    if rfs.is_s3(root):   # a bucket has no disk of its own to fill; the local cache's disk is what can run out
        du = shutil.disk_usage(rfs.cache_dir(root))
        out["backend"] = {"kind": "s3", "root": root, "endpoint": rfs.s3_config()["endpoint"]}
    else:
        du = shutil.disk_usage(root)
        out["backend"] = {"kind": "disk", "root": root}
    out["disk"] = {"total": du.total, "used": du.used, "free": du.free, "free_pct": round(du.free / du.total * 100, 1)}
    out["total"] = sum(sum(v.values()) for v in out["parts"].values()) + out["search_total"] + sum(out["vectors"].values()) + out["logs"]
    out["growth"] = growth(root, out["total"])
    _sizes = (time.time(), out)
    return out


def record_size(root: str) -> None:
    """At most one line an hour in logs/sizes.jsonl (called by `relic5 index`), for growth per day."""
    p = os.path.join(root, "logs", "sizes.jsonl")
    day = time.strftime("%Y-%m-%dT%H")
    rows = _tail(p, 2000)
    if rows and rows[-1].get("day") == day:
        return
    s = store(root, ttl=0)
    rfs.append_line(p, json.dumps({"day": day, "total": s["total"], "parts": sum(sum(v.values()) for v in s["parts"].values()),
                                   "disk_free": s["disk"]["free"]}), 0o644)


def growth(root: str, total_now: int) -> Json:
    """Bytes per day from the first and the newest size line; an estimate until a full day is covered (None before 6 h)."""
    rows = _tail(os.path.join(root, "logs", "sizes.jsonl"), 2000)
    if len(rows) < 2:
        return {"per_day": None, "since": rows[0]["day"] if rows else None}
    t: Callable[[str], float] = lambda d: time.mktime(time.strptime(d[:13], "%Y-%m-%dT%H" if "T" in d else "%Y-%m-%d"))
    a, b = rows[0], rows[-1]
    hours = (t(b["day"]) - t(a["day"])) / 3600
    if hours < 6:
        return {"per_day": None, "since": a["day"], "note": f"{hours:.0f} h of history; a rate needs 6 h"}
    return {"per_day": round((b["total"] - a["total"]) / hours * 24), "since": a["day"], "estimate": hours < 24}


def _read(p: str) -> str:
    try:
        return open(p).read()
    except OSError:
        return ""


def resources() -> Json:
    out: Json = {"load": list(os.getloadavg()), "cpus": os.cpu_count()}
    mem = {l.split(":")[0]: int(l.split()[1]) * 1024 for l in _read("/proc/meminfo").splitlines() if l.split(":")[0] in ("MemTotal", "MemAvailable")}
    if mem:
        out["memory"] = {"total": mem.get("MemTotal"), "available": mem.get("MemAvailable")}
    st = {l.split(":")[0]: l.split(":")[1].strip() for l in _read("/proc/self/status").splitlines() if ":" in l}
    out["process"] = {"rss": int(st["VmRSS"].split()[0]) * 1024 if "VmRSS" in st else None, "threads": int(st.get("Threads", 0)) or None,
                      "open_files": len(rfs.listdir("/proc/self/fd")) if rfs.isdir("/proc/self/fd") else None}
    cg = _read("/sys/fs/cgroup/memory.current").strip()
    if cg:
        out["container"] = {"memory": int(cg), "limit": _read("/sys/fs/cgroup/memory.max").strip()}
    return out


def warnings(st: Json, res: Json) -> list[str]:
    w = []
    if st["disk"]["free_pct"] < 20:
        w.append(f"disk: only {st['disk']['free_pct']}% free on the hub (relic5 itself: {st.get('total', 0) / 1e9:.1f} GB; "
                 "`relic5 gc` lists what else is big)")
    if res["load"][2] > (res["cpus"] or 1) * 0.8:
        w.append(f"load: {res['load'][2]:.1f} over 15 min on {res['cpus']} cpus")
    return w


def clients(root: str, days: int = 7) -> Json:
    """Connected devices: every door + client seen in the query log in the last `days` days, newest first: last seen,
    calls in 24 h and in all, the tools it used, and its median time. A door is the machine (tailnet:<node>, loopback,
    token:<name>); a client is the program (relic-feeder (http), claude-code (mcp), python-urllib (mcp): the Mac shim)."""
    now = time.time()
    seen: dict[tuple[str, str], Json] = {}
    for r in _tail(_log(root), 20000):
        try:
            t = time.mktime(time.strptime(r["at"], "%Y-%m-%dT%H:%M:%SZ")) - time.timezone
        except (KeyError, ValueError):
            continue
        if now - t > days * 86400:
            continue
        k = (r.get("door") or "unknown", r.get("client") or "unknown")
        d = seen.setdefault(k, {"door": k[0], "client": k[1], "first": r["at"], "last": r["at"], "calls": 0, "calls_24h": 0,
                                "tools": {}, "ms": []})
        d["calls"] += 1
        d["calls_24h"] += now - t < 86400
        d["last"] = max(d["last"], r["at"])
        d["first"] = min(d["first"], r["at"])
        d["tools"][r.get("tool", "?")] = d["tools"].get(r.get("tool", "?"), 0) + 1
        if isinstance(r.get("ms"), int):
            d["ms"].append(r["ms"])
    out = []
    for d in seen.values():
        ms = d.pop("ms")
        d["p50_ms"] = round(statistics.median(ms)) if ms else None
        out.append(d)
    out.sort(key=lambda d: d["last"], reverse=True)
    return {"days": days, "devices": out}
