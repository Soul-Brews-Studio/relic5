"""discord.py: Discord server backups as their own search layer, "discord" (with: "discord"), never mixed with talk.

The backups are neo's maw atlas runs on m5 (~/.maw/atlas-blobs/<Guild>-<id>/server.sqlite, neo-oracle#205; 18 servers,
240,480 messages on 2026-10-26). bin/relic5-discord-export writes the servers neo's manifest marks verified, text and
file names only, and relic5-push sends them:

  <root>/parts/<machine>/discord/<guild_id>.jsonl.gz     one JSON line per message (relic5-discord-export's docstring)

and `relic5 index` folds them into index/_discord/messages.parquet, which fts.py indexes. One row per message:
sid = "discord:<guild>:<thread or channel>", title "#channel" or "#channel › thread", cat = the server's name,
role = discord, or discord-bot for a bot, text = "author: message [files: a.png]".

Other people's words (Nat, 2026-10-26: "no guild at all" on the public MCP): this layer is read by the local CLI, the
web UI on the tailnet and m5's MCP only. A request that came in through the public host or an OAuth connector
(api.py sets PUBLIC) gets a usage error for with: "discord", and show() refuses a discord message.
"""
import contextvars, gzip, hashlib, io, json, os
from datetime import datetime, timedelta, timezone
from typing import TypedDict
from . import store as rfs

PUBLIC: "contextvars.ContextVar[bool]" = contextvars.ContextVar("relic5_public", default=False)
"""True while a request from outside (the public host, an OAuth connector) is served: api.py sets it."""


def guard() -> None:
    """A usage error when the request came through the public door."""
    from .query import UsageError
    if PUBLIC.get():
        raise UsageError("discord is not served through the public MCP (Nat, 2026-10-26); use the local CLI or the tailnet")


class MessageRow(TypedDict):
    machine: str
    machines: list[str]
    msgkey: str
    chunk: int
    key: str
    month: str
    sid: str
    ts: str
    ts_th: str
    role: str
    engine: str
    cat: str
    title: str
    text: str
    path: str
    guild: str
    guild_name: str
    channel: str
    thread: str | None
    author: str
    message_id: str


def files(root: str) -> list[tuple[str, str]]:
    """[(machine, path)] of every pushed server file."""
    out: list[tuple[str, str]] = []
    pdir = os.path.join(root, "parts")
    for machine in sorted(rfs.listdir(pdir)) if rfs.isdir(pdir) else []:
        base = os.path.join(pdir, machine, "discord")
        if rfs.isdir(base):
            out += [(machine, os.path.join(base, f)) for f in sorted(rfs.listdir(base)) if f.endswith(".jsonl.gz") and not f.startswith(".")]
    return out


def _when(iso: str) -> datetime | None:
    try:
        return datetime.fromisoformat((iso or "").replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return None


def rows(root: str) -> list[MessageRow]:
    out: dict[str, MessageRow] = {}
    for machine, path in files(root):
        with gzip.open(io.BytesIO(rfs.read_bytes(path)), "rt", encoding="utf-8") as f:
            for line in f:
                try:
                    m = json.loads(line)
                except ValueError:
                    continue
                msgkey = hashlib.md5(f"discord\n{m.get('id')}".encode()).hexdigest()
                if msgkey in out:
                    out[msgkey]["machines"] = sorted(set(out[msgkey]["machines"]) | {machine})
                    continue
                ts = _when(m.get("ts") or "")
                if ts is None or not m.get("id"):
                    continue
                th = (ts + timedelta(hours=7)).strftime("%Y-%m-%dT%H:%M:%S.000+07:00")
                where = f"#{m.get('channel_name') or '?'}" + (f" › {m.get('thread_name') or '?'}" if m.get("thread") else "")
                body = (m.get("text") or "") + (f" [files: {', '.join(m['files'])}]" if m.get("files") else "")
                out[msgkey] = {"machine": machine, "machines": [machine], "msgkey": msgkey, "chunk": 0, "key": msgkey,
                               "month": th[:7], "sid": f"discord:{m['guild']}:{m.get('thread') or m.get('channel')}",
                               "ts": ts.strftime("%Y-%m-%dT%H:%M:%S.000Z"), "ts_th": th,
                               "role": "discord-bot" if m.get("bot") else "discord", "engine": "discord",
                               "cat": m.get("guild_name") or m["guild"], "title": where,
                               "text": f"{m.get('author') or '?'}: {body.strip()}", "path": os.path.relpath(path, root),
                               "guild": m["guild"], "guild_name": m.get("guild_name") or m["guild"], "channel": m.get("channel") or "",
                               "thread": m.get("thread"), "author": m.get("author") or "?", "message_id": str(m["id"])}
    return sorted(out.values(), key=lambda r: (r["ts"], r["msgkey"]))


def table(root: str) -> str:
    return os.path.join(root, "index", "_discord", "messages.parquet")


def sig(root: str) -> list[list[str | int]]:
    return [[os.path.relpath(p, root), rfs.getsize(p), int(rfs.getmtime(p))] for _, p in files(root)]


def build(root: str) -> str | None:
    """Write index/_discord/messages.parquet when the pushed files changed; returns its path (None: nothing pushed)."""
    import pyarrow as pa
    p = table(root)
    sp = os.path.join(os.path.dirname(p), "sig.json")
    s = sig(root)
    if not s:
        return None
    if rfs.exists(p) and rfs.exists(sp) and rfs.read_json(sp) == s:
        return p
    rfs.write_parquet(pa.Table.from_pylist(rows(root)), p)
    rfs.write_json(sp, s)
    return p


class Counts(TypedDict):
    messages: int
    servers: dict[str, int]
    first: str | None
    last: str | None


def counts(root: str) -> Counts | None:
    """For relic_status (local doors only): messages per server and the time span."""
    p = table(root)
    if not rfs.exists(p):
        return None
    t = rfs.read_parquet(p, columns=["guild_name", "ts_th"]).to_pylist()
    servers: dict[str, int] = {}
    for r in t:
        servers[r["guild_name"]] = servers.get(r["guild_name"], 0) + 1
    ts = sorted(r["ts_th"] for r in t)
    return {"messages": len(t), "servers": dict(sorted(servers.items(), key=lambda kv: -kv[1])),
            "first": ts[0] if ts else None, "last": ts[-1] if ts else None}
