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

LOCK = threading.Lock()
RUNNING = {}          # id -> {at, door, tool, query}
_sizes = (0, None)    # cache: (time, value)


def _log(root):
    return os.path.join(root, "logs", "queries.jsonl")


def start(tool, door, query, client=None):
    qid = f"{time.time():.6f}-{threading.get_ident()}"
    with LOCK:
        RUNNING[qid] = {"at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "door": door, "tool": tool, "query": (query or "")[:200],
                        **({"client": client} if client else {})}
    return qid, time.time()


def finish(root, qid, t0, result=None, args=None, error=None):
    with LOCK:
        q = RUNNING.pop(qid, {})
    args = args or {}
    r = result if isinstance(result, dict) else {}
    line = q | {"ms": round((time.time() - t0) * 1000), "hits": len(r.get("hits", [])) if "hits" in r else None,
                "mode": ("hybrid" if r.get("hybrid") else "semantic") if r.get("semantic") else ("keyword" if "hits" in r else None),
                "horizon": r.get("horizon"), "vector": "vector" in args, "error": (error or "")[:200] or None}
    p = _log(root)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    try:
        os.write(fd, (json.dumps(line, ensure_ascii=False) + "\n").encode())
    finally:
        os.close(fd)


def _tail(path, n=5000):
    if not os.path.exists(path):
        return []
    with open(path, "rb") as f:
        f.seek(max(0, os.path.getsize(path) - 2_000_000))
        out = []
        for line in f.read().decode("utf-8", "replace").splitlines()[-n:]:
            try:
                out.append(json.loads(line))
            except ValueError:
                pass
    return out


def queries(root):
    rows = _tail(_log(root))
    now = time.time()
    hours = {}
    for r in rows:
        try:
            t = time.mktime(time.strptime(r["at"], "%Y-%m-%dT%H:%M:%SZ")) - time.timezone
        except (KeyError, ValueError):
            continue
        if now - t < 86400:
            hours.setdefault(r["at"][:13], []).append(r["ms"])
    per_hour = {h: {"n": len(v), "p50_ms": round(statistics.median(v)), "p95_ms": round(sorted(v)[max(0, int(len(v) * 0.95) - 1)])}
                for h, v in sorted(hours.items())}
    real = [r for r in rows if r.get("client") != "eval"]   # eval runs say so (X-Relic5-Client: eval); keep them out of Nat's view
    counts = {}
    for r in real:
        if r.get("query"):
            counts[r["query"]] = counts.get(r["query"], 0) + 1
    zero = [r for r in real if r.get("hits") == 0 and r.get("query")]
    with LOCK:
        running = [v | {"for_s": round(now - time.mktime(time.strptime(v["at"], "%Y-%m-%dT%H:%M:%SZ")) + time.timezone)} for v in RUNNING.values()]
    return {"running": running, "total_logged": len(rows), "eval_logged": len(rows) - len(real), "last": real[-20:][::-1], "per_hour": per_hour,
            "top": sorted(({"query": q, "n": n} for q, n in counts.items() if n > 1), key=lambda x: -x["n"])[:15],
            "zero_hits": [{"at": r["at"], "query": r["query"], "tool": r.get("tool")} for r in zero[-20:][::-1]]}


def _du(path):
    total = 0
    for d, _, fs in os.walk(path):
        for f in fs:
            try:
                total += os.lstat(os.path.join(d, f)).st_size
            except OSError:
                pass
    return total


def store(root, ttl=120):
    """Sizes, cached for ttl seconds (walking 6 GB of LanceDB files on every status call would be wasteful)."""
    global _sizes
    if _sizes[1] is not None and time.time() - _sizes[0] < ttl:
        return _sizes[1]
    out = {"parts": {}, "search": {}, "vectors": {}, "manifests": 0, "logs": 0}
    pd = os.path.join(root, "parts")
    for m in sorted(os.listdir(pd)) if os.path.isdir(pd) else []:
        out["parts"][m] = {s: _du(os.path.join(pd, m, s)) for s in sorted(os.listdir(os.path.join(pd, m))) if os.path.isdir(os.path.join(pd, m, s))}
    from .fts import current, search_dir
    sd = search_dir(root)
    for name, rel in current(root).items():
        out["search"][name] = _du(os.path.join(sd, rel))
    vd = os.path.join(root, "vectors")
    for m in sorted(os.listdir(vd)) if os.path.isdir(vd) else []:
        out["vectors"][m] = _du(os.path.join(vd, m))
    out["manifests"] = sum(_du(os.path.join(root, "index", d)) for d in os.listdir(os.path.join(root, "index")) if d[:4].isdigit() or d == "undated") \
        if os.path.isdir(os.path.join(root, "index")) else 0
    out["logs"] = _du(os.path.join(root, "logs"))
    out["search_total"] = _du(sd) if os.path.isdir(sd) else 0
    du = shutil.disk_usage(root)
    out["disk"] = {"total": du.total, "used": du.used, "free": du.free, "free_pct": round(du.free / du.total * 100, 1)}
    out["total"] = sum(sum(v.values()) for v in out["parts"].values()) + out["search_total"] + sum(out["vectors"].values()) + out["logs"]
    out["growth"] = growth(root, out["total"])
    _sizes = (time.time(), out)
    return out


def record_size(root):
    """At most one line an hour in logs/sizes.jsonl (called by `relic5 index`), for growth per day."""
    p = os.path.join(root, "logs", "sizes.jsonl")
    day = time.strftime("%Y-%m-%dT%H")
    rows = _tail(p, 2000)
    if rows and rows[-1].get("day") == day:
        return
    os.makedirs(os.path.dirname(p), exist_ok=True)
    s = store(root, ttl=0)
    with open(p, "a") as f:
        f.write(json.dumps({"day": day, "total": s["total"], "parts": sum(sum(v.values()) for v in s["parts"].values()),
                            "disk_free": s["disk"]["free"]}) + "\n")


def growth(root, total_now):
    """Bytes per day from the first and the newest size line; an estimate until a full day is covered (None before 6 h)."""
    rows = _tail(os.path.join(root, "logs", "sizes.jsonl"), 2000)
    if len(rows) < 2:
        return {"per_day": None, "since": rows[0]["day"] if rows else None}
    t = lambda d: time.mktime(time.strptime(d[:13], "%Y-%m-%dT%H" if "T" in d else "%Y-%m-%d"))
    a, b = rows[0], rows[-1]
    hours = (t(b["day"]) - t(a["day"])) / 3600
    if hours < 6:
        return {"per_day": None, "since": a["day"], "note": f"{hours:.0f} h of history; a rate needs 6 h"}
    return {"per_day": round((b["total"] - a["total"]) / hours * 24), "since": a["day"], "estimate": hours < 24}


def _read(p):
    try:
        return open(p).read()
    except OSError:
        return ""


def resources():
    out = {"load": list(os.getloadavg()), "cpus": os.cpu_count()}
    mem = {l.split(":")[0]: int(l.split()[1]) * 1024 for l in _read("/proc/meminfo").splitlines() if l.split(":")[0] in ("MemTotal", "MemAvailable")}
    if mem:
        out["memory"] = {"total": mem.get("MemTotal"), "available": mem.get("MemAvailable")}
    st = {l.split(":")[0]: l.split(":")[1].strip() for l in _read("/proc/self/status").splitlines() if ":" in l}
    out["process"] = {"rss": int(st["VmRSS"].split()[0]) * 1024 if "VmRSS" in st else None, "threads": int(st.get("Threads", 0)) or None,
                      "open_files": len(os.listdir("/proc/self/fd")) if os.path.isdir("/proc/self/fd") else None}
    cg = _read("/sys/fs/cgroup/memory.current").strip()
    if cg:
        out["container"] = {"memory": int(cg), "limit": _read("/sys/fs/cgroup/memory.max").strip()}
    return out


def warnings(st, res):
    w = []
    if st["disk"]["free_pct"] < 20:
        w.append(f"disk: only {st['disk']['free_pct']}% free on the hub")
    if res["load"][2] > (res["cpus"] or 1) * 0.8:
        w.append(f"load: {res['load'][2]:.1f} over 15 min on {res['cpus']} cpus")
    return w
