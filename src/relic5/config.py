"""config.py: the fleet's config files as their own search layer, "config" (issue #269).

A memory note (memory.py) is where a rule is remembered; a CLAUDE.md is where it is enforced: it loads into every
session that starts under it, a memory note does not. Until this layer, relic5 held only the first. Two verbatim
lines of real CLAUDE.md files ("ghq-tree Fleet Rules", "Never publish to claude.ai") returned no hit from any layer
on 2026-10-29. relic5-push now sends, per account:

  ~/.claude*/CLAUDE.md                          -> parts/<machine>/config/<user>/home/<home>/CLAUDE.md
  ~/.claude*/skills/**/SKILL.md                 -> parts/<machine>/config/<user>/home/<home>/skills/...
  ~/.claude*/plugins/cache/**/SKILL.md          -> parts/<machine>/config/<user>/home/<home>/plugins/cache/...
  <ghq root>/{,<host>/,<host>/<org>/}CLAUDE.md  -> parts/<machine>/config/<user>/ghq/...   (the tree's own rules,
  every CLAUDE.md / AGENTS.md git knows in a repo -> parts/<machine>/config/<user>/ghq/<host>/<org>/<repo>/...  in no repo)
  the list of files sent this time              -> parts/<machine>/config/<user>/_files.json

and `relic5 index` turns every "## " section of every file into one row of index/_config/sections.parquet, which
fts.py indexes as the "config" layer (relic_search with: "config"). role = config-claudemd | config-agentsmd |
config-skill.

Only rules, never secrets. Three gates, each enough on its own:
  1. names: only CLAUDE.md, AGENTS.md and SKILL.md are read. settings.json, .envrc, .env*, *.pem, *.key, *.conf
     never are, wherever they sit.
  2. content: a file carrying anything key-shaped (key_shaped: a private key block, a WireGuard PrivateKey, a
     provider token, a secret assigned a value, a long high-entropy run) is refused whole. Its path and the rule that
     tripped are recorded (refused()), never the text. A pattern list of file names alone is not trusted: a
     CLAUDE.md can hold a pasted key as easily as a .conf can (mycelium-oracle ψ/active/*.conf, 2026-10).
  3. relic5-push runs the same check before anything leaves the machine, so a refused file never reaches the hub.

The fold. A file's scope is where it applies: a repo file is the repo and its path in it (the same CLAUDE.md cloned
on m5 and white is one scope); a home file is the account, the home and its path (beta's ~/.claude/CLAUDE.md and
nat's are two scopes: each loads only for its own account); a plugin skill drops its version folder. One row per
(scope, text, section): identical text on two machines or accounts is one row whose machines/accounts list both; an
edited copy is a second row, so both versions stay findable. Nothing is dropped: a section whose text no longer
exists anywhere (edited, or its file removed) stays with current = false and the time it was last seen, so the
table is the history of every rule's wording from the first push on. A file is current while some account's latest
_files.json lists it.

Sections. A CLAUDE.md is a list of rules, one per "## " heading, most of them dated "(Nat, 2026-10-22)". Each section
is its own row (the title is the heading, ts the heading's date when it has one, else the file's mtime), so a hit
lands on the rule, not on a 10 kB file, and "since when" is the rule's own date. Headings inside ``` fences do not
split.
"""
import hashlib, json, math, os, re
from datetime import datetime, timedelta, timezone
from typing import Iterator, TypedDict

from . import store as rfs
from .types_ import Json
from .memory import parse

NAMES = {"CLAUDE.md": "claudemd", "AGENTS.md": "agentsmd", "SKILL.md": "skill"}
"""The only file names read. Everything else under parts/<machine>/config/ is ignored (gate 1)."""

# Gate 2: key-shaped content. Each rule is (name, pattern); a match refuses the whole file. key_shaped returns the first
# rule a text trips with its line ('wireguard-key line 7'), never the matched text. Beyond the named shapes: a run of
# 24+ token characters (split at _ = -, so ENV_VAR_NAMES and placeholders are words, not runs) holding upper case,
# lower case and digits with an entropy of 4.2 bits a character or more: a random base62/base64 secret. Words, hex
# hashes, uuids and a URL's own path segments (after a /) stay under it. A value assigned to api_key/token/secret/...
# counts only when it holds a letter and a digit and is not a dotted code reference (process.env.X).
# The block between the markers is copied verbatim into bin/relic5-push (tests/test_config.py compares them).
# KEY_SHAPED begin
_VAL = r"[\"']?(?=[\w~+/=-]*\d)(?=[\w~+/=-]*[A-Za-z])[\w~+/=-]{16,}(?![\w.~+/=-])"
KEY_SHAPED = [
    ("private-key-block", re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----")),
    ("wireguard-key", re.compile(r"(?im)^\s*(?:PrivateKey|PresharedKey)\s*=\s*[A-Za-z0-9+/]{42,43}=")),
    ("github-token", re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,})")),
    ("api-key", re.compile(r"\bsk-(?:ant-|proj-)?[A-Za-z0-9_-]{24,}")),
    ("slack-token", re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}")),
    ("aws-key", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("google-key", re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b")),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}")),
    ("bearer", re.compile(r"(?i)\bbearer\s+" + _VAL)),
    ("secret-assigned", re.compile(r"(?i)\b(?:api[_-]?key|secret|token|password|passwd|client[_-]?secret|access[_-]?key)"
                                   r"\b[\"']?\s*[:=]\s*" + _VAL)),
]
_RUN = re.compile(r"[A-Za-z0-9+/]{24,}")


def _entropy(s: str) -> float:
    n = len(s)
    return -sum(c / n * math.log2(c / n) for c in (s.count(ch) for ch in set(s)))


def key_shaped(text: str) -> "str | None":
    for name, rx in KEY_SHAPED:
        m = rx.search(text)
        if m:
            return f"{name} line {text.count(chr(10), 0, m.start()) + 1}"
    for m in _RUN.finditer(text):
        s = m.group(0).strip("/")
        if (m.start() and text[m.start() - 1] == "/") or "/" in s and "://" in text[max(0, m.start() - 200):m.start()]:
            continue   # a URL's path segment, not a value
        if len(s) >= 24 and any(c.isupper() for c in s) and any(c.islower() for c in s) and any(c.isdigit() for c in s) \
                and _entropy(s) >= 4.2:
            return f"high-entropy line {text.count(chr(10), 0, m.start()) + 1}"
    return None
# KEY_SHAPED end


class Section(TypedDict):
    title: str
    body: str
    date: str | None


_HEAD = re.compile(r"^(#{1,2})\s+(.*\S)\s*$")
_DATE = re.compile(r"\b(20\d\d-\d\d-\d\d)\b")


def sections(text: str) -> list[Section]:
    """A file's "## " sections, the part before the first one as section 0 (its title the "# " heading, if any).
    Headings inside ``` / ~~~ fences do not split. date = the first YYYY-MM-DD in the heading."""
    meta, body = parse(text)
    out: list[Section] = []
    title, fence = meta.get("name") or "", ""
    buf: list[str] = []
    for line in body.splitlines():
        s = line.strip()
        if s.startswith(("```", "~~~")):
            fence = "" if fence and s.startswith(fence) else (fence or s[:3])
        h = None if fence else _HEAD.match(line)
        if h and h.group(1) == "#" and not out and not "".join(buf).strip():
            title = title or h.group(2)
            continue
        if h and h.group(1) == "##":
            out.append({"title": title, "body": "\n".join(buf).strip(), "date": None})
            title, buf = h.group(2), []
            continue
        buf.append(line)
    out.append({"title": title, "body": "\n".join(buf).strip(), "date": None})
    if meta.get("description") and out:
        out[0]["body"] = (meta["description"] + "\n\n" + out[0]["body"]).strip()
    for sec in out:
        d = _DATE.search(sec["title"])
        sec["date"] = d.group(1) if d else None
    return [s for s in out if s["body"] or s["title"]]


class Pushed(TypedDict):
    machine: str
    user: str
    rel: str      # the path under parts/<machine>/config/<user>/: home/claude/CLAUDE.md, ghq/github.com/x/y/AGENTS.md
    path: str


_STAT: dict[str, tuple[int, float]] = {}


def files(root: str) -> Iterator[Pushed]:
    """Every pushed file this layer reads (gate 1: the names in NAMES), from one listing of parts/."""
    pdir = os.path.join(root, "parts")
    if not rfs.isdir(pdir):
        return
    base = pdir.rstrip("/") + "/"
    for path, size, mtime in sorted(rfs.files(pdir)):
        rel = path[len(base):].split("/")
        if len(rel) < 5 or rel[1] != "config" or rel[-1] not in NAMES or rel[3] not in ("home", "ghq"):
            continue
        _STAT[path] = (size, mtime)
        yield {"machine": rel[0], "user": rel[2], "rel": "/".join(rel[3:]), "path": path}


def listed(root: str) -> dict[tuple[str, str], set[str] | None]:
    """{(machine, user): the files its latest push listed} from parts/<machine>/config/<user>/_files.json; None when
    that account sent no list (then every file it holds counts as current)."""
    out: dict[tuple[str, str], set[str] | None] = {}
    pdir = os.path.join(root, "parts")
    if not rfs.isdir(pdir):
        return out
    for m in rfs.listdir(pdir):
        cdir = os.path.join(pdir, m, "config")
        if not rfs.isdir(cdir):
            continue
        for u in rfs.listdir(cdir):
            p = os.path.join(cdir, u, "_files.json")
            try:
                out[(m, u)] = set(rfs.read_json(p)["files"]) if rfs.exists(p) else None
            except (ValueError, KeyError, TypeError):
                out[(m, u)] = None
    return out


def push_refused(root: str) -> "list[Refused]":
    """What relic5-push refused on each machine (the "refused" list of its _files.json): those files never reach the
    hub, so this is the only place they show."""
    out: list[Refused] = []
    pdir = os.path.join(root, "parts")
    if not rfs.isdir(pdir):
        return out
    for m in sorted(rfs.listdir(pdir)):
        cdir = os.path.join(pdir, m, "config")
        if not rfs.isdir(cdir):
            continue
        for u in sorted(rfs.listdir(cdir)):
            p = os.path.join(cdir, u, "_files.json")
            try:
                got = rfs.read_json(p).get("refused") or [] if rfs.exists(p) else []
            except (ValueError, AttributeError):
                got = []
            out += [{"machine": m, "user": u, "rel": str(r.get("rel")), "why": f"{r.get('why')} (at push)"} for r in got if isinstance(r, dict)]
    return out


_VERSION = re.compile(r"^(home/[^/]+/plugins/cache/[^/]+/[^/]+)/[^/]*\d[^/]*/")


def scope(f: Pushed) -> tuple[str, str, str]:
    """(scope key, role kind, cat) of a pushed file. See the fold in the module doc."""
    rel, kind = f["rel"], NAMES[os.path.basename(f["rel"])]
    if rel.startswith("ghq/"):
        p = rel[4:].split("/")
        cat = "/".join(p[1:3]) if len(p) > 3 else "/".join(p[:-1]) or "ghq root"
        return rel, kind, cat
    key = f['user'] + ":" + _VERSION.sub(r"\1/", rel)
    p = rel.split("/")
    if kind == "skill":
        cat = ("plugin:" + p[5] if p[2] == "plugins" and len(p) > 5 else "skill") + ":" + p[-2]
    else:
        cat = f"~{f['user']}/.{p[1]}"
    return key, kind, cat


class Refused(TypedDict):
    machine: str
    user: str
    rel: str
    why: str


def _iso(ts: datetime) -> tuple[str, str]:
    ts = ts.astimezone(timezone.utc)
    return ts.strftime("%Y-%m-%dT%H:%M:%S.000Z"), (ts + timedelta(hours=7)).strftime("%Y-%m-%dT%H:%M:%S.000+07:00")


def rows(root: str, now: datetime | None = None) -> tuple[list[Json], list[Refused]]:
    """(one row per section of every current file, folded; the files refused by gate 2)."""
    seen = (now or datetime.now(timezone.utc)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    lists = listed(root)
    out: dict[str, Json] = {}
    refused: list[Refused] = []
    for f in files(root):
        want = lists.get((f["machine"], f["user"]))
        if want is not None and f["rel"] not in want:
            continue   # its account's latest push no longer has it: stays only as history
        text = rfs.read_text(f["path"])
        why = key_shaped(text)
        if why:
            refused.append({"machine": f["machine"], "user": f["user"], "rel": f["rel"], "why": why})
            continue
        key, kind, cat = scope(f)
        fkey = hashlib.md5(f"{key}\n{text}".encode()).hexdigest()
        mtime = datetime.fromtimestamp(_STAT.get(f["path"], (0, 0.0))[1] or rfs.getmtime(f["path"]), timezone.utc)
        account = f"{f['user']}@{f['machine']}"
        secs = sections(text)
        file_title = secs[0]["title"] if secs and secs[0]["title"] else os.path.basename(os.path.dirname(f["rel"])) if kind == "skill" else cat
        for i, sec in enumerate(secs):
            # a section is its own identity (scope, heading, body): editing one rule leaves the others' rows and first_seen
            mk = hashlib.md5(f"{key}\n{sec['title']}\n{sec['body']}\n{i if not sec['title'] else ''}".encode()).hexdigest()
            r = out.get(mk)
            if r:
                r["machines"] = sorted(set(r["machines"]) | {f["machine"]})
                r["accounts"] = sorted(set(r["accounts"]) | {account})
                r["paths"] = sorted(set(r["paths"]) | {f"{account}:{f['rel']}"})
                continue
            ts = datetime.fromisoformat(sec["date"] + "T00:00:00+07:00") if sec["date"] else mtime
            iso, th = _iso(ts)
            head = sec["title"] if i else file_title
            out[mk] = {"machine": f["machine"], "machines": [f["machine"]], "msgkey": mk, "chunk": 0, "key": fkey,
                       "month": th[:7], "sid": f"config:{key}", "ts": iso, "ts_th": th, "role": f"config-{kind}",
                       "engine": f["user"], "cat": cat, "title": head or os.path.basename(f["rel"]),
                       "text": (f"{file_title} › {sec['title']}\n\n" if i and file_title else f"{head}\n\n" if head else "") + sec["body"],
                       "path": os.path.relpath(f["path"], root), "scope": key, "file": os.path.basename(f["rel"]),
                       "section": i, "dated": sec["date"], "mtime": _iso(mtime)[0], "accounts": [account],
                       "paths": [f"{account}:{f['rel']}"], "current": True, "first_seen": seen, "last_seen": seen}
    return sorted(out.values(), key=lambda r: (r["scope"], r["section"], r["ts"])), refused


TABLE = ("_config", "sections.parquet")


def sig(root: str) -> list[list[str | int]]:
    s: list[list[str | int]] = []
    for f in files(root):
        size, mtime = _STAT.get(f["path"]) or (0, 0.0)
        s.append([os.path.relpath(f["path"], root), size, int(mtime)])
    lists = os.path.join(root, "parts")
    if rfs.isdir(lists):
        for (m, u), names in sorted(listed(root).items()):
            s.append([f"{m}/{u}/_files.json", len(names) if names is not None else -1, 0])
        if s:
            s.append(["push refused", len(push_refused(root)), 0])
    return s


def build(root: str, now: datetime | None = None) -> str | None:
    """Write index/_config/sections.parquet when the pushed config changed; returns its path (None: nothing pushed).
    Rows of the previous table that are gone now are kept as history (current = false), with their first_seen."""
    import pyarrow as pa
    d = os.path.join(root, "index", TABLE[0])
    p, sp, rp = os.path.join(d, TABLE[1]), os.path.join(d, "sig.json"), os.path.join(d, "refused.json")
    s = sig(root)
    if not s:
        return None
    if rfs.exists(p) and rfs.exists(sp) and rfs.read_json(sp) == s:
        return p
    new, refused = rows(root, now)
    if not new and not rfs.exists(p):   # nothing indexable yet (every file refused): no empty table for DuckDB to
        rfs.makedirs(d)                  # trip on, but the refusals are still recorded for status
        rfs.write_json(rp, refused + push_refused(root), indent=1)
        rfs.write_json(sp, s)
        return None
    if rfs.exists(p):
        old = {r["msgkey"]: r for r in rfs.read_parquet(p).to_pylist()}
        for r in new:
            o = old.pop(r["msgkey"], None)
            if o:
                r["first_seen"] = o["first_seen"]
        for o in old.values():
            if o["current"]:
                o["current"] = False   # last_seen stays: the last build that still found it
            new.append(o)
    rfs.write_parquet(pa.Table.from_pylist(sorted(new, key=lambda r: (r["scope"], r["section"], r["ts"]))), p)
    rfs.write_json(rp, refused + push_refused(root), indent=1)
    rfs.write_json(sp, s)
    return p


def refused(root: str) -> list[Refused]:
    """The files the last build refused (gate 2): machine, user, path, the rule and line. Never their text."""
    p = os.path.join(root, "index", TABLE[0], "refused.json")
    return rfs.read_json(p) if rfs.exists(p) else []


def counts(root: str) -> dict[str, int]:
    """{kind: current sections, 'refused': files} for relic_status."""
    p = os.path.join(root, "index", *TABLE)
    if not rfs.exists(p):
        return {}
    out: dict[str, int] = {}
    t = rfs.read_parquet(p, columns=["role", "current"]).to_pylist()
    for r in t:
        if r["current"]:
            out[r["role"][7:]] = out.get(r["role"][7:], 0) + 1
    if refused(root):
        out["refused"] = len(refused(root))
    return out
