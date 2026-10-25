"""perf.py: every HTTP request the hub answers, timed (Nat, 2026-10-25: "can we have performance log and page to
display each like request?"), and the process's memory and the machine's load every 10 s.

  RING            the last 5,000 requests in memory: what the Performance page reads
  logs/requests/<day>.jsonl   the same lines, written in one append every 30 s (one object on S3, not one per request)
  SAMPLES         rss, load and the request rate every 10 s, the last 6 h

A line: {at, method, path, route, status, ms, bytes, door, q}. route is FastAPI's path template (/api/artifact/{id}),
so a page groups by it; q is the query string, cut at 200 characters, with any token removed.
"""
import contextvars, json, os, re, resource, sys, threading, time
from collections import deque


from . import store as rfs
from .types_ import Json

RING: deque[Json] = deque(maxlen=5000)
QRING: deque[Json] = deque(maxlen=20000)   # every query the hub ran: {at, name, kind, ms, rows, route, sql}
ROUTE: "contextvars.ContextVar[str | None]" = contextvars.ContextVar("relic5_route", default=None)
SAMPLES: deque[Json] = deque(maxlen=6 * 360)
_PENDING: list[str] = []
_LOCK = threading.Lock()
_SECRET = re.compile(r"(?i)\b(t|token|key|secret)=[^&]*")


def rss_mb() -> float:
    """Resident memory now (Linux /proc), else the peak (macOS getrusage)."""
    try:
        with open("/proc/self/statm") as f:
            return round(int(f.read().split()[1]) * os.sysconf("SC_PAGE_SIZE") / 2**20, 1)
    except OSError:
        r = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        return round(r / 2**20 if r > 2**32 else r / 1024, 1)


def record(method: str, path: str, route: str | None, status: int, ms: float, size: int | None, door: str | None, q: str) -> None:
    at = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()) + f".{int(time.time() * 1000) % 1000:03d}Z"
    line = {"at": at, "method": method, "path": path, "route": route or path, "status": status, "ms": round(ms, 1),
            "bytes": size, "door": door, "q": _SECRET.sub(r"\1=…", q)[:200]}
    with _LOCK:
        RING.append(line)
        _PENDING.append(json.dumps(line, ensure_ascii=False))


def query(kind: str, ms: float, rows: int | None, sql: str = "", name: str | None = None, depth: int = 2) -> None:
    """One query: its name is the function that ran it (Relic5.tail, Index._fts), unless given."""
    if name is None:
        f = sys._getframe(depth)
        name = f.f_code.co_qualname.split(".<locals>")[0]   # a helper inside a method is filed under the method
    QRING.append({"at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "name": name, "kind": kind, "ms": round(ms, 1),
                  "rows": rows, "route": ROUTE.get(), "sql": re.sub(r"\s+", " ", sql)[:300]})


def queries(minutes: int = 60) -> list[Json]:
    """Per query name: count, p50, p95, max, rows, the routes that ran it, the slowest SQL seen."""
    cut = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - minutes * 60))
    by: dict[str, list[Json]] = {}
    for q in list(QRING):
        if q["at"] >= cut:
            by.setdefault(q["name"], []).append(q)
    out = []
    for k, v in by.items():
        ms = [x["ms"] for x in v]
        worst = max(v, key=lambda x: x["ms"])
        out.append({"name": k, "kind": v[0]["kind"], "count": len(v), "p50": _pct(ms, .5), "p95": _pct(ms, .95), "max": max(ms),
                    "total": round(sum(ms)), "rows": round(sum(x["rows"] or 0 for x in v) / len(v)),
                    "routes": sorted({x["route"] for x in v if x["route"]}), "sql": worst["sql"]})
    return sorted(out, key=lambda x: -x["total"])


def flush(root: str) -> int:
    with _LOCK:
        lines, _PENDING[:] = list(_PENDING), []
    if not lines:
        return 0
    rfs.append_line(os.path.join(root, "logs", "requests", time.strftime("%Y-%m-%d", time.gmtime()) + ".jsonl"), "\n".join(lines))
    return len(lines)


def keep(root: str) -> threading.Thread:
    """Sample every 10 s, write the log every 30 s."""
    def loop() -> None:
        n = 0
        while True:
            time.sleep(10)
            n += 1
            now = time.time()
            recent = sum(1 for r in list(RING)[-600:] if r["at"] >= time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(now - 60)))
            SAMPLES.append({"at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now)), "rss_mb": rss_mb(),
                            "load": round(os.getloadavg()[0], 2), "per_min": recent})
            if n % 3 == 0:
                try:
                    flush(root)
                except Exception as ex:   # a failed write keeps nothing back: the ring still has them
                    print(f"relic5: could not write the request log: {ex}", flush=True)
    t = threading.Thread(target=loop, name="relic5-perf", daemon=True)
    t.start()
    return t


def _pct(xs: list[float], p: float) -> float | None:
    if not xs:
        return None
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(p * len(xs)))]


def summary(minutes: int = 60, route: str | None = None, slow_ms: float = 1000) -> Json:
    """Per route: count, p50, p95, max, errors; the slowest requests; the newest ones; the samples."""
    cut = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(time.time() - minutes * 60))
    rows = [r for r in list(RING) if r["at"] >= cut]
    by: dict[str, list[Json]] = {}
    for r in rows:
        by.setdefault(r["route"], []).append(r)
    routes = sorted(({"route": k, "count": len(v), "p50": _pct([x["ms"] for x in v], .5), "p95": _pct([x["ms"] for x in v], .95),
                      "max": max(x["ms"] for x in v), "errors": sum(1 for x in v if x["status"] >= 500),
                      "slow": sum(1 for x in v if x["ms"] >= slow_ms), "bytes": sum(x["bytes"] or 0 for x in v)}
                     for k, v in by.items()), key=lambda x: -(x["p95"] or 0) * x["count"])
    pick = [r for r in rows if not route or r["route"] == route]
    return {"minutes": minutes, "requests": len(rows), "routes": routes,
            "slowest": sorted(pick, key=lambda r: -r["ms"])[:50], "recent": pick[-200:][::-1],
            "samples": [s for s in list(SAMPLES) if s["at"] >= cut + "Z"], "rss_mb": rss_mb(), "queries": queries(minutes),
            "load": [round(x, 2) for x in os.getloadavg()], "cpus": os.cpu_count()}


