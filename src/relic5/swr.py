"""swr.py: stale-while-revalidate for the hub's heavy GET answers (2026-10-25: /api/sessions p50 1.3 s, p95 7.2 s,
/api/status 1.2 s, /api/memory 4.5 s, measured in perf.py; every page reads sessions and status).

get(key, ttl, fn): a fresh answer comes from memory; a stale one comes from memory at once while one thread
recomputes it; a missing one is computed, once, however many requests ask at the same time. RELIC5_SWR=0 turns it
off (every call computes).
"""
import os, threading, time
from collections.abc import Callable
from typing import Any

_VAL: dict[str, tuple[float, Any]] = {}
_BUSY: dict[str, threading.Event] = {}
_LOCK = threading.Lock()
MAX = 512
STATS = {"hit": 0, "stale": 0, "miss": 0}


def _compute(key: str, fn: Callable[[], Any], ev: threading.Event) -> Any:
    try:
        v = fn()
        with _LOCK:
            _VAL[key] = (time.time(), v)
            if len(_VAL) > MAX:   # the oldest out
                for k in sorted(_VAL, key=lambda k: _VAL[k][0])[: len(_VAL) - MAX]:
                    del _VAL[k]
        return v
    finally:
        with _LOCK:
            _BUSY.pop(key, None)
        ev.set()


def get(key: str, ttl: float, fn: Callable[[], Any]) -> Any:
    if os.environ.get("RELIC5_SWR", "1") == "0":
        return fn()
    with _LOCK:
        have = _VAL.get(key)
        busy = _BUSY.get(key)
        now = time.time()
        if have and now - have[0] < ttl:
            STATS["hit"] += 1
            return have[1]
        if have:
            STATS["stale"] += 1
            if not busy:
                ev = _BUSY[key] = threading.Event()
                threading.Thread(target=_compute, args=(key, fn, ev), name="relic5-swr", daemon=True).start()
            return have[1]
        STATS["miss"] += 1
        if busy:
            wait = busy
        else:
            ev = _BUSY[key] = threading.Event()
            wait = None
    if wait is not None:
        wait.wait(120)
        with _LOCK:
            have = _VAL.get(key)
        return have[1] if have else fn()
    return _compute(key, fn, ev)


def clear() -> None:
    with _LOCK:
        _VAL.clear()
