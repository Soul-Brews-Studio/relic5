"""search.py: relic_search over the BM25 index (fts.py), ported from agent-relic-v3 src/search/query.ts, horizon.ts,
fold.ts @9f0bdb5.

  widening   with no horizon / since / until / session, try 7d, 15d, 1m, 3m, archive and answer from the narrowest
             window holding at least min(10, limit) folded hits (query.ts:298-325); the cursor pins that horizon
  fold       a hit whose (ts, role, text with whitespace collapsed) was already seen is dropped, the first kept
             (fold.ts:37-58), and so is a second chunk text (same key) - before counting, widening and paging
  order      prose before tools / thinking (query.ts:317-319); within a layer BM25 score desc, then newest, then uid
  fetch      over-fetch want * 1.5 + 8 rows, growing x4 while the fold eats them (query.ts:158-168)
"""
import base64, hashlib, json, re

from .window import HORIZONS, window

WIDEN = ["7d", "15d", "1m", "3m", "archive"]
CAP = 8192


def q_(v):
    return "'" + str(v).replace("'", "''") + "'"


def snippet(text, words, width=240):
    low = text.lower()
    at = min((i for i in (low.find(w.lower()) for w in words) if i >= 0), default=0)
    s = max(0, at - width // 3)
    return ("…" if s else "") + " ".join(text[s:s + width].split()) + ("…" if s + width < len(text) else "")


def fold(rows, seen):
    out = []
    for r in rows:
        k = (r["ts"], r["role"], " ".join((r["text"] or "").split()))
        if k in seen or ("key", r["key"]) in seen:
            continue
        seen.add(k)
        seen.add(("key", r["key"]))
        out.append(r)
    return out


def run(index, query, layers, where, want):
    """Folded hits of every layer, prose first; fetches more while the fold drops rows."""
    seen, out = set(), []
    for layer in layers:
        k = int(want * 1.5) + 8
        while True:
            rows = index.query(layer, query, where, k)
            got = fold(rows, set(seen))
            if len(got) >= want - len(out) or len(rows) < k or k >= CAP:
                break
            k = min(k * 4, CAP)
        got = fold(rows, seen)
        out += got
        if len(out) >= want:
            break
    return out


def pick_model(index, model):
    """A vector table by its model, model@hash or slug; the only one when there is one."""
    from .query import UsageError
    from .vec import slug as slug_of
    have = index.vector_models()
    if not have:
        raise UsageError("no vectors on the hub yet")
    if not model:
        if len(have) > 1:
            raise UsageError(f"several vector tables: pick a model ({', '.join(have)})")
        return have[0]
    want = slug_of(model)
    hit = [h for h in have if h == want or want in h]
    if len(hit) != 1:
        raise UsageError(f"model {model}: " + ("no vectors for it" if not hit else "ambiguous") + f" (have {', '.join(have)})")
    return hit[0]


def search(relic, index, query, since=None, until=None, horizon=None, repo=None, session=None, role=None, tier=None,
           with_=None, limit=20, cursor=None, vector=None, model=None, hybrid=False):
    from .query import UsageError, repo_pattern
    words = query.split()
    layers = ["prose"] + ([w for w in (with_ or "").split(",") if w] if with_ != "all" else ["tools", "thinking"])
    layers = ["prose" if l == "vault" else l for l in layers]
    layers = list(dict.fromkeys(layers))
    for l in layers:
        if l not in ("prose", "tools", "thinking"):
            raise UsageError(f"with {l}: one of tools, thinking, vault, all")
    try:
        lo, hi, _ = window(since, until, None)
    except ValueError as ex:
        raise UsageError(str(ex))
    if horizon and (since or until):
        raise UsageError("horizon and since/until each set the window - pick one.")
    if horizon and horizon not in HORIZONS:
        raise UsageError(f"horizon {horizon}: one of {' | '.join(HORIZONS)}")
    conds = []
    for c, v in (("ts <= {}", hi), ("role = {}", role)):
        if v:
            conds.append(c.format(q_(v)))
    if session:
        conds.append(f"sid LIKE {q_(session.replace('%', '') + '%')}")
    if repo or tier:
        meta = relic._meta()
        if not meta:
            raise UsageError("repo/tier need relic-scan's meta/sessions.parquet on the hub (push it)")
        sub, sp = [], []
        if repo:
            sub.append("proj ILIKE ? ESCAPE '\\'")
            sp.append(repo_pattern(repo))
        if tier:
            sub.append("tier = ?")
            sp.append(tier)
        sids = [r["sid"] for r in relic._rows(f"SELECT DISTINCT sid FROM {meta} WHERE {' AND '.join(sub)}", sp)]
        if not sids:
            return {"hits": [], "next_cursor": None, "horizon": horizon or "archive", "horizons_tried": [], "widened": False,
                    "searched_weeks": [], "searched_months": [], "scope_empty": True}
        conds.append("sid IN (" + ",".join(q_(s) for s in sids) + ")")
    sig = hashlib.sha1(json.dumps([query, lo, hi, repo, session, role, tier, with_]).encode()).hexdigest()[:12]
    off, pinned = 0, None
    if cursor:
        try:
            c = json.loads(base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)))
            off, pinned = int(c["o"]), c.get("h")
            assert c["q"] == sig
        except Exception:
            raise UsageError("bad cursor: it belongs to another query")
    if vector is not None:   # semantic: relic3 does not widen it (semantic.ts:175-178): one window, archive by default
        pinned = pinned or horizon or ("window" if lo or hi or session else "archive")
        slug = pick_model(index, model)
    fixed = pinned or horizon or ("window" if lo or hi or session else None)
    tried, hits, chosen = [], [], None
    want = off + limit + 1
    for hz in ([fixed] if fixed else WIDEN):
        start = lo if hz == "window" else window(horizon=hz)[0]
        where = " AND ".join(conds + ([f"ts >= {q_(start)}"] if start else [])) or None
        tried.append(hz)
        if vector is not None and hybrid:   # reciprocal-rank fusion (k = 60) of the BM25 and the vector lists
            k = int(want * 1.5) + 8
            lists = [run(index, query, ["prose"], where, k), fold(index.vector(slug, vector, where, k), set())]
            fused = {}
            for lst in lists:
                for rank, r in enumerate(lst):
                    f = fused.setdefault(r["uid"], [0.0, r])
                    f[0] += 1 / (60 + rank + 1)
            hits = []
            for sc, r in sorted(fused.values(), key=lambda x: -x[0]):
                hits.append(r | {"_score": sc})
            hits = fold(hits, set())
        elif vector is not None:
            hits = fold(index.vector(slug, vector, where, int(want * 1.5) + 8), set())
        else:
            hits = run(index, query, layers, where, want)
        chosen = hz
        if fixed or len(hits) >= min(10, limit):
            break
    page = hits[off:off + limit]
    more = len(hits) > off + limit
    repos = relic._repos({h["sid"] for h in page if h["sid"]})
    names = relic._names({h["sid"] for h in page if h["sid"]})
    out = []
    for r in page:
        out.append({"uid": r["uid"], "partition": r["month"], "session_uuid": r["sid"], "role": r["role"], "ts": r["ts"],
                    "day": (r["ts_th"] or "")[:10] or None, "repo_key": repos.get(r["sid"]),
                    "session_name": names.get(r["sid"]), "text_snippet": snippet(r["text"] or "", words), "score": round(float(r["_score"]), 4),
                    "layer": r["layer"], "source_present": False, "machines": r["machines"], "title": r.get("title"),
                    "link": f"relic5://{r['month']}/{r['uid']}",
                    "locator": {"month": r["month"], "stream": r["layer"], "key": r["key"], "chunk": r["chunk"]}})
    nxt = base64.urlsafe_b64encode(json.dumps({"o": off + limit, "q": sig, "h": chosen}).encode()).decode().rstrip("=") if more else None
    months = sorted({h["month"] for h in hits if h.get("month")})
    extra = {"semantic": True, "model": slug, "hybrid": bool(hybrid)} if vector is not None else {}
    return {**extra, "hits": out, "next_cursor": nxt, "horizon": chosen, "horizons_tried": tried, "widened": len(tried) > 1,
            "searched_weeks": months, "searched_months": months}
