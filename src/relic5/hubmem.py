"""hubmem.py: the hub's DuckDB memory cap, set from the CLI or MCP (issue #306).

Nat, 2026-11-23: "can we make 6g ram config can config from cli or mcp?" The hub caps DuckDB at 6 GB (white's hub was
OOM-killed at 24 GB beside an index, 2026-10-25), and `relic5 skills --ai` hit that cap once (#305). Until now the only
knob was RELIC5_DUCK_MEM in the environment of `relic5 serve`.

At start, the first of:  `relic5 serve --duck-mem 8GB`  ·  RELIC5_DUCK_MEM  ·  ~/.config/relic5/hub.json
{"duck_mem": "8GB"} (RELIC5_HUB_CONFIG)  ·  6GB.

While it runs: `relic5 duck-mem` reads it, `relic5 duck-mem 8GB` sets it on the live connection (DuckDB's SET
memory_limit, no restart) and saves it in hub.json so the next start keeps it; MCP relic_hub_memory does the same.
Reading is open to every door; a change only from a tokenless door (the hub's own loopback or Nat's tailnet), as token
admin: a client token never resizes the hub.
"""
import json
import os
import re
from typing import Any

from .types_ import Json

DEFAULT = "6GB"
CONFIG = os.path.expanduser(os.environ.get("RELIC5_HUB_CONFIG", "~/.config/relic5/hub.json"))
SIZE = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*(MB|GB|TB|MiB|GiB|TiB)\s*$", re.IGNORECASE)
UNIT = {"mb": 2**20, "mib": 2**20, "gb": 2**30, "gib": 2**30, "tb": 2**40, "tib": 2**40}
LOW, HIGH = 512 * 2**20, 512 * 2**30   # below 512 MB the hub cannot answer a search; above 512 GB is a typo


def parse(v: str) -> str:
    """'8GB', '8 gb', '7.5GiB' -> DuckDB's form ('8GB'); anything else, or outside 512 MB .. 512 GB, is a ValueError.
    The value goes into a SET statement, so only this shape ever reaches SQL."""
    m = SIZE.match(v or "")
    if not m:
        raise ValueError(f"memory size like 6GB, 8GB or 12GiB, not {v!r}")
    n, unit = float(m.group(1)), m.group(2)
    size = n * UNIT[unit.lower()]
    if not LOW <= size <= HIGH:
        raise ValueError(f"{v} is outside 512MB .. 512GB")
    num = m.group(1).rstrip("0").rstrip(".") if "." in m.group(1) else m.group(1)
    return f"{num}{unit.upper().replace('IB', 'iB')}"


def _read() -> Json:
    try:
        with open(CONFIG) as f:
            c = json.load(f)
    except (OSError, ValueError):
        return {}
    return c if isinstance(c, dict) else {}


def saved() -> str | None:
    try:
        v = _read().get("duck_mem")
    except (OSError, ValueError, AttributeError):
        return None
    return v if isinstance(v, str) else None


def save(v: str) -> None:
    c = _read()
    c["duck_mem"] = v
    os.makedirs(os.path.dirname(CONFIG), exist_ok=True)
    tmp = CONFIG + ".tmp"
    with open(tmp, "w") as f:
        json.dump(c, f, indent=1)
    os.chmod(tmp, 0o600)
    os.replace(tmp, CONFIG)


def at_start(flag: str | None = None) -> tuple[str, str]:
    """(value, where it came from) for `relic5 serve`: the flag, the environment, hub.json, then the default."""
    for v, src in ((flag, "--duck-mem"), (os.environ.get("RELIC5_DUCK_MEM"), "RELIC5_DUCK_MEM"), (saved(), CONFIG)):
        if v:
            return parse(v), src
    return DEFAULT, "default"


def current(con: Any) -> str:
    row = con.cursor().execute("SELECT current_setting('memory_limit')").fetchone()
    return str(row[0]) if row else "?"


def tokenless(door: str | None) -> bool:
    """The hub's own loopback or Nat's tailnet: the doors that need no token (doors.py), and the only ones that may
    change the hub itself. A token or an OAuth grant may read, never resize."""
    return bool(door) and str(door).startswith(("loopback", "tailnet:"))


def status(con: Any) -> Json:
    return {"memory_limit": current(con), "saved": saved(), "default": DEFAULT, "config": CONFIG,
            "env": os.environ.get("RELIC5_DUCK_MEM")}


def change(con: Any, value: str, door: str | None, persist: bool = True) -> Json:
    """SET memory_limit on the live connection (no restart), and save it for the next start unless persist=False."""
    if not tokenless(door):
        raise PermissionError("the hub's memory is changed from the hub itself or Nat's tailnet, not with a token")
    v = parse(value)
    before = current(con)
    con.cursor().execute(f"SET memory_limit = '{v}'")   # v matched SIZE: digits, a dot, a unit, nothing else
    if persist:
        save(v)
    return status(con) | {"before": before, "set": v, "persisted": persist}
