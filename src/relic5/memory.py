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

FRONT = re.compile(r"\A---\n(.*?)\n---\n?", re.S)
KEY = re.compile(r"^\s*([A-Za-z_][\w-]*):\s*(.*)$")
TYPES = ("user", "feedback", "project", "reference")


def parse(text):
    """(frontmatter dict, body). Nested keys (metadata: type: ...) are flattened; quotes stripped."""
    m = FRONT.match(text)
    if not m:
        return {}, text.strip()
    meta = {}
    for line in m.group(1).splitlines():
        k = KEY.match(line)
        if k and k.group(2).strip():
            meta[k.group(1)] = k.group(2).strip().strip('"').strip("'")
    return meta, text[m.end():].strip()


def files(root):
    """[(machine, home, project, path)] of every pushed note."""
    out, pdir = [], os.path.join(root, "parts")
    if not os.path.isdir(pdir):
        return out
    for machine in sorted(os.listdir(pdir)):
        base = os.path.join(pdir, machine, "memory")
        if not os.path.isdir(base):
            continue
        for home in sorted(os.listdir(base)):
            hd = os.path.join(base, home)
            for project in sorted(os.listdir(hd)) if os.path.isdir(hd) else []:
                md = os.path.join(hd, project, "memory")
                for f in sorted(os.listdir(md)) if os.path.isdir(md) else []:
                    if f.endswith(".md") and f != "MEMORY.md" and not f.startswith("."):
                        out.append((machine, home, project, os.path.join(md, f)))
    return out


def short(project):
    """'-opt-Code-github-com-laris-co-neo-oracle' -> 'laris-co-neo-oracle' (org-repo; the org may hold a hyphen)."""
    return re.sub(r"^-(opt-Code|Users-[^-]+-Code)-github-com-", "", project)


def rows(root):
    out = {}
    for machine, home, project, path in files(root):
        text = open(path, encoding="utf-8", errors="replace").read()
        meta, body = parse(text)
        name = meta.get("name") or os.path.basename(path)[:-3]
        typ = meta.get("type") if meta.get("type") in TYPES else "note"
        msgkey = hashlib.md5(f"{project}/{os.path.basename(path)}\n{text}".encode()).hexdigest()
        when = meta.get("modified")
        try:
            ts = datetime.fromisoformat(when.replace("Z", "+00:00")) if when else None
        except ValueError:
            ts = None
        ts = ts or datetime.fromtimestamp(os.path.getmtime(path), timezone.utc)
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


def sig(root):
    return [[os.path.relpath(p, root), os.path.getsize(p), int(os.path.getmtime(p))] for _, _, _, p in files(root)]


def build(root):
    """Write index/_memory/notes.parquet when the pushed notes changed; returns its path (None: no notes)."""
    import pyarrow as pa, pyarrow.parquet as pq
    d = os.path.join(root, "index", "_memory")
    p, sp = os.path.join(d, "notes.parquet"), os.path.join(d, "sig.json")
    s = sig(root)
    if not s:
        return None
    if os.path.exists(p) and os.path.exists(sp) and json.load(open(sp)) == s:
        return p
    os.makedirs(d, exist_ok=True)
    pq.write_table(pa.Table.from_pylist(rows(root)), p + ".tmp")
    os.replace(p + ".tmp", p)
    with open(sp + ".tmp", "w") as f:
        json.dump(s, f)
    os.replace(sp + ".tmp", sp)
    return p


def counts(root):
    """{type: notes} of the built table, for relic_status."""
    p = os.path.join(root, "index", "_memory", "notes.parquet")
    if not os.path.exists(p):
        return {}
    import pyarrow.parquet as pq
    out = {}
    for role in pq.read_table(p, columns=["role"]).column("role").to_pylist():
        out[role[7:]] = out.get(role[7:], 0) + 1
    return out
