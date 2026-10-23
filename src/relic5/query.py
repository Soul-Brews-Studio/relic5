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

from .parts import STREAMS, Parts
from .window import window

DEFAULT_LIMIT = 20
HEX32 = re.compile(r"^[0-9a-f]{32}$")
COLS = "machine, key, msgkey, chunk, month, sid, ts, ts_th, engine, role, type, kind, name, cat, text"


class UsageError(ValueError):
    pass


class NotFound(LookupError):
    pass


def like(word):
    return "%" + re.sub(r"([%_\\])", r"\\\1", word) + "%"


def repo_pattern(repo):
    """github.com/laris-co/neo-oracle -> the Claude project folder form, -opt-Code-github-com-laris-co-neo-oracle."""
    return like(re.sub(r"[/.]", "-", repo.strip("/")))


def uid(r):
    return r["msgkey"] + (f":{r['chunk']}" if r.get("chunk") else "")


def folded(src, where="TRUE"):
    """Rows of src that pass `where`, one per (msgkey, chunk): the first machine by name, plus every machine."""
    return f"""(SELECT * EXCLUDE (rn) FROM (SELECT *, list(machine) OVER (PARTITION BY msgkey, chunk ORDER BY machine
               ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING) AS machines,
               row_number() OVER (PARTITION BY msgkey, chunk ORDER BY machine) AS rn FROM {src} WHERE {where}) WHERE rn = 1)"""


class Relic5:
    def __init__(self, root, con):
        from .fts import Index
        self.parts = Parts(root)
        self.con = con
        self.index = Index(root)

    def _rows(self, sql, params=()):
        cur = self.con.cursor()   # a cursor per call: the HTTP handlers run in threads
        res = cur.execute(sql, list(params))
        names = [d[0] for d in res.description]
        return [dict(zip(names, r)) for r in res.fetchall()]

    def _meta(self):
        fs = self.parts.meta()
        if not fs:
            return None
        lst = ", ".join("'" + f.replace("'", "''") + "'" for f in fs)
        # one row per sid: a main session over a subagent copy, then the first machine by name
        return f"""(SELECT * EXCLUDE (rn) FROM (SELECT *, row_number() OVER (PARTITION BY sid ORDER BY tier <> 'main', machine) AS rn
                   FROM (SELECT regexp_extract(filename, '/parts/([^/]+)/', 1) AS machine, * EXCLUDE (filename)
                   FROM read_parquet([{lst}], union_by_name = true, filename = true))) WHERE rn = 1)"""

    def _names(self, sids):
        from .names import path
        p = path(self.parts.root)
        if not sids or not os.path.exists(p):
            return {}
        return {r["sid"]: r["name"] for r in self._rows(f"SELECT sid, name FROM read_parquet('{p}') WHERE sid IN (SELECT unnest(?))", [list(sids)])}

    def _repos(self, sids):
        meta = self._meta()
        if not meta or not sids:
            return {}
        return {r["sid"]: r["proj"] for r in self._rows(f"SELECT sid, proj FROM {meta} WHERE sid IN (SELECT unnest(?))", [list(sids)])}

    # ---- search ----
    def search(self, query, since=None, until=None, horizon=None, repo=None, session=None, role=None, tier=None,
               with_=None, limit=DEFAULT_LIMIT, cursor=None, vector=None, model=None, hybrid=False):
        """BM25 over the published index (search.py); ILIKE over the parts when none is built or FTS cannot parse
        the query (relic3 falls back the same way, query.ts:127-140)."""
        if not (query or "").split():
            raise UsageError("search needs a query")
        kw = dict(since=since, until=until, horizon=horizon, repo=repo, session=session, role=role, tier=tier, with_=with_,
                  limit=limit, cursor=cursor)
        if vector is not None:
            if not self.index.built():
                raise UsageError("no index published yet")
            from . import search as S
            return S.search(self, self.index, query, vector=vector, model=model, hybrid=hybrid, **kw)
        if self.index.built():
            from . import search as S
            try:
                return S.search(self, self.index, query, **kw)
            except UsageError:
                raise
            except Exception as ex:   # an FTS parse error: answer by substring, and say so
                r = self.search_ilike(query, **kw)
                r["fallback"] = f"substring match ({type(ex).__name__})"
                return r
        return self.search_ilike(query, **kw)

    def search_ilike(self, query, since=None, until=None, horizon=None, repo=None, session=None, role=None, tier=None,
                     with_=None, limit=DEFAULT_LIMIT, cursor=None):
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
        where, params = [], []
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
            sub, sp = [], []
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
        hits, months = [], []
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

    def _hit(self, r, repos):
        text = " ".join((r.get("snip") or "").split())
        return {"uid": uid(r), "partition": r["month"], "session_uuid": r["sid"], "role": r["role"], "ts": r["ts"],
                "day": (r["ts_th"] or "")[:10] or None, "repo_key": repos.get(r["sid"]), "text_snippet": "…" + text + "…",
                "score": r.get("score", 0), "layer": r["layer"], "source_present": False, "machines": r["machines"],
                "link": f"relic5://{r['month']}/{uid(r)}",
                "locator": {"month": r["month"], "stream": r["layer"], "key": r["key"], "chunk": r["chunk"]}}

    # ---- show ----
    def _parse_id(self, ident):
        ident = ident.strip()
        if ident.startswith("relic3://") or re.fullmatch(r"[0-9a-f]{40}", ident):
            raise UsageError("a relic3 id: relic5 keys messages by msgkey - search relic5 again for this message")
        month = None
        m = re.fullmatch(r"relic5://(\d{4}-\d{2}|undated)/([0-9a-f]{32})(?::(\d+))?", ident)
        if m:
            return m.group(1), m.group(2), int(m.group(3) or 0)
        m = re.fullmatch(r"([0-9a-f]{32})(?::(\d+))?", ident)
        if m:
            return month, m.group(1), int(m.group(2) or 0)
        return None

    def show(self, ident, seq=None, before=2, after=2):
        if not ident:
            raise UsageError("show needs id (msgkey | relic5:// link | session id with seq)")
        parsed = self._parse_id(ident)
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
        parts, layer = [], None
        for s in STREAMS:
            src = self.parts.source(s, month if s != "vault" else None)
            if not src:
                continue
            parts = self._rows(f"SELECT '{s}' AS layer, * FROM {folded(src, 'msgkey = ?')} ORDER BY chunk", [msgkey])
            if parts:
                layer = s
                break
        if not parts:
            raise NotFound(f"no message {msgkey}" + (f" in {month}" if month else ""))
        target = next((p for p in parts if p["chunk"] == chunk), parts[0])
        before_rows, after_rows = self._neighbours(target, before, after)
        clean = lambda r: {k: v for k, v in r.items() if k not in ("machine",)} | {"uid": uid(r), "link": f"relic5://{r['month']}/{uid(r)}"}
        return {"link": f"relic5://{target['month']}/{uid(target)}", "target": clean(target),
                "parts": [clean(p) for p in parts], "before": before_rows, "after": after_rows, "raw": None, "layer": layer}

    def _neighbours(self, t, before, after):
        src = self.parts.source("text")
        if not src or not t.get("sid"):
            return [], []
        cols = "msgkey, month, sid, ts, ts_th, role, engine, machines, substr(text, 1, 2000) AS text"
        base = folded(src, "sid = ? AND chunk = 0")
        b = self._rows(f"""SELECT {cols} FROM {base} WHERE ts < ? OR (ts = ? AND msgkey < ?)
                           ORDER BY ts DESC, msgkey DESC LIMIT ?""", [t["sid"], t["ts"], t["ts"], t["msgkey"], before])
        a = self._rows(f"""SELECT {cols} FROM {base} WHERE ts > ? OR (ts = ? AND msgkey > ?)
                           ORDER BY ts, msgkey LIMIT ?""", [t["sid"], t["ts"], t["ts"], t["msgkey"], after])
        link = lambda r: r | {"uid": r["msgkey"], "link": f"relic5://{r['month']}/{r['msgkey']}"}
        return [link(r) for r in reversed(b)], [link(r) for r in a]

    # ---- tail ----
    def tail(self, n=50, session=None, machine=None, since=None):
        """The newest messages as they land (open month first), every machine or one session: chunk 0 of each."""
        from .parts import this_month
        mons = sorted(self.parts.months(), reverse=True)[:2]   # the open month, and the last one across a rollover
        src = self.parts.source("text", months=set(mons))
        if not src:
            return {"rows": []}
        where, params = ["chunk = 0"], []
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
    def sessions(self, repo=None, since=None, until=None, limit=None):
        meta = self._meta()
        if not meta:
            raise NotFound("no sessions on the hub: push relic-scan's meta/sessions.parquet")
        try:
            lo, hi, _ = window(since, until)
        except ValueError as ex:
            raise UsageError(str(ex))
        where, params = ["parent_sid IS NULL"], []
        for cond, v in (("proj ILIKE ? ESCAPE '\\'", repo and repo_pattern(repo)), ("last_ts >= ?", lo), ("first_ts <= ?", hi)):
            if v:
                where.append(cond)
                params.append(v)
        w = " AND ".join(where)
        total, events = self._rows(f"SELECT count(*) AS n, coalesce(sum(n_rows), 0) AS e FROM {meta} WHERE {w}", params)[0].values()
        rows = self._rows(f"""SELECT s.*, (SELECT count(*) FROM {meta} c WHERE c.parent_sid = s.sid) AS children
                              FROM {meta} s WHERE {w} ORDER BY last_ts DESC NULLS LAST LIMIT ?""", params + [limit or DEFAULT_LIMIT])
        names = self._names({r["sid"] for r in rows})
        rows = [r | {"name": names.get(r["sid"])} for r in rows]
        return {"total": total, "counted": "top-level sessions only (no parent_sid); subagents fold into children",
                "events": int(events), "sessions": [self._session_row(r) for r in rows]}

    def _session_row(self, r):
        return {"uuid": r["sid"], "name": r.get("name"), "home": r["machine"], "tenant": r["cat"], "source": r["engine"],
                "link": f"relic5://session/{r['sid']}", "repo": r["proj"], "worktree": "", "tier": r["tier"],
                "startedAt": r["first_ts"], "endedAt": r["last_ts"], "events": r["n_rows"], "children": r.get("children", 0),
                "months": r["months"]}

    def session(self, ident):
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
        out |= {"parent": s["parent_sid"], "base": s["base"], "counts": {k: s[k] for k in (
            "text_rows", "text_msgs", "user_text", "assistant_text", "thinking", "tool_calls", "tool_results", "tool_errors")},
                "subagents": [self._session_row(k) for k in kids]}
        return out
