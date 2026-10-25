"""arra.py: ARRA Oracle Studio (studio.buildwithoracle.com, ui-oracle apps/studio) reading relic5 (Nat, 2026-10-25: "can we
make https://studio.buildwithoracle.com/ support? the ui?" -> "Studio reads relic5", "can go tailscale serve https! and
can we make like adaptor").

Studio speaks the arra-oracle API (ui-oracle apps/studio/src/api/oracle.ts): a knowledge base of documents typed
principle | learning | retro, with concepts. This router answers that API under /arra/api from relic5's history:

  document      a ψ note, as arra-oracle indexes them (Nat: "my md should more than 5k"): every machine's vault notes
                (parts/*/vault/notes.parquet, relic-extract), one document per note, its oracle as project
  type          principle = the soul (memory/resonance, identity), retro = memory/retrospectives, learning = the rest
  concepts      [section, oracle, vault]
  /feed         the live message stream (sessions, not notes)
  /map /map3d   a fixed sample of the vector index projected to 2D / 3D (PCA over the real embeddings)
  /graph        the same sample, each document linked to its two nearest neighbours by cosine
  /similar      nearest neighbours of a document's own vector

Open it as studio.buildwithoracle.com/?host=https://white.follow-rankine.ts.net/arra (tailscale serve, HTTPS on the
tailnet). Writes (learn, settings, login) answer read-only: relic5 is a record, not a notebook.
"""
import random, re, threading, time
from collections import Counter
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, PlainTextResponse, Response

from .types_ import Json

# Every ui-oracle app shares the ?host= picker (feed, vector, canvas, forum ... read the same /api), so all of them may read.
APPS = ("studio", "feed", "app", "canvas", "forum", "indexer", "local", "pulse", "schedule", "vector", "vector-playground")
ORIGINS = tuple(f"https://{a}.buildwithoracle.com" for a in APPS)
LOCAL_ORIGIN = re.compile(r"^http://(localhost|127\.0\.0\.1)(:\d+)?$")   # Studio's own dev server
SAMPLE = 3000
GRAPH = 300
_RETRO = re.compile(r"\b(retro|retrospective|/rrr)\b", re.I)


def cors(origin: str | None) -> dict[str, str]:
    """The headers that let Studio's page (another origin, public HTTPS) read the hub on the tailnet."""
    if not origin or not (origin in ORIGINS or LOCAL_ORIGIN.match(origin)):
        return {}
    return {"Access-Control-Allow-Origin": origin, "Vary": "Origin", "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
            "Access-Control-Allow-Headers": "Content-Type", "Access-Control-Allow-Private-Network": "true",
            "Access-Control-Max-Age": "600", "Timing-Allow-Origin": origin}


def project_of(repo_key: str | None) -> str | None:
    """-opt-Code-github-com-Soul-Brews-Studio-relic5 -> github.com/Soul-Brews-Studio-relic5 (owner/repo dashes are
    ambiguous in the folder name, so the rest stays as it is)."""
    if not repo_key:
        return None
    i = repo_key.find("github-com-")
    return "github.com/" + repo_key[i + 11:] if i >= 0 else repo_key.strip("-")


def kind(role: str | None, text: str | None) -> str:
    if (role or "").startswith("memory"):
        return "principle"
    return "retro" if _RETRO.search(text or "") else "learning"


def doc(r: Json) -> Json:
    """A relic5 row (search hit, tail row, vector row) as Studio's Document."""
    text = r.get("text") or r.get("text_snippet") or ""
    machines = r.get("machines") or []
    cat = r.get("cat") or r.get("session_name")
    return {"id": r.get("uid") or r.get("msgkey"), "type": kind(r.get("role"), text), "content": text,
            "source_file": r.get("session_uuid") or r.get("sid") or "", "project": project_of(r.get("repo_key")) or cat,
            "concepts": [c for c in (r.get("role"), cat, machines[0] if machines else None) if c],
            "created_at": r.get("ts"), **({"score": r["score"], "source": "fts"} if r.get("score") is not None else {}),
            **({"score": r["_score"], "source": "vector"} if r.get("_score") is not None else {})}


class Sample:
    """SAMPLE rows of the vector index, their PCA coordinates and nearest-neighbour links, made once per index
    generation (the matrices are the ones semantic search already holds)."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.seen: Any = None
        self.data: Json | None = None

    def get(self, relic: Any) -> Json:
        import numpy as np
        from . import vec as V
        with self.lock:
            idx = relic.index
            mx = idx.matrices(V.DEFAULT) if idx.built() else []
            if self.data is not None and self.seen == getattr(idx, "seen", None):
                return self.data
            rows, vecs = [], []
            total = sum(m.n for m in mx)
            rng = random.Random(23)
            for m in mx:
                take = sorted(rng.sample(range(m.n), min(m.n, max(1, round(SAMPLE * m.n / max(total, 1))))))
                for i in take:
                    if m.cols["chars"][i] < 120:   # tiny chatter sits near everything
                        continue
                    rows.append({k: (m.cols[k][i].item() if hasattr(m.cols[k][i], "item") else m.cols[k][i]) for k in m.META}
                                | {"machines": m.machines[i]})
                    vecs.append(m.M[i])
            if not rows:
                empty: Json = {"docs": [], "links": []}
                self.data, self.seen = empty, getattr(idx, "seen", None)
                return empty
            X = np.asarray(vecs, dtype=np.float32)
            Xc = X - X.mean(axis=0)
            _, sv, vt = np.linalg.svd(Xc, full_matrices=False)
            P = Xc @ vt[:3].T
            P = P / (np.abs(P).max(axis=0) + 1e-9)
            docs = [doc(r) | {"x": float(p[0]), "y": float(p[1]), "z": float(p[2]), "chunk_ids": [r["uid"]]} for r, p in zip(rows, P)]
            # the graph is the first GRAPH documents only: Studio's Graph page runs its force layout in the browser and
            # looks every link's ends up by a linear scan, so 3,000 nodes froze the tab
            g = min(GRAPH, len(docs))
            S = X[:g] @ X[:g].T
            np.fill_diagonal(S, -1)
            nn = np.argsort(-S, axis=1)[:, :2]
            links = {tuple(sorted((docs[a]["id"], docs[int(b)]["id"]))) for a in range(g) for b in nn[a]}
            var = (sv[:3] ** 2) / float((sv ** 2).sum() or 1)
            out: Json = {"docs": docs, "graph": docs[:g], "links": [{"source": s, "target": t} for s, t in links],
                         "pca": {"components": 3, "explained_variance": [round(float(v), 4) for v in var], "sample": len(docs),
                                 "model": V.DEFAULT, "of": total}}
            self.data, self.seen = out, getattr(idx, "seen", None)
            return out


class Notes:
    """The ψ notes every machine pushed (relic-extract: parts/<machine>/vault/notes.parquet), one row per note (its
    chunks joined, the same msgkey in two machines' files once)."""

    TYPE = ("CASE WHEN section IN ('memory/resonance','resonance','soul','identity','memory/soul') OR section LIKE 'memory/resonance/%' "
            "OR section LIKE 'soul/%' THEN 'principle' WHEN section IN ('memory/retrospectives','retrospectives','retros') "
            "OR section LIKE 'memory/retrospectives/%' OR section LIKE 'retrospectives/%' THEN 'retro' ELSE 'learning' END")

    HEAD = 600   # characters of each note kept in memory for lists and search; the whole note is read on open

    def __init__(self, relic: Any) -> None:
        self.relic, self.lock = relic, threading.Lock()
        self.sig: Any = None

    def files(self) -> list[str]:
        import os
        from . import store as rfs
        return sorted(rfs.glob(os.path.join(self.relic.parts.root, "parts", "*", "vault", "notes.parquet")))

    def src(self) -> str | None:
        files = self.files()
        if not files:
            return None
        lst = ", ".join("'" + f.replace("'", "''") + "'" for f in files)
        return f"""(SELECT msgkey, any_value(title) AS title, any_value(path) AS path, any_value(section) AS section,
                          any_value(cat) AS cat, any_value(vault) AS vault, max(ts) AS ts,
                          string_agg(text, '' ORDER BY chunk) AS text
                   FROM (SELECT DISTINCT msgkey, chunk, title, path, section, cat, vault, ts, text
                         FROM read_parquet([{lst}], union_by_name = true))
                   GROUP BY msgkey)"""

    def table(self) -> bool:
        """arra_notes in the hub's DuckDB: each note's fields and its first HEAD characters, remade when a machine
        pushes a new notes.parquet (3 s on white for 175 k notes; reading the parquet every call cost 2-5 s)."""
        from . import store as rfs
        files = self.files()
        if not files:
            return False
        sig = tuple((f, rfs.getsize(f), rfs.getmtime(f)) for f in files)
        with self.lock:
            if sig != self.sig:
                self.relic.con.cursor().execute(f"""CREATE OR REPLACE TABLE arra_notes AS SELECT msgkey, title, path, section, cat,
                    vault, ts, {self.TYPE} AS type, left(text, {self.HEAD}) AS text FROM {self.src()}""")
                self.sig = sig
        return True

    def rows(self, where: str = "TRUE", params: list[Any] | None = None, order: str = "ts DESC", limit: int = 20, offset: int = 0) -> list[Json]:
        if not self.table():
            return []
        out: list[Json] = self.relic._rows(f"SELECT * FROM arra_notes WHERE {where} ORDER BY {order} LIMIT ? OFFSET ?",
                                           (params or []) + [limit, offset])
        return out

    def full(self, where: str, params: list[Any]) -> Json | None:
        """One note whole (its chunks joined), from the parquet."""
        s = self.src()
        got: list[Json] = self.relic._rows(f"SELECT *, {self.TYPE} AS type FROM {s} WHERE {where} LIMIT 1", params) if s else []
        return got[0] if got else None

    def counts(self) -> dict[str, int]:
        if not self.table():
            return {}
        return {str(r["type"]): int(r["n"]) for r in self.relic._rows("SELECT type, count(*) AS n FROM arra_notes GROUP BY 1")}


def note(r: Json) -> Json:
    """A ψ note as Studio's Document."""
    return {"id": r["msgkey"], "type": r.get("type") or "learning", "content": r.get("text") or "",
            "source_file": r.get("path") or "", "project": r.get("cat"), "created_at": r.get("ts"),
            "concepts": [c for c in (r.get("section"), r.get("cat"), r.get("vault")) if c],
            **({"score": r["score"], "source": "fts"} if r.get("score") is not None else {})}


def router(relic: Any, status: Any, oracles: Any, version: str) -> APIRouter:
    r = APIRouter(prefix="/arra/api")
    sample = Sample()
    notes = Notes(relic)
    from . import swr

    def counts() -> dict[str, int]:
        c: dict[str, int] = swr.get("arra-note-counts", 300, notes.counts)
        return c
    readonly = {"success": False, "error": "relic5 is read-only here: it records sessions, it does not take notes"}

    @r.get("/health")
    def health() -> Json:
        return {"status": "ok", "server": "relic5", "version": version}

    @r.get("/stats")
    def stats() -> Json:
        s = status()
        rows = s.get("rows") or {}
        c = counts()
        built = (s.get("freshness") or {}).get("index_built")
        return {"total": sum(c.values()), "by_type": c,
                "last_indexed": built, "is_stale": bool(s.get("warnings")), "vault_repo": "relic5",
                "vector": {"enabled": True, "count": (s.get("rows") or {}).get("text", 0), "collection": "relic5"},
                "sessions": rows.get("sessions", 0)}

    @r.get("/search")
    def search(q: str = "", type: str = "all", limit: int = 20, mode: str = "hybrid", model: str = "") -> Json:
        if not q.strip():
            return {"results": [], "total": 0, "query": q}
        words = [w for w in q.split() if w][:6]
        cond = " AND ".join("(title ILIKE ? OR text ILIKE ?)" for _ in words)
        params: list[Any] = [x for w in words for x in (f"%{w}%", f"%{w}%")]
        if type != "all":
            cond += " AND type = ?"
            params.append(type)
        got = notes.rows(cond, params, limit=max(1, min(limit, 100)))   # newest first: no ranking over ILIKE
        docs = [note(x) for x in got]
        return {"results": docs, "total": len(docs), "query": q, "mode": "fts",
                **({"warning": "relic5 searches by keyword here; semantic search needs the query embedded by a client"}
                   if mode != "fts" else {})}

    @r.get("/list")
    def list_(type: str = "all", limit: int = 20, offset: int = 0) -> Json:
        c = counts()
        where, params = ("TRUE", []) if type == "all" else ("type = ?", [type])
        got = notes.rows(where, params, limit=max(1, min(limit, 200)), offset=max(0, offset))
        return {"results": [note(x) for x in got], "total": sum(c.values()) if type == "all" else c.get(type, 0)}

    @r.get("/doc/{ident}")
    def get_doc(ident: str) -> Json:
        whole = notes.full("msgkey = ?", [ident])
        if whole:
            return note(whole)
        t = relic.show(ident.split(":")[0])["target"]
        return doc(t | {"uid": ident})

    @r.get("/similar")
    def similar(id: str, limit: int = 5) -> Json:
        import numpy as np
        from . import vec as V
        for m in (relic.index.matrices(V.DEFAULT) if relic.index.built() else []):
            hit = np.nonzero(m.cols["uid"] == id)[0]
            if len(hit):
                got = relic.index.vector(V.DEFAULT, m.M[hit[0]].tolist(), {"min_chars": 80}, max(1, min(limit, 50)) + 1)
                return {"results": [doc(x) for x in got if x.get("uid") != id][:limit], "docId": id}
        return {"results": [], "docId": id}

    @r.get("/map")
    def map2d() -> Json:
        d = sample.get(relic)
        return {"documents": [{k: v for k, v in x.items() if k != "z"} for x in d["docs"]], "total": len(d["docs"])}

    @r.get("/map3d")
    def map3d(model: str = "") -> Json:
        d = sample.get(relic)
        return {"documents": d["docs"], "total": len(d["docs"]), "pca_info": d.get("pca")}

    @r.get("/graph")
    def graph() -> Json:
        d = sample.get(relic)
        return {"nodes": [{"id": x["id"], "type": x["type"], "label": (x["content"] or "")[:80], "concepts": x["concepts"]}
                          for x in d.get("graph", [])], "links": d["links"]}

    @r.get("/oracles")
    def oracles_() -> Json:
        o = oracles().get("oracles") or []
        ids = [{"oracle_name": x["name"], "source": x.get("path", ""), "last_seen": x.get("newest") or 0, "actions": x.get("notes", 0)} for x in o]
        projects = [{"project": x["name"], "docs": x.get("notes", 0), "types": len(x.get("sections") or {}),
                     "last_indexed": x.get("newest") or 0} for x in o]
        return {"identities": ids, "projects": projects, "total_projects": len(projects), "total_identities": len(ids)}

    @r.get("/feed")
    def feed(limit: int = 50, oracle: str = "", event: str = "", since: str = "") -> Json:
        rows = relic.tail(max(1, min(limit, 500)), since=since or None)["rows"]
        ev = [{"timestamp": x.get("ts"), "oracle": x.get("cat") or "", "host": (x.get("machines") or [""])[0],
               "event": x.get("role") or "", "project": x.get("session_name") or x.get("cat") or "", "session_id": x.get("sid") or "",
               "message": (x.get("text") or "")[:400]} for x in rows]
        ev = [e for e in ev if (not oracle or e["oracle"] == oracle) and (not event or e["event"] == event)]
        return {"events": ev, "total": len(ev), "active_oracles": sorted({e["oracle"] for e in ev if e["oracle"]})}

    @r.get("/reflect")
    def reflect() -> Json:
        rows = [x for x in relic.tail(200)["rows"] if x.get("role") == "assistant" and len(x.get("text") or "") > 160]
        return doc(random.choice(rows)) if rows else {"id": "", "type": "learning", "content": "", "source_file": "", "concepts": []}

    @r.get("/dashboard/summary")
    def summary() -> Json:
        st = stats()
        top = [(str(x["cat"]), int(x["n"])) for x in relic._rows("SELECT cat, count(*) AS n FROM arra_notes GROUP BY 1 ORDER BY 2 DESC LIMIT 12")] \
            if notes.table() else []
        from . import trace
        lo = since(7)
        s7 = sum(1 for x in trace.rows(relic.parts.root) if x.get("tool") == "relic_search" and str(x.get("at") or "") >= lo)
        l7 = int(relic._rows("SELECT count(*) AS n FROM arra_notes WHERE ts >= ? AND type = 'learning'", [lo])[0]["n"]) if notes.table() else 0
        return {"documents": {"total": st["total"], "by_type": st["by_type"]},
                "concepts": {"total": len(top), "top": [{"name": n, "count": c} for n, c in top]},
                "activity": {"searches_7d": s7, "learnings_7d": l7},
                "health": {"fts_status": "ok" if not st["is_stale"] else "warning", "last_indexed": st["last_indexed"]}}

    def since(days: int) -> str:
        return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - days * 86400))

    @r.get("/dashboard/activity")
    def activity(days: int = 7) -> Json:
        """Searches = relic5's query log (every client: Claude Code, claude.ai, ChatGPT, the hub); learnings = the newest
        notes in a learnings section."""
        from . import trace
        lo = since(max(1, min(days, 90)))
        q = [x for x in trace.rows(relic.parts.root) if x.get("tool") == "relic_search" and str(x.get("at") or "") >= lo]
        q.sort(key=lambda x: str(x.get("at") or ""), reverse=True)
        learn = notes.rows("section LIKE '%learnings%' AND ts >= ?", [lo], limit=30)
        return {"searches": [{"query": x.get("query") or "", "type": x.get("mode") or "keyword", "results_count": x.get("hits") or 0,
                              "search_time_ms": x.get("ms") or 0, "created_at": x.get("at")} for x in q[:50]],
                "learnings": [{"document_id": x["msgkey"], "pattern_preview": (x.get("title") or x.get("text") or "")[:120],
                               "source": x.get("cat") or "", "concepts": [x.get("section") or ""], "created_at": x.get("ts")} for x in learn],
                "days": days}

    @r.get("/dashboard/growth")
    def growth(period: str = "week") -> Json:
        """Per day: notes written (by their time) and searches asked."""
        from . import trace
        days = {"week": 7, "month": 30, "quarter": 90}.get(period, 7)
        lo = since(days)
        docs = {str(x["d"]): int(x["n"]) for x in relic._rows("SELECT left(ts, 10) AS d, count(*) AS n FROM arra_notes WHERE ts >= ? GROUP BY 1", [lo])} \
            if notes.table() else {}
        sq = Counter(str(x.get("at") or "")[:10] for x in trace.rows(relic.parts.root) if x.get("tool") == "relic_search" and str(x.get("at") or "") >= lo)
        return {"period": period, "days": days, "data": [{"date": d, "documents": docs.get(d, 0), "searches": sq.get(d, 0)}
                                                         for d in sorted(set(docs) | set(sq)) if d]}

    @r.get("/file", response_model=None)
    def file(path: str, project: str = "") -> PlainTextResponse:
        """A note (source_file is its path) as its markdown; else a session (by id) as plain text, its messages in order."""
        whole = notes.full("path = ?", [path])
        if whole:
            return PlainTextResponse(whole.get("text") or "", media_type="text/markdown; charset=utf-8")
        rows = relic.tail(500, session=path)["rows"]
        rows.sort(key=lambda x: x.get("ts") or "")
        return PlainTextResponse("\n\n".join(f"[{(x.get('ts') or '')[:19]}] {x.get('role')}: {x.get('text') or ''}" for x in rows)
                                 or f"no messages for {path}", status_code=200 if rows else 404)

    def ms(ts: Any) -> int:
        import datetime as dt
        try:
            return int(dt.datetime.fromisoformat(str(ts).replace("Z", "+00:00")).timestamp() * 1000)
        except ValueError:
            return 0

    @r.get("/session/stats")
    def session_stats(since: int = 0) -> Json:
        """The header's counters since this browser opened Studio: searches over the whole hub (the query log)."""
        from . import trace
        lo = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(since / 1000)) if since else None
        n = sum(1 for x in trace.rows(relic.parts.root) if x.get("tool") == "relic_search" and (not lo or str(x.get("at") or "") >= lo))
        return {"searches": n, "learnings": 0}

    @r.get("/sessions")
    def sessions_() -> Json:
        got = relic.sessions(limit=50).get("sessions") or []
        return {"sessions": [{"id": x["uuid"], "oracle": x.get("tenant") or x.get("name") or "", "last_seen": x.get("endedAt"),
                              "thread_count": x.get("children") or 0, "learning_count": x.get("events") or 0, "trace_count": 0,
                              "name": x.get("name")} for x in got]}

    @r.get("/session/{sid}/context")
    def session_context(sid: str) -> Json:
        s = relic.session(sid)
        rows = [x for x in relic.tail(300, session=sid)["rows"] if x.get("role") == "user"]
        rows.sort(key=lambda x: x.get("ts") or "")
        meta = s.get("session") or s
        return {"id": sid, "oracle": meta.get("cat") or meta.get("tenant") or meta.get("name"),
                "threads": [{"id": x.get("msgkey"), "title": (x.get("text") or "")[:80], "message": x.get("text") or "",
                             "timestamp": x.get("ts")} for x in rows[:40]],
                "learnings": [], "traces": []}

    def trace_summary(c: Json) -> Json:
        return {"traceId": c["root"], "query": c.get("query") or c.get("goal") or "", "depth": max(0, int(c.get("steps") or 1) - 1),
                "fileCount": int(c.get("opened") or 0), "commitCount": 0, "issueCount": 0,
                "status": "distilled" if c.get("found") else "raw", "hasAwakening": bool(c.get("found")),
                "createdAt": ms(c.get("first")), "parentTraceId": None, "prevTraceId": None, "nextTraceId": None,
                "clients": c.get("clients")}

    @r.get("/traces")
    def traces(limit: int = 50, offset: int = 0, status: str = "all", query: str = "") -> Json:
        """relic5's question chains (the query log: a search, the hits it opened, the relic_found at the end)."""
        from . import trace
        got = [trace_summary(c) for c in trace.chains(relic.parts.root, 200)]
        if status != "all":
            got = [t for t in got if t["status"] == status]
        if query:
            got = [t for t in got if query.lower() in t["query"].lower()]
        page = got[max(0, offset):max(0, offset) + max(1, min(limit, 200))]
        return {"traces": page, "total": len(got), "hasMore": offset + len(page) < len(got)}

    @r.get("/traces/{tid}", response_model=None)
    def trace_detail(tid: str) -> Response:
        from . import trace
        c = trace.chain(relic.parts.root, tid)
        if "error" in c:
            return JSONResponse({"error": c["error"]}, status_code=404)
        steps = c.get("steps") or []
        hits = [h for st in steps for h in (st.get("top") or [])]
        found = c.get("found") or []
        return JSONResponse({"traceId": c["root"], "query": steps[0].get("query") if steps else "", "queryType": steps[0].get("tool") if steps else "",
                "project": None, "foundFiles": [{"path": h.get("link") or "", "type": h.get("role"), "matchReason": h.get("repo")} for h in hits[:40]],
                "foundCommits": [], "foundIssues": [], "foundRetrospectives": [], "foundLearnings": [f.get("found") or "" for f in found if f.get("found")],
                "fileCount": int(c.get("opened") or 0), "commitCount": 0, "issueCount": 0, "depth": max((st.get("depth") or 0) for st in steps) if steps else 0,
                "parentTraceId": None, "childTraceIds": [], "prevTraceId": None, "nextTraceId": None,
                "status": "distilled" if found else "raw", "awakening": (found[-1].get("found") if found else None), "createdAt": ms(c.get("first")),
                "steps": steps})

    @r.get("/traces/{tid}/linked-chain")
    def linked_chain(tid: str) -> Json:
        return {"chain": [], "position": 0}

    @r.get("/inbox")
    def inbox(limit: int = 50) -> Json:
        """Handoff notes: the vaults' inbox/handoff notes, newest first."""
        got = notes.rows("section LIKE 'inbox/handoff%' OR section LIKE '%/handoff%'", [], limit=max(1, min(limit, 200)))
        return {"files": [{"filename": (x.get("path") or "").rsplit("/", 1)[-1], "path": x.get("path") or "", "created": x.get("ts"),
                           "preview": (x.get("text") or "")[:300], "type": x.get("cat") or "handoff"} for x in got], "total": len(got)}

    @r.get("/supersede")
    def supersede(limit: int = 50, offset: int = 0) -> Json:
        return {"supersessions": [], "total": 0}

    @r.get("/auth/status")
    def auth_status() -> Json:
        return {"authenticated": True, "authEnabled": False, "hasPassword": False, "localBypass": True, "isLocal": True}

    @r.get("/settings")
    def settings() -> Json:
        return {"authEnabled": False, "localBypass": True, "hasPassword": False, "vaultRepo": None}

    @r.get("/plugins")
    def plugins() -> Json:
        return {"plugins": []}

    @r.post("/learn", response_model=None)
    @r.post("/settings", response_model=None)
    @r.post("/auth/login", response_model=None)
    @r.post("/auth/logout", response_model=None)
    def writes() -> JSONResponse:
        return JSONResponse(readonly, status_code=403)

    return r
