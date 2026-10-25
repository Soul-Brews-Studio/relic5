"""query.py: search, show, sessions, session over the folded parts (parts.py). Read-only.

The result shapes follow agent-relic-v3's tools (src/mcp/tools.ts, src/search/query.ts @9f0bdb5) so a relic3 client
reads relic5 the same way. What differs, by design:
  uid        the msgkey (md5 of the message, the same on every machine), ":<chunk>" for a later chunk of a long one
  partition  the Bangkok month YYYY-MM (relic3: an ISO week)
  link       relic5://<YYYY-MM>/<uid>
  machines   every machine that pushed the row (the first by name gave it)
  score      keyword hits: how many times the query's words occur (no BM25 until the embed milestone)
Search is keyword: every word of the query must occur (ILIKE, so a Thai substring matches).
"""
import base64, hashlib, json, os, re
from collections.abc import Callable, Collection, Sequence
from typing import TYPE_CHECKING, TypedDict

from .parts import STREAMS, Parts
from .types_ import Json
from .window import window
from . import store as rfs

if TYPE_CHECKING:   # for annotations only: the connection comes from the caller
    import duckdb

DEFAULT_LIMIT = 20
HEX32 = re.compile(r"^[0-9a-f]{32}$")
COLS = "machine, key, msgkey, chunk, month, sid, ts, ts_th, engine, role, type, kind, name, cat, text"


class SearchKw(TypedDict):
    """The filters and paging Relic5.search hands on to search.search and search_ilike alike."""
    since: str | None
    until: str | None
    horizon: str | None
    repo: str | None
    session: str | None
    role: str | None
    tier: str | None
    with_: str | None
    limit: int
    cursor: str | None


class UsageError(ValueError):
    pass


class NotFound(LookupError):
    pass


def like(word: str) -> str:
    return "%" + re.sub(r"([%_\\])", r"\\\1", word) + "%"


def repo_pattern(repo: str) -> str:
    """github.com/laris-co/neo-oracle -> the Claude project folder form, -opt-Code-github-com-laris-co-neo-oracle."""
    return like(re.sub(r"[/.]", "-", repo.strip("/")))


def uid(r: Json) -> str:
    msgkey: str = r["msgkey"]
    return msgkey + (f":{r['chunk']}" if r.get("chunk") else "")


def folded(src: str, where: str = "TRUE") -> str:
    """Rows of src that pass `where`, one per (msgkey, chunk): the first machine by name, plus every machine."""
    return f"""(SELECT * EXCLUDE (rn) FROM (SELECT *, list(machine) OVER (PARTITION BY msgkey, chunk ORDER BY machine
               ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING) AS machines,
               row_number() OVER (PARTITION BY msgkey, chunk ORDER BY machine) AS rn FROM {src} WHERE {where}) WHERE rn = 1)"""


def home_kind(home: str | None, agent: str | None = None) -> Json:
    """Whose a home is and what kind: the owner from the path (the last /Users/<u>/ or /home/<u>/, so a mirror of nat's
    ~/.claude under beta's folder is nat's), else relic-scan's user@host; the kind: user (~/.claude, ~/.codex), extra
    (another home of the same user: ~/.claude1, ~/.claude-lean), mirror (a copy: .relic3-mirror, .relic-mirrors), backup (a backup or attic
    folder inside a home: .codex/path-migration-backup-*, .codex-team-attic/slot-3-dead),
    export (/Users/Shared/<u>-export), project (a .claude inside a project or an archive), unknown (no src_path)."""
    if not home:
        return {"user": (agent or "").split("@")[0] or None, "kind": "unknown", "label": "unknown (parts before src_path)"}
    owners = re.findall(r"/(?:Users|home)/([^/]+)/", home + "/")
    exp = re.search(r"/Users/Shared/([^/]+?)-export/", home + "/")
    user = (exp.group(1) if exp else None) or next((u for u in reversed(owners) if u != "Shared"), None) or (agent or "").split("@")[0] or None
    if "/.relic3-mirror/" in home or "/.relic-mirrors/" in home:
        kind = "mirror"
    elif re.search(r"/\.(?:claude|codex)[^/]*(?:-attic/|/.*(?:backup|attic|rescued|-dead))", home):
        kind = "backup"
    elif exp:
        kind = "export"
    elif re.fullmatch(r"/(?:Users|home)/[^/]+/\.(?:claude|codex)", home):
        kind = "user"
    elif re.fullmatch(r"/(?:Users|home)/[^/]+/\.(?:claude|codex)(?:[^/]+|[^/]*/[^/]+)", home):   # ~/.claude1, ~/.codex-team/1
        kind = "extra"
    else:
        kind = "project"
    m = re.match(r"^/(?:Users|home)/([^/]+)/(.*)$", home)
    label = f"~{'' if m and m.group(1) == user else m.group(1) if m else ''}/{m.group(2)}" if m else home
    return {"user": user, "kind": kind, "label": label}


class Relic5:
    _resolved: str | None   # how show() placed an old relic3 id, set by _parse_id

    def __init__(self, root: str, con: "duckdb.DuckDBPyConnection") -> None:
        from .fts import Index
        self.parts = Parts(root)
        self.con = rfs.duck(con, self.parts.root)   # an S3 root: the connection reads s3:// through httpfs
        self.index = Index(root)

    def _rows(self, sql: str, params: Sequence[object] = ()) -> list[Json]:
        cur = self.con.cursor()   # a cursor per call: the HTTP handlers run in threads
        res = cur.execute(sql, list(params))
        names = [d[0] for d in res.description]
        return [dict(zip(names, r)) for r in res.fetchall()]

    def _meta(self) -> str | None:
        fs = self.parts.meta()
        if not fs:
            return None
        lst = ", ".join("'" + f.replace("'", "''") + "'" for f in fs)
        # one row per sid: a main session over a subagent copy, then the first machine by name, then the most complete
        # copy (latest last_ts, most rows, then by file name). Without the last three a sid held twice on one machine
        # (~/.claude and a mirror) picked a copy at random, and relic_sessions' total moved between calls (2026-10-24).
        return f"""(SELECT * EXCLUDE (rn) FROM (SELECT *, row_number() OVER (PARTITION BY sid ORDER BY tier <> 'main', machine,
                   last_ts DESC NULLS LAST, n_rows DESC NULLS LAST, base) AS rn
                   FROM (SELECT regexp_extract(filename, '/parts/([^/]+)/', 1) AS machine, * EXCLUDE (filename)
                   FROM read_parquet([{lst}], union_by_name = true, filename = true))) WHERE rn = 1)"""

    def meta_has(self, col: str) -> bool:
        """Does any machine's sessions.parquet carry this column (relic-scan PR #37 added cwd, title, branch, version)?
        Machines without it read NULL there (union_by_name), so one is enough: an import's meta never has them."""
        fs = self.parts.meta()
        if not fs:
            return False
        try:
            return any(col in {r[0] for r in self.con.cursor().execute(f"DESCRIBE SELECT * FROM read_parquet('{f}')").fetchall()} for f in fs)
        except Exception:
            return False

    def sessions_of_home(self, home: str) -> list[str]:
        """Every session whose home holds this (substring, case-blind): names.build_homes."""
        from .names import homes_path
        p = homes_path(self.parts.root)
        if not rfs.exists(p):
            return []
        return [r["sid"] for r in self._rows(f"SELECT sid FROM read_parquet('{p}') WHERE lower(home) LIKE ?", ["%" + home.lower() + "%"])]

    def homes(self) -> Json:
        """Where the history comes from: per machine and home, the user@host, sessions, messages, first and last."""
        from .names import homes_path
        p = homes_path(self.parts.root)
        if not rfs.exists(p):
            return {"homes": [], "note": "no homes table yet: run relic5 index"}
        rows = self._rows(f"""SELECT machine, home, mode(agent) AS agent, count(*) AS sessions, sum(messages) AS messages,
                                     min(first_ts) AS first, max(last_ts) AS last
                              FROM read_parquet('{p}') GROUP BY machine, home ORDER BY messages DESC""")
        for r in rows:
            r.update(home_kind(r["home"], r["agent"]))
        return {"homes": rows}

    def _names(self, sids: Collection[str]) -> dict[str, str]:
        from .names import path
        p = path(self.parts.root)
        if not sids or not rfs.exists(p):
            return {}
        return {r["sid"]: r["name"] for r in self._rows(f"SELECT sid, name FROM read_parquet('{p}') WHERE sid IN (SELECT unnest(?))", [list(sids)])}

    def _repos(self, sids: Collection[str]) -> dict[str, str]:
        meta = self._meta()
        if not meta or not sids:
            return {}
        return {r["sid"]: r["proj"] for r in self._rows(f"SELECT sid, proj FROM {meta} WHERE sid IN (SELECT unnest(?))", [list(sids)])}

    # ---- search ----
    def search(self, query: str | None, since: str | None = None, until: str | None = None, horizon: str | None = None,
               repo: str | None = None, session: str | None = None, role: str | None = None, tier: str | None = None,
               with_: str | None = None, limit: int = DEFAULT_LIMIT, cursor: str | None = None,
               vector: Sequence[float] | None = None, model: str | None = None, hybrid: bool = False, sort: str | None = None,
               min_chars: int | None = None, cwd: str | None = None, branch: str | None = None, title: str | None = None,
               via: str | None = None, chat: str | None = None, from_user: str | None = None, home: str | None = None) -> Json:
        """BM25 over the published index (search.py); ILIKE over the parts when none is built or FTS cannot parse
        the query (relic3 falls back the same way, query.ts:127-140)."""
        if query is None or not query.split():   # None or blank
            raise UsageError("search needs a query")
        kw = SearchKw(since=since, until=until, horizon=horizon, repo=repo, session=session, role=role, tier=tier, with_=with_,
                       limit=limit, cursor=cursor)
        if vector is not None:
            if not self.index.built():
                raise UsageError("no index published yet")
            from . import search as S
            return S.search(self, self.index, query, vector=vector, model=model, hybrid=hybrid, sort=sort, min_chars=min_chars, cwd=cwd, branch=branch, title=title, via=via, chat=chat, from_user=from_user, home=home, **kw)
        if self.index.built():
            from . import search as S
            try:
                return S.search(self, self.index, query, sort=sort, cwd=cwd, branch=branch, title=title, via=via, chat=chat,
                                from_user=from_user, home=home, **kw)
            except UsageError:
                raise
            except NotFound:
                raise
            except Exception as ex:   # an FTS parse error: answer by substring, and say so
                r = self.search_ilike(query, **kw)
                r["fallback"] = f"substring match ({type(ex).__name__})"
                return r
        return self.search_ilike(query, **kw)

    def search_ilike(self, query: str | None, since: str | None = None, until: str | None = None, horizon: str | None = None,
                     repo: str | None = None, session: str | None = None, role: str | None = None, tier: str | None = None,
                     with_: str | None = None, limit: int = DEFAULT_LIMIT, cursor: str | None = None) -> Json:
        words = (query or "").split()
        if not words:
            raise UsageError("search needs a query")
        streams = ["text"] + ([s for s in with_.split(",") if s] if with_ else [])
        if with_ == "all":
            streams = list(STREAMS)
        for s in streams:
            if s not in STREAMS:
                raise UsageError(f"with {s}: one of tools, thinking, vault, all")
        try:
            lo, hi, hz = window(since, until, horizon)
        except ValueError as ex:
            raise UsageError(str(ex))
        where: list[str] = []
        params: list[object] = []
        for w in words:
            where.append("text ILIKE ? ESCAPE '\\'")
            params.append(like(w))
        for cond, v in (("ts >= ?", lo), ("ts <= ?", hi), ("role = ?", role), ("starts_with(sid, ?)", session)):
            if v:
                where.append(cond)
                params.append(v)
        meta = self._meta()
        if repo or tier:
            if not meta:
                raise UsageError("repo/tier need relic-scan's meta/sessions.parquet on the hub (push it)")
            sub: list[str] = []
            sp: list[object] = []
            if repo:
                sub.append("proj ILIKE ? ESCAPE '\\'")
                sp.append(repo_pattern(repo))
            if tier:
                sub.append("tier = ?")
                sp.append(tier)
            where.append(f"sid IN (SELECT sid FROM {meta} WHERE {' AND '.join(sub)})")
            params += sp
        sig = hashlib.sha1(json.dumps([query, lo, hi, repo, session, role, tier, with_]).encode()).hexdigest()[:12]
        off = 0
        if cursor:
            try:
                c = json.loads(base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)))
                off = int(c["o"])
                assert c["q"] == sig
            except Exception:
                raise UsageError("bad cursor: it belongs to another query")
        srcs = [(s, self.parts.source(s)) for s in streams]
        srcs = [(s, x) for s, x in srcs if x]
        hits: list[Json] = []
        months: list[str] = []
        if srcs:
            union = " UNION ALL BY NAME ".join(f"SELECT '{s}' AS layer, {COLS} FROM {x}" for s, x in srcs)
            score = " + ".join("(length(lower(text)) - length(replace(lower(text), lower(?), ''))) // ?" for _ in words)
            sp = [x for w in words for x in (w, len(w))]
            rows = self._rows(f"""SELECT *, {score} AS score,
                     substr(text, greatest(1, strpos(lower(text), lower(?)) - 100), 300) AS snip
                     FROM {folded('(' + union + ')', ' AND '.join(where))}
                     ORDER BY score DESC, ts DESC, msgkey, chunk LIMIT ? OFFSET ?""",
                              sp + [words[0]] + params + [limit + 1, off])   # placeholders in text order
            more = len(rows) > limit
            rows = rows[:limit]
            repos = self._repos({r["sid"] for r in rows if r["sid"]})
            for r in rows:
                hits.append(self._hit(r, repos))
            months = sorted({r["month"] for r in rows if r["month"]})
        else:
            more = False
        nxt = base64.urlsafe_b64encode(json.dumps({"o": off + limit, "q": sig}).encode()).decode().rstrip("=") if more else None
        return {"hits": hits, "next_cursor": nxt, "horizon": hz, "horizons_tried": [hz], "widened": False,
                "searched_weeks": months, "searched_months": months}

    def _hit(self, r: Json, repos: dict[str, str]) -> Json:
        text = " ".join((r.get("snip") or "").split())
        return {"uid": uid(r), "partition": r["month"], "session_uuid": r["sid"], "role": r["role"], "ts": r["ts"],
                "day": (r["ts_th"] or "")[:10] or None, "repo_key": repos.get(r["sid"]), "text_snippet": "…" + text + "…",
                "score": r.get("score", 0), "layer": r["layer"], "source_present": False, "machines": r["machines"],
                "link": f"relic5://{r['month']}/{uid(r)}",
                "locator": {"month": r["month"], "stream": r["layer"], "key": r["key"], "chunk": r["chunk"]}}

    # ---- show ----
    def _relic3(self, ident: str) -> tuple[str, str] | None:
        """An old relic3:// link or 40-hex uid -> (msgkey, how) through resolve/relic3.parquet, or None."""
        m = re.search(r"([0-9a-f]{40})$", ident)
        p = os.path.join(self.parts.root, "resolve", "relic3.parquet")
        if not m or not rfs.exists(p):
            return None
        rows = self._rows(f"SELECT sid, ts, role, layer, msgkey FROM read_parquet('{p}') WHERE uid = ?", [m.group(1)])
        if not rows:
            return None
        r = rows[0]
        if r["msgkey"]:
            for s in ("text", "vault"):
                src = self.parts.source(s)
                if src and self._rows(f"SELECT 1 FROM {src} WHERE msgkey = ? LIMIT 1", [r["msgkey"]]):
                    return r["msgkey"], "relic3 uid -> msgkey"
        if r["role"] == "note" and r["sid"] and "/ψ/" in r["sid"]:
            # relic3 keyed a ψ note by its absolute path; relic5's vault rows carry the path inside the ψ vault
            src = self.parts.source("vault")
            rel = r["sid"].split("/ψ/", 1)[1]
            hit = self._rows(f"""SELECT msgkey FROM {src} WHERE path = ? ORDER BY (vault IS NOT NULL AND ? LIKE '%' || vault || '%') DESC, chunk
                                 LIMIT 1""", [rel, r["sid"]]) if src else []
            if hit:
                return hit[0]["msgkey"], f"relic3 note -> ψ note {rel}"
        stream = "tools" if r["layer"] == "tools" else "text"
        src = self.parts.source(stream)
        if src and r["sid"]:
            hit = self._rows(f"""SELECT msgkey FROM {src} WHERE sid = ? AND ts = ? ORDER BY (role = ?) DESC, chunk LIMIT 1""",
                             [r["sid"], r["ts"], r["role"] if stream == "text" else ""])
            if hit:
                return hit[0]["msgkey"], "relic3 uid -> (session, ts)"
            # the row itself was cleaned out on purpose (harness turns, relayed messages): the nearest message of that
            # session within 10 minutes, so the link still lands in its conversation
            near = self._rows(f"""SELECT msgkey, ts FROM {src} WHERE sid = ? AND chunk = 0
                                   AND abs(epoch(CAST(ts AS TIMESTAMP)) - epoch(CAST(? AS TIMESTAMP))) <= 600
                                   ORDER BY abs(epoch(CAST(ts AS TIMESTAMP)) - epoch(CAST(? AS TIMESTAMP))) LIMIT 1""",
                              [r["sid"], r["ts"], r["ts"]])
            if near:
                return near[0]["msgkey"], (f"relic3 uid -> nearest message in its session ({near[0]['ts']}); the linked "
                                           f"{r['role']} row at {r['ts']} is not on the hub (relic-extract cleans such rows out)")
        return None

    def _parse_id(self, ident: str) -> tuple[str | None, str, int] | None:
        ident = ident.strip()
        if ident.startswith("relic3://") or re.fullmatch(r"[0-9a-f]{40}", ident):
            found = self._relic3(ident)
            if found:
                self._resolved = found[1]
                return None, found[0], 0
            raise UsageError("a relic3 id that relic5 cannot place (not in resolve/relic3.parquet, or its row is not on the hub)"
                             " - search relic5 again for this message")
        month = None
        m = re.fullmatch(r"relic5://(\d{4}-\d{2}|undated)/([0-9a-f]{32})(?::(\d+))?", ident)
        if m:
            return m.group(1), m.group(2), int(m.group(3) or 0)
        m = re.fullmatch(r"([0-9a-f]{32})(?::(\d+))?", ident)
        if m:
            return month, m.group(1), int(m.group(2) or 0)
        return None

    def show(self, ident: str | None, seq: int | None = None, before: int = 2, after: int = 2) -> Json:
        if not ident:
            raise UsageError("show needs id (msgkey | relic5:// link | session id with seq)")
        parsed = self._parse_id(ident)
        month: str | None
        if parsed is None:
            if seq is None:
                raise UsageError(f"{ident}: not a msgkey or relic5:// link (a session id needs seq)")
            src = self.parts.source("text")
            rows = self._rows(f"""SELECT msgkey FROM {folded(src, "starts_with(sid, ?) AND chunk = 0")} ORDER BY ts, msgkey
                                  LIMIT 1 OFFSET ?""", [ident, seq]) if src else []
            if not rows:
                raise NotFound(f"no message {seq} in session {ident}")
            month, msgkey, chunk = None, rows[0]["msgkey"], 0
        else:
            month, msgkey, chunk = parsed
        parts: list[Json] = []
        layer: str | None = None
        for s in STREAMS:
            src = self.parts.source(s, month if s != "vault" else None)
            if not src:
                continue
            parts = self._rows(f"SELECT '{s}' AS layer, * FROM {folded(src, 'msgkey = ?')} ORDER BY chunk", [msgkey])
            if parts:
                layer = s
                break
        # a memory note (memory.py) or a git commit (gitlog.py): its own table, no session neighbours
        for side, (d, f), what in (("memory", ("_memory", "notes.parquet"), "memory note"), ("git", ("_git", "commits.parquet"), "git commit")):
            mp = os.path.join(self.parts.root, "index", d, f)
            if parts or not rfs.exists(mp):
                continue
            hit = self._rows(f"SELECT * EXCLUDE (machine) FROM read_parquet('{mp}') WHERE msgkey = ?", [msgkey])
            if hit:
                t = hit[0] | {"link": f"relic5://{hit[0]['month']}/{msgkey}", "uid": msgkey}
                note = f"{what} ({t['role']}) from {t['path']}" + (f", {t['hash']} in {', '.join(t['repos'])}" if side == "git" else "")
                return {"link": t["link"], "target": t, "notes": [note], "parts": [t], "before": [], "after": [], "raw": None, "layer": side}
        if not parts:
            raise NotFound(f"no message {msgkey}" + (f" in {month}" if month else ""))
        target = next((p for p in parts if p["chunk"] == chunk), parts[0])
        before_rows, after_rows = self._neighbours(target, before, after)
        clean: Callable[[Json], Json] = lambda r: {k: v for k, v in r.items() if k not in ("machine",)} | {"uid": uid(r), "link": f"relic5://{r['month']}/{uid(r)}"}
        notes: list[str] = []
        if getattr(self, "_resolved", None):
            notes.append(f"resolved an old relic3 id: {self._resolved}")
            self._resolved = None
        if target.get("type") == "relic3-merged":
            notes.append("imported from relic3: this assistant row may carry its thinking inline (relic3 stored them as one row)")
        return {"link": f"relic5://{target['month']}/{uid(target)}", "target": clean(target), "notes": notes,
                "parts": [clean(p) for p in parts], "before": before_rows, "after": after_rows, "raw": None, "layer": layer}

    def _neighbours(self, t: Json, before: int, after: int) -> tuple[list[Json], list[Json]]:
        src = self.parts.source("text")
        if not src or not t.get("sid"):
            return [], []
        cols = "msgkey, month, sid, ts, ts_th, role, engine, machines, substr(text, 1, 2000) AS text"
        base = folded(src, "sid = ? AND chunk = 0")
        b = self._rows(f"""SELECT {cols} FROM {base} WHERE ts < ? OR (ts = ? AND msgkey < ?)
                           ORDER BY ts DESC, msgkey DESC LIMIT ?""", [t["sid"], t["ts"], t["ts"], t["msgkey"], before])
        a = self._rows(f"""SELECT {cols} FROM {base} WHERE ts > ? OR (ts = ? AND msgkey > ?)
                           ORDER BY ts, msgkey LIMIT ?""", [t["sid"], t["ts"], t["ts"], t["msgkey"], after])
        link: Callable[[Json], Json] = lambda r: r | {"uid": r["msgkey"], "link": f"relic5://{r['month']}/{r['msgkey']}"}
        return [link(r) for r in reversed(b)], [link(r) for r in a]

    # ---- tail ----
    def tail(self, n: int = 50, session: str | None = None, machine: str | None = None, since: str | None = None) -> Json:
        """The newest messages as they land (open month first), every machine or one session: chunk 0 of each."""
        from .parts import this_month
        mons = sorted(self.parts.months(), reverse=True)[:2]   # the open month, and the last one across a rollover
        src = self.parts.source("text", months=set(mons))
        if not src:
            return {"rows": []}
        where: list[str] = ["chunk = 0"]
        params: list[object] = []
        for cond, v in (("starts_with(sid, ?)", session), ("ts > ?", since)):
            if v:
                where.append(cond)
                params.append(v)
        if machine:
            where.append("machine = ?")
            params.append(machine)
        rows = self._rows(f"""SELECT msgkey, month, sid, ts, ts_th, role, engine, cat, machines, substr(text, 1, 600) AS text
                              FROM {folded(src, ' AND '.join(where))} ORDER BY ts DESC LIMIT ?""", params + [int(n)])
        names = self._names({r["sid"] for r in rows if r["sid"]})
        for r in rows:
            r["session_name"] = names.get(r["sid"])
            r["link"] = f"relic5://{r['month']}/{r['msgkey']}"
        return {"rows": rows, "newest": rows[0]["ts"] if rows else None}

    # ---- sessions ----
    def sessions(self, repo: str | None = None, since: str | None = None, until: str | None = None, limit: int | None = None,
                 via: str | None = None, chat: str | None = None, from_user: str | None = None, by_repo: bool = False,
                 home: str | None = None) -> Json:
        meta = self._meta()
        if not meta:
            raise NotFound("no sessions on the hub: push relic-scan's meta/sessions.parquet")
        try:
            lo, hi, _ = window(since, until)
        except ValueError as ex:
            raise UsageError(str(ex))
        where: list[str] = ["parent_sid IS NULL"]
        params: list[object] = []
        for col, v in (("via", via), ("chat", chat), ("from_user", from_user)):
            if v and not self.meta_has(col):
                raise UsageError(f"{col} is not in the index yet (needs a newer relic-scan meta on some machine)")
        for cond, v in (("proj ILIKE ? ESCAPE '\\'", repo and repo_pattern(repo)), ("last_ts >= ?", lo), ("first_ts <= ?", hi),
                        ("via ILIKE ? ESCAPE '\\'", via and like(via)), ("chat ILIKE ? ESCAPE '\\'", chat and like(chat)),
                        ("from_user ILIKE ? ESCAPE '\\'", from_user and like(from_user))):
            if v:
                where.append(cond)
                params.append(v)
        if home:   # whose .claude: the sessions names.build_homes found in that home
            from .names import homes_path
            hp = homes_path(self.parts.root)
            if not rfs.exists(hp):
                raise UsageError("home is not in the index yet: run relic5 index")
            where.append(f"sid IN (SELECT sid FROM read_parquet('{hp}') WHERE lower(home) LIKE ?)")
            params.append("%" + home.lower() + "%")
        w = " AND ".join(where)
        total, events = self._rows(f"SELECT count(*) AS n, coalesce(sum(n_rows), 0) AS e FROM {meta} WHERE {w}", params)[0].values()
        # the same window and filters with subagents too: every session once, so "transcript events" is every .jsonl
        # record (2026-10-24: 7.37M, where top-level alone said 5.23M)
        w_all = " AND ".join(where[1:]) or "true"
        a = self._rows(f"""SELECT count(*) AS n, coalesce(sum(n_rows), 0)::BIGINT AS e, count(*) FILTER (parent_sid IS NOT NULL) AS sn,
                           coalesce(sum(n_rows) FILTER (parent_sid IS NOT NULL), 0)::BIGINT AS se FROM {meta} WHERE {w_all}""", params)[0]
        rows = self._rows(f"""SELECT s.*, (SELECT count(*) FROM {meta} c WHERE c.parent_sid = s.sid) AS children
                              FROM {meta} s WHERE {w} ORDER BY last_ts DESC NULLS LAST LIMIT ?""", params + [limit or DEFAULT_LIMIT])
        names = self._names({r["sid"] for r in rows})
        rows = [r | {"name": names.get(r["sid"])} for r in rows]
        out: Json = {"total": total, "counted": "top-level sessions only (no parent_sid); subagents fold into children",
                     "events": int(events), "sessions": [self._session_row(r) for r in rows],
                     "all": {"sessions": a["n"], "events": int(a["e"]), "subagents": a["sn"], "subagent_events": int(a["se"])}}
        if by_repo:   # the same window and filters, counted per repo; a session with no repo (Codex) counts by its tenant
            repos = self._rows(f"""SELECT coalesce(proj, '(no repo) ' || coalesce(cat, '?')) AS repo, count(*) AS sessions,
                                      coalesce(sum(n_rows), 0)::BIGINT AS events FROM {meta} WHERE {w}
                                      GROUP BY 1 ORDER BY sessions DESC, repo""", params)
            top, rest = repos[:200], repos[200:]
            if rest:   # the long tail as one row, so the counts always add up to total
                top.append({"repo": f"(other {len(rest)} repos)", "sessions": sum(r["sessions"] for r in rest),
                            "events": sum(r["events"] for r in rest)})
            out["repos"] = top
        return out

    def _session_row(self, r: Json) -> Json:
        return {"uuid": r["sid"], "name": r.get("name"), "home": r["machine"], "tenant": r["cat"], "source": r["engine"],
                "link": f"relic5://session/{r['sid']}", "repo": r["proj"], "worktree": "", "tier": r["tier"],
                "startedAt": r["first_ts"], "endedAt": r["last_ts"], "events": r["n_rows"], "children": r.get("children", 0),
                "months": r["months"]}

    def session(self, ident: str | None) -> Json:
        if not ident:
            raise UsageError("session needs id (session id prefix)")
        meta = self._meta()
        if not meta:
            raise NotFound("no sessions on the hub: push relic-scan's meta/sessions.parquet")
        ident = ident.removeprefix("relic5://session/")
        rows = self._rows(f"SELECT * FROM {meta} WHERE starts_with(sid, ?) ORDER BY tier <> 'main', last_ts DESC LIMIT 6", [ident])
        if not rows:
            raise NotFound(f"no session {ident}")
        if len({r["sid"] for r in rows}) > 1 and rows[0]["sid"] != ident:
            raise UsageError(f"{ident} names {len(rows)}+ sessions: " + ", ".join(r["sid"] for r in rows[:5]))
        s = rows[0]
        kids = self._rows(f"SELECT * FROM {meta} WHERE parent_sid = ? ORDER BY first_ts", [s["sid"]])
        names = self._names({s["sid"]} | {k["sid"] for k in kids})
        s = s | {"name": names.get(s["sid"])}
        kids = [k | {"name": names.get(k["sid"])} for k in kids]
        out = self._session_row(s | {"children": len(kids)})
        cwd = s.get("cwd")
        resume = None
        if cwd:
            resume = f"cd {cwd} && " + (f"codex resume {s['sid']}" if s.get("engine") == "codex" else f"claude --resume {s['sid']}")
        out |= {"cwd": cwd, "branch": s.get("branch"), "version": s.get("version"), "title": s.get("title"), "resume": resume,
                "parent": s["parent_sid"], "base": s["base"], "counts": {k: s[k] for k in (
            "text_rows", "text_msgs", "user_text", "assistant_text", "thinking", "tool_calls", "tool_results", "tool_errors")},
                "subagents": [self._session_row(k) for k in kids]}
        return out
