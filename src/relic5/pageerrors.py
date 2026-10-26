"""pageerrors.py: the hub page's own errors, kept on the hub (Nat, 2026-10-26: "when click sometimes this ...
ERR_CONNECTION_REFUSED ... Failed to fetch dynamically imported module ... we should register like sentry?").

A Sentry of our own, and nothing leaves the hub: the page catches its errors (window error, an unhandled rejection, a
failed API call, a chunk that would not load), queues them in localStorage while the hub cannot be reached, and posts
them here when it can. They go to logs/client-errors.jsonl (0600, one line each, fields cut short) and the Incidents
page lists them grouped by message.
"""
import json, os, threading, time

from . import store as rfs
from .types_ import Json

LOCK = threading.Lock()
FIELDS = {"kind": 40, "message": 500, "stack": 2000, "url": 300, "view": 80, "ua": 200, "at": 40, "build": 40}
MAX_BYTES = 20_000_000     # past this the file stops growing: a page in a loop never fills the disk


def path(root: str) -> str:
    return os.path.join(root, "logs", "client-errors.jsonl")


def record(root: str, items: list[Json], door: str | None) -> int:
    """Append up to 50 reports from one page; returns how many were kept."""
    p = path(root)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    lines = []
    for it in items[:50]:
        if not isinstance(it, dict):
            continue
        row: Json = {k: str(it.get(k) or "")[:n] for k, n in FIELDS.items()}
        row["count"] = max(1, min(int(it.get("count") or 1), 10_000)) if str(it.get("count") or "1").isdigit() else 1
        row["received"], row["door"] = now, door
        lines.append(json.dumps(row, ensure_ascii=False))
    if not lines:
        return 0
    with LOCK:
        if os.path.exists(p) and os.path.getsize(p) > MAX_BYTES:
            return 0
        fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        with os.fdopen(fd, "a", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
    return len(lines)


def recent(root: str, hours: float = 24) -> Json:
    """Reports received in the last `hours`, grouped by kind + message: count, first and last time, views, a stack."""
    p = path(root)
    if not os.path.exists(p):
        return {"groups": [], "total": 0}
    since = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - hours * 3600))
    groups: dict[tuple[str, str], Json] = {}
    total = 0
    for line in rfs.tail_lines(p, 8_000_000):
        try:
            r = json.loads(line)
        except ValueError:
            continue
        if str(r.get("received") or "") < since:
            continue
        total += int(r.get("count") or 1)
        k = (r.get("kind") or "", r.get("message") or "")
        g = groups.setdefault(k, {"kind": k[0], "message": k[1], "count": 0, "first": r.get("at") or r.get("received"),
                                  "last": "", "views": [], "stack": r.get("stack") or "", "url": r.get("url") or ""})
        g["count"] += int(r.get("count") or 1)
        g["last"] = max(g["last"], str(r.get("at") or r.get("received")))
        if r.get("view") and r["view"] not in g["views"]:
            g["views"].append(r["view"])
    out = sorted(groups.values(), key=lambda g: g["last"], reverse=True)
    return {"groups": out, "total": total, "hours": hours}
