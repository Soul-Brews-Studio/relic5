"""gitlog.py: git commits as their own search layer, the record of the work from before any transcript survived.

Claude Code co-wrote commits from 2025-03-25 (laris-co/esphome-fw, "Fix template paths for ESPHome builds"), but the
oldest transcript left on any machine is from 2025-09-19: Claude Code deletes transcripts after 30 days by default.
About 900 commits of March to September 2025 are the only trace of those months (session 6f5563d6, 2026-10-22).
relic5-push sends one raw `git log --all --no-merges` per repo of `ghq list`:

  <root>/parts/<machine>/git/<host>/<org>/<repo>.log     %H %aI %cI %an %ae %s %b, fields split by 0x1f, commits by 0x1e

and `relic5 index` turns every commit into one row of index/_git/commits.parquet, which fts.py indexes as the "git"
layer (relic_search with: "git"). The fold: one row per commit hash, whichever machines and clones hold it
(`machines`, `repos`).

Whose commits: a ghq tree also holds open-source clones (m5, 2026-10-24: 625k commits in 1,087 repos, litellm alone 58k,
and other people's Claude commits from 2025-03-06 on). Our identities are the lines of the hub's git-own file
(`RELIC5_GIT_OWN`, default /config/git-own or ~/.config/relic5/git-own: an email or a glob per line, matched without
case against the author email). An org is ours when our identities wrote at least OWN_SHARE of its commits (laris-co
94%, Soul-Brews-Studio 62%, a client's 11%; open-source orgs under 1%): every commit of it is kept, the team's too.
Elsewhere only the commits we wrote are kept. No git-own file: every commit is kept, and `ours` is false everywhere.

role = commit-claude when Claude co-wrote it (a Co-Authored-By: Claude line, or "Generated with
Claude Code"), commit-codex for Codex, else commit; sid = "git:<host>/<org>/<repo>", ts = the author date.
"""
import fnmatch, hashlib, json, os, re
from datetime import datetime, timedelta, timezone
from typing import TypedDict

CLAUDE = re.compile(r"co-authored-by:\s*claude|generated with \[?claude code|noreply@anthropic\.com", re.I)
CODEX = re.compile(r"co-authored-by:\s*codex|generated with \[?codex|noreply@openai\.com", re.I)
OWN_SHARE = 0.10


class CommitRow(TypedDict):
    """One commit as gitlog.py indexes it (the columns fts.py reads, plus the commit's own)."""
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
    hash: str
    repo: str
    repos: list[str]
    author: str
    email: str
    committed: str
    ours: bool


def own_file() -> str:
    return os.environ.get("RELIC5_GIT_OWN") or next(
        (p for p in ("/config/git-own", os.path.expanduser("~/.config/relic5/git-own")) if os.path.exists(p)), "")


def own_patterns() -> list[str]:
    p = own_file()
    if not p or not os.path.exists(p):
        return []
    return [l.strip().lower() for l in open(p) if l.strip() and not l.startswith("#")]


def files(root: str) -> list[tuple[str, str, str]]:
    """[(machine, repo, path)] of every pushed log; repo = '<host>/<org>/<repo>'."""
    out: list[tuple[str, str, str]] = []
    pdir = os.path.join(root, "parts")
    for machine in sorted(os.listdir(pdir)) if os.path.isdir(pdir) else []:
        base = os.path.join(pdir, machine, "git")
        for d, _, fs in sorted(os.walk(base)):
            for f in sorted(fs):
                if f.endswith(".log") and not f.startswith("."):
                    p = os.path.join(d, f)
                    out.append((machine, os.path.relpath(p, base)[:-4], p))
    return out


def role(subject: str, body: str) -> str:
    t = subject + "\n" + body
    return "commit-claude" if CLAUDE.search(t) else "commit-codex" if CODEX.search(t) else "commit"


def _when(iso: str) -> datetime | None:
    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return None


def parse(text: str) -> list[tuple[str, str, str, str, str, str, str]]:
    """[(hash, author date, commit date, name, email, subject, body)] of one log; a broken record is skipped."""
    out = []
    for rec in text.split("\x1e"):
        f = rec.lstrip("\n").split("\x1f")
        if len(f) == 7 and re.fullmatch(r"[0-9a-f]{40}", f[0]):
            out.append((f[0], f[1], f[2], f[3], f[4], f[5], f[6].strip()))
    return out


def rows(root: str) -> list[CommitRow]:
    own = own_patterns()

    def ours(email: str) -> bool:
        return any(fnmatch.fnmatchcase(email.lower(), p) for p in own)

    def org(repo: str) -> str:
        return "/".join(repo.split("/")[:2])

    logs = [(machine, repo, parse(open(path, encoding="utf-8", errors="replace").read()), path) for machine, repo, path in files(root)]
    total: dict[str, int] = {}
    mine: dict[str, int] = {}
    for _, repo, cs, _ in logs:
        o = org(repo)
        total[o] = total.get(o, 0) + len(cs)
        mine[o] = mine.get(o, 0) + sum(1 for c in cs if ours(c[4]))
    our_orgs = {o for o in total if not own or mine[o] >= OWN_SHARE * total[o] > 0}
    out: dict[str, CommitRow] = {}
    for machine, repo, cs, path in logs:
        for h, authored, committed, name, email, subject, body in cs:
            if repo and org(repo) not in our_orgs and not ours(email):
                continue
            msgkey = hashlib.md5(f"git\n{h}".encode()).hexdigest()
            r = out.get(msgkey)
            if r:
                r["machines"] = sorted(set(r["machines"]) | {machine})
                r["repos"] = sorted(set(r["repos"]) | {repo})
                continue
            ts = _when(authored) or _when(committed)
            if ts is None:
                continue
            iso = ts.strftime("%Y-%m-%dT%H:%M:%S.000Z")
            th = (ts + timedelta(hours=7)).strftime("%Y-%m-%dT%H:%M:%S.000+07:00")
            short = repo.split("/", 1)[-1]
            out[msgkey] = {"machine": machine, "machines": [machine], "msgkey": msgkey, "chunk": 0, "key": msgkey,
                           "month": th[:7], "sid": f"git:{repo}", "ts": iso, "ts_th": th, "role": role(subject, body),
                           "engine": "git", "cat": short, "title": subject,
                           "text": "\n\n".join(x for x in (subject, body, f"{short} {h[:12]} by {name}") if x),
                           "path": os.path.relpath(path, root), "hash": h, "repo": repo, "repos": [repo],
                           "author": name, "email": email, "committed": committed, "ours": ours(email)}
    return sorted(out.values(), key=lambda r: (r["ts"], r["msgkey"]))


def table(root: str) -> str:
    return os.path.join(root, "index", "_git", "commits.parquet")


def sig(root: str) -> list[list[str | int]]:
    """The pushed logs, plus the git-own patterns: a new identity rebuilds the table."""
    logs: list[list[str | int]] = [[os.path.relpath(p, root), os.path.getsize(p), int(os.path.getmtime(p))] for _, _, p in files(root)]
    return logs + [["git-own", *own_patterns()]] if logs else []


def build(root: str) -> str | None:
    """Write index/_git/commits.parquet when the pushed logs changed; returns its path (None: no logs)."""
    import pyarrow as pa, pyarrow.parquet as pq
    p = table(root)
    sp = os.path.join(os.path.dirname(p), "sig.json")
    s = sig(root)
    if not s:
        return None
    if os.path.exists(p) and os.path.exists(sp) and json.load(open(sp)) == s:
        return p
    os.makedirs(os.path.dirname(p), exist_ok=True)
    pq.write_table(pa.Table.from_pylist(rows(root)), p + ".tmp")
    os.replace(p + ".tmp", p)
    with open(sp + ".tmp", "w") as f:
        json.dump(s, f)
    os.replace(sp + ".tmp", sp)
    return p


class Counts(TypedDict):
    commits: int
    ours: int
    claude: int
    codex: int
    repos: int
    first_claude: str | None
    months: dict[str, dict[str, int]]


def counts(root: str) -> Counts | None:
    """For relic_status: commits, how many Claude or Codex co-wrote, the first Claude commit, and per Bangkok month."""
    p = table(root)
    if not os.path.exists(p):
        return None
    import pyarrow.parquet as pq
    t = pq.read_table(p, columns=["role", "month", "ts_th", "repo", "ours"]).to_pylist()
    months: dict[str, dict[str, int]] = {}
    for r in t:
        m = months.setdefault(r["month"], {"commits": 0, "claude": 0, "codex": 0})
        m["commits"] += 1
        if r["role"] != "commit":
            m[r["role"][7:]] += 1
    claude = sorted(r["ts_th"] for r in t if r["role"] == "commit-claude")
    return {"commits": len(t), "ours": sum(1 for r in t if r["ours"]), "claude": sum(m["claude"] for m in months.values()),
            "codex": sum(m["codex"] for m in months.values()), "repos": len({r["repo"] for r in t}),
            "first_claude": claude[0] if claude else None, "months": dict(sorted(months.items()))}
