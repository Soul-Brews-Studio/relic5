"""memory.py: Claude Code's memory notes as their own search layer.

Each project an agent works in keeps a memory folder of one-fact notes (~/.claude*/projects/<project>/memory/*.md,
frontmatter name / description / type = user | feedback | project | reference). They are the distilled rules and
decisions of thousands of sessions, and relic-scan does not collect them (it reads .jsonl and ψ vaults). relic5-push
sends them raw:

  <root>/parts/<machine>/memory/<claude home>/<project>/memory/<note>.md

and `relic5 index` turns every note into one row of index/_memory/notes.parquet, which fts.py indexes as the
"memory" layer (relic_search with: "memory"). MEMORY.md (the index of a folder) is skipped: it only points at notes.

The fold: a note copied to two machines with the same project, file name and text is one row; an edited copy is a
second row (both versions stay findable). role = "memory-<type>", so role filters pick rules, decisions, references.
"""
import hashlib, json, os, re
from datetime import datetime, timedelta, timezone
from typing import TypedDict

from .types_ import MemoryRow
from . import store as rfs

FRONT = re.compile(r"\A---\n(.*?)\n---\n?", re.S)
KEY = re.compile(r"^\s*([A-Za-z_][\w-]*):\s*(.*)$")
TYPES = ("user", "feedback", "project", "reference")


class Note(TypedDict):
    """One note of listing(): a MemoryRow without its body."""
    uid: str
    link: str
    ts: str
    type: str
    project: str
    title: str
    description: str
    machines: list[str]
    home: str


class Listing(TypedDict):
    notes: list[Note]
    types: dict[str, int]
    projects: dict[str, int]


def parse(text: str) -> tuple[dict[str, str], str]:
    """(frontmatter dict, body). Nested keys (metadata: type: ...) are flattened; quotes stripped."""
    m = FRONT.match(text)
    if not m:
        return {}, text.strip()
    meta: dict[str, str] = {}
    for line in m.group(1).splitlines():
        k = KEY.match(line)
        if k and k.group(2).strip():
            meta[k.group(1)] = k.group(2).strip().strip('"').strip("'")
    return meta, text[m.end():].strip()


_STAT: dict[str, tuple[int, float]] = {}   # path -> (bytes, mtime) from the last listing, for sig() without a stat each


def files(root: str) -> list[tuple[str, str, str, str]]:
    """[(machine, home, project, path)] of every pushed note: parts/<machine>/memory/<home>/<project>/memory/*.md,
    from one listing of parts/ (one round trip per folder level on S3, not one per folder)."""
    out: list[tuple[str, str, str, str]] = []
    pdir = os.path.join(root, "parts")
    if not rfs.isdir(pdir):
        return out
    base = pdir.rstrip("/") + "/"
    for path, size, mtime in rfs.files(pdir):
        rel = path[len(base):].split("/")
        if len(rel) != 6 or rel[1] != "memory" or rel[4] != "memory":
            continue
        f = rel[5]
        if f.endswith(".md") and f != "MEMORY.md" and not f.startswith("."):
            _STAT[path] = (size, mtime)
            out.append((rel[0], rel[2], rel[3], path))
    return sorted(out)


def short(project: str) -> str:
    """'-opt-Code-github-com-laris-co-neo-oracle' -> 'laris-co-neo-oracle' (org-repo; the org may hold a hyphen)."""
    return re.sub(r"^-(opt-Code|Users-[^-]+-Code)-github-com-", "", project)


def rows(root: str) -> list[MemoryRow]:
    out: dict[str, MemoryRow] = {}
    for machine, home, project, path in files(root):
        text = rfs.read_text(path)
        meta, body = parse(text)
        name = meta.get("name") or os.path.basename(path)[:-3]
        typ = meta.get("type") if meta.get("type") in TYPES else "note"
        msgkey = hashlib.md5(f"{project}/{os.path.basename(path)}\n{text}".encode()).hexdigest()
        when = meta.get("modified")
        try:
            ts = datetime.fromisoformat(when.replace("Z", "+00:00")) if when else None
        except ValueError:
            ts = None
        ts = ts or datetime.fromtimestamp(_STAT.get(path, (0, 0.0))[1] or rfs.getmtime(path), timezone.utc)
        ts = ts.astimezone(timezone.utc)
        iso = ts.strftime("%Y-%m-%dT%H:%M:%S.000Z")
        th = (ts + timedelta(hours=7)).strftime("%Y-%m-%dT%H:%M:%S.000+07:00")
        r = out.get(msgkey)
        if r:
            r["machines"] = sorted(set(r["machines"]) | {machine})
            continue
        out[msgkey] = {"machine": machine, "machines": [machine], "msgkey": msgkey, "chunk": 0, "key": msgkey,
                       "month": th[:7], "sid": f"memory:{project}", "ts": iso, "ts_th": th, "role": f"memory-{typ}",
                       "engine": home, "cat": short(project), "title": name,
                       "text": f"{name}: {meta.get('description', '')}\n\n{body}".strip(),
                       "path": os.path.relpath(path, root), "origin": meta.get("originSessionId")}
    return sorted(out.values(), key=lambda r: (r["ts"], r["msgkey"]))


def sig(root: str) -> list[list[str | int]]:
    return [[os.path.relpath(p, root), *(lambda st: [st[0], int(st[1])])(_STAT.get(p) or (rfs.getsize(p), rfs.getmtime(p)))]
            for _, _, _, p in files(root)]


def build(root: str) -> str | None:
    """Write index/_memory/notes.parquet when the pushed notes changed; returns its path (None: no notes)."""
    import pyarrow as pa, pyarrow.parquet as pq
    d = os.path.join(root, "index", "_memory")
    p, sp = os.path.join(d, "notes.parquet"), os.path.join(d, "sig.json")
    s = sig(root)
    if not s:
        return None
    if rfs.exists(p) and rfs.exists(sp) and rfs.read_json(sp) == s:
        return p
    rfs.write_parquet(pa.Table.from_pylist(rows(root)), p)
    rfs.write_json(sp, s)
    return p


def counts(root: str) -> dict[str, int]:
    """{type: notes} of the built table, for relic_status."""
    p = os.path.join(root, "index", "_memory", "notes.parquet")
    if not rfs.exists(p):
        return {}
    import pyarrow.parquet as pq
    out: dict[str, int] = {}
    for role in rfs.read_parquet(p, columns=["role"]).column("role").to_pylist():
        out[role[7:]] = out.get(role[7:], 0) + 1
    return out


def listing(root: str) -> Listing:
    """Every note without its body, newest first, for the hub's Memory tab: title, description, type, project, when,
    machines, link. The body is one relic_show away."""
    p = os.path.join(root, "index", "_memory", "notes.parquet")
    if not rfs.exists(p):
        return {"notes": [], "types": {}, "projects": {}}
    import pyarrow.parquet as pq
    notes: list[Note] = []
    types: dict[str, int] = {}
    projects: dict[str, int] = {}
    for r in rfs.read_parquet(p, columns=["msgkey", "month", "ts", "role", "cat", "title", "text", "machines", "engine"]).to_pylist():
        typ = r["role"][7:]
        head = (r["text"] or "").split("\n\n", 1)[0]
        desc = head[len(r["title"]) + 2:] if head.startswith(r["title"] + ": ") else head
        notes.append({"uid": r["msgkey"], "link": f"relic5://{r['month']}/{r['msgkey']}", "ts": r["ts"], "type": typ,
                      "project": r["cat"], "title": r["title"], "description": desc[:400], "machines": r["machines"], "home": r["engine"]})
        types[typ] = types.get(typ, 0) + 1
        projects[r["cat"]] = projects.get(r["cat"], 0) + 1
    notes.sort(key=lambda n: n["ts"] or "", reverse=True)
    return {"notes": notes, "types": types, "projects": dict(sorted(projects.items(), key=lambda kv: -kv[1]))}
