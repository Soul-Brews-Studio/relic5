"""arra.py: ARRA Oracle Studio (studio.buildwithoracle.com, ui-oracle apps/studio) reading relic5 (Nat, 2026-10-25: "can we
make https://studio.buildwithoracle.com/ support? the ui?" -> "Studio reads relic5", "can go tailscale serve https! and
can we make like adaptor").

Studio speaks the arra-oracle API (ui-oracle apps/studio/src/api/oracle.ts): a knowledge base of documents typed
principle | learning | retro, with concepts. This router answers that API under /arra/api from relic5's history:

  document      a message (uid), its text, its session as source_file, its repo as project
  type          principle = an agent's memory note (role memory-*), retro = text mentioning a retrospective/rrr,
                learning = every other message
  concepts      [role, cat (the oracle / repo), machine]
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
from fastapi.responses import JSONResponse, PlainTextResponse

from .types_ import Json

ORIGINS = ("https://studio.buildwithoracle.com",)
LOCAL_ORIGIN = re.compile(r"^http://(localhost|127\.0\.0\.1)(:\d+)?$")   # Studio's own dev server
SAMPLE = 3000
_RETRO = re.compile(r"\b(retro|retrospective|/rrr)\b", re.I)


def cors(origin: str | None) -> dict[str, str]:
    """The headers that let Studio's page (another origin, public HTTPS) read the hub on the tailnet."""
    if not origin or not (origin in ORIGINS or LOCAL_ORIGIN.match(origin)):
        return {}
    return {"Access-Control-Allow-Origin": origin, "Vary": "Origin", "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
            "Access-Control-Allow-Headers": "Content-Type", "Access-Control-Allow-Private-Network": "true",
            "Access-Control-Max-Age": "600"}


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
            S = X @ X.T
            np.fill_diagonal(S, -1)
            nn = np.argsort(-S, axis=1)[:, :2]
            docs = [doc(r) | {"x": float(p[0]), "y": float(p[1]), "z": float(p[2]), "chunk_ids": [r["uid"]]} for r, p in zip(rows, P)]
            links = {tuple(sorted((docs[a]["id"], docs[int(b)]["id"]))) for a in range(len(docs)) for b in nn[a]}
            var = (sv[:3] ** 2) / float((sv ** 2).sum() or 1)
            out: Json = {"docs": docs, "links": [{"source": s, "target": t} for s, t in links],
                         "pca": {"components": 3, "explained_variance": [round(float(v), 4) for v in var], "sample": len(docs),
                                 "model": V.DEFAULT, "of": total}}
            self.data, self.seen = out, getattr(idx, "seen", None)
            return out


def router(relic: Any, status: Any, oracles: Any, version: str) -> APIRouter:
    r = APIRouter(prefix="/arra/api")
    sample = Sample()
    readonly = {"success": False, "error": "relic5 is read-only here: it records sessions, it does not take notes"}

    @r.get("/health")
    def health() -> Json:
        return {"status": "ok", "server": "relic5", "version": version}

    @r.get("/stats")
    def stats() -> Json:
        s, o = status(), oracles()
        rows = s.get("rows") or {}
        ors = o.get("oracles") or []
        built = (s.get("freshness") or {}).get("index_built")
        return {"total": rows.get("text", 0), "by_type": {"learning": rows.get("text", 0),
                                                           "principle": sum(x.get("soul", 0) for x in ors),
                                                           "retro": sum(x.get("retros", 0) for x in ors)},
                "last_indexed": built, "is_stale": bool(s.get("warnings")), "vault_repo": "relic5",
                "vector": {"enabled": True, "count": (s.get("rows") or {}).get("text", 0), "collection": "relic5"},
                "sessions": rows.get("sessions", 0)}

    @r.get("/search")
    def search(q: str = "", type: str = "all", limit: int = 20, mode: str = "hybrid", model: str = "") -> Json:
        if not q.strip():
            return {"results": [], "total": 0, "query": q}
        hits = relic.search(q, limit=max(1, min(limit, 100)), with_="memory" if type == "principle" else None)["hits"]
        docs = [doc(h) for h in hits]
        if type in ("learning", "retro"):
            docs = [d for d in docs if d["type"] == type]
        return {"results": docs, "total": len(docs), "query": q, "mode": "fts",
                **({"warning": "relic5 searches by keyword here; semantic search needs the query embedded by a client"}
                   if mode != "fts" else {})}

    @r.get("/list")
    def list_(type: str = "all", limit: int = 20, offset: int = 0) -> Json:
        n = max(1, min(limit, 200)) + max(0, offset)
        rows = relic.tail(min(n, 500))["rows"][max(0, offset):]
        docs = [doc(x) for x in rows]
        if type != "all":
            docs = [d for d in docs if d["type"] == type]
        return {"results": docs[:limit], "total": len(docs)}

    @r.get("/doc/{ident}")
    def get_doc(ident: str) -> Json:
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
                          for x in d["docs"]], "links": d["links"]}

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
        top = Counter(c for x in sample.get(relic)["docs"] for c in x["concepts"][1:2]).most_common(12)
        q = (status().get("queries") or {})
        return {"documents": {"total": st["total"], "by_type": st["by_type"]},
                "concepts": {"total": len(top), "top": [{"name": n, "count": c} for n, c in top]},
                "activity": {"searches_7d": q.get("searches_7d") or q.get("count") or 0, "learnings_7d": 0},
                "health": {"fts_status": "ok" if not st["is_stale"] else "warning", "last_indexed": st["last_indexed"]}}

    @r.get("/dashboard/activity")
    def activity(days: int = 7) -> Json:
        return {"searches": [], "learnings": [], "days": days}

    @r.get("/dashboard/growth")
    def growth(period: str = "week") -> Json:
        days = {"week": 7, "month": 30, "quarter": 90}.get(period, 7)
        c = Counter((x.get("ts") or "")[:10] for x in relic.tail(500, since=f"{days}d")["rows"])
        return {"period": period, "days": days, "data": [{"date": d, "documents": n, "searches": 0} for d, n in sorted(c.items()) if d]}

    @r.get("/file", response_model=None)
    def file(path: str, project: str = "") -> PlainTextResponse:
        """A session (source_file is its id) as plain text: its messages in order."""
        rows = relic.tail(500, session=path)["rows"]
        rows.sort(key=lambda x: x.get("ts") or "")
        return PlainTextResponse("\n\n".join(f"[{(x.get('ts') or '')[:19]}] {x.get('role')}: {x.get('text') or ''}" for x in rows)
                                 or f"no messages for {path}", status_code=200 if rows else 404)

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
