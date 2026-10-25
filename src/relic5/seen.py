"""seen.py: when each token and connector was last used, and from where (Nat, 2026-10-25, on Settings > Access tokens:
"last login?"). The auth middleware calls touch() for every request through a token:<name> or oauth:<client> door;
the approve page calls it for the hub token pasted there.

  ~/.config/relic5/seen.json (0600, beside tokens.json): {door: {"at": iso, "ip": str, "via": "tunnel"|"direct", "path": str}}

Kept in memory and written at most once a minute per door, so a busy client costs no disk write per request. A restart
loses at most that minute.
"""
import json, os, threading, time

from .types_ import Json

PATH = os.path.expanduser(os.environ.get("RELIC5_SEEN_JSON") or os.path.join(
    os.path.dirname(os.path.expanduser(os.environ.get("RELIC5_TOKENS_JSON", "~/.config/relic5/tokens.json"))), "seen.json"))
EVERY = 60.0
_LOCK = threading.Lock()
_MEM: dict[str, Json] = {}
_WROTE: dict[str, float] = {}
_LOADED = False


def _load() -> None:
    global _LOADED
    if _LOADED:
        return
    try:
        _MEM.update(json.load(open(PATH)))
    except (OSError, ValueError):
        pass
    _LOADED = True


def _save() -> None:
    os.makedirs(os.path.dirname(PATH), mode=0o700, exist_ok=True)
    tmp = PATH + ".tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    os.write(fd, json.dumps(_MEM, indent=1).encode())
    os.close(fd)
    os.replace(tmp, PATH)


def touch(door: str, ip: str, via: str, path: str) -> None:
    if not door.startswith(("token:", "oauth:")):
        return
    with _LOCK:
        _load()
        _MEM[door] = {"at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "ip": ip, "via": via, "path": path}
        if time.monotonic() - _WROTE.get(door, -EVERY) >= EVERY:
            _WROTE[door] = time.monotonic()
            try:
                _save()
            except OSError:
                pass   # a read-only config dir: still shown until a restart


def seed(root: str, days: int = 30) -> None:
    """Fill doors never touched since seen.json began from the hub's own logs: the request log (logs/requests/<day>.jsonl)
    and the MCP call log (logs/queries.jsonl). Those keep no address, so a seeded entry has the time and path only."""
    from . import store as rfs
    logs = os.path.join(root, "logs")
    since = time.strftime("%Y-%m-%d", time.gmtime(time.time() - days * 86400))
    files = [os.path.join(logs, "requests", f) for f in sorted(rfs.listdir(os.path.join(logs, "requests")))
             if f.endswith(".jsonl") and f[:10] >= since] if rfs.exists(os.path.join(logs, "requests")) else []
    best: dict[str, Json] = {}
    for f in files + [os.path.join(logs, "queries.jsonl")]:
        try:
            text = rfs.read_text(f)
        except (OSError, FileNotFoundError):
            continue
        for line in text.splitlines():
            if '"token:' not in line and '"oauth:' not in line:
                continue
            try:
                r = json.loads(line)
            except ValueError:
                continue
            d, at = str(r.get("door") or ""), str(r.get("at") or "")[:19] + "Z"
            if d.startswith(("token:", "oauth:")) and at > best.get(d, {}).get("at", ""):
                best[d] = {"at": at, "ip": None, "via": None, "path": r.get("path") or ("/mcp " + r["tool"] if r.get("tool") else None)}
    with _LOCK:
        _load()
        for d, v in best.items():
            if v["at"] > _MEM.get(d, {}).get("at", ""):
                _MEM[d] = v


def of(door: str) -> Json:
    """-> {"last_used", "last_ip", "last_via", "last_path"} for a door, empty when never seen."""
    with _LOCK:
        _load()
        s = _MEM.get(door)
    return {"last_used": s["at"], "last_ip": s.get("ip"), "last_via": s.get("via"), "last_path": s.get("path")} if s else {}
