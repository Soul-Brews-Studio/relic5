"""search.py: relic_search over the BM25 index (fts.py), ported from agent-relic-v3 src/search/query.ts, horizon.ts,
fold.ts @9f0bdb5.

  widening   with no horizon / since / until / session, try 7d, 15d, 1m, 3m, archive and answer from the narrowest
             window holding at least min(10, limit) folded hits (query.ts:298-325); the cursor pins that horizon.
             Then the best hits older than that window follow (issue #19): recent first, never only recent
  fold       a hit whose (ts, role, text with whitespace collapsed) was already seen is dropped, the first kept
             (fold.ts:37-58), and so is a second chunk text (same key) - before counting, widening and paging
  order      prose before tools / thinking (query.ts:317-319); within a layer BM25 score desc, then newest, then uid
  fetch      over-fetch want * 1.5 + 8 rows, growing x4 while the fold eats them (query.ts:158-168)
"""
import base64, hashlib, json, re
from collections.abc import Sequence
from typing import TYPE_CHECKING, Any

from .types_ import Json
from .window import HORIZONS, window

if TYPE_CHECKING:   # for annotations only: query.py imports this module
    from .fts import Index
    from .query import Relic5
    from .vec import VecFilter

WIDEN = ["7d", "15d", "1m", "3m", "archive"]
# Paths a temp janitor deletes (agent-relic-v3 src/search/ephemeral.ts): a hit that names one may point at nothing now.
EPHEMERAL = re.compile(r"(?:/private)?/tmp/\S+|/var/folders/\S+|\bscratchpad/\S*|claude-\d+/\S*")
CAP = 8192


def q_(v: object) -> str:
    return "'" + str(v).replace("'", "''") + "'"


def snippet(text: str, words: list[str], width: int = 240) -> str:
    low = text.lower()
    at = min((i for i in (low.find(w.lower()) for w in words) if i >= 0), default=0)
    s = max(0, at - width // 3)
    return ("…" if s else "") + " ".join(text[s:s + width].split()) + ("…" if s + width < len(text) else "")


def fold(rows: list[Json], seen: set[tuple[object, ...]]) -> list[Json]:
    out: list[Json] = []
    for r in rows:
        k = (r["ts"], r["role"], " ".join((r["text"] or "").split()))
        if k in seen or ("key", r["key"]) in seen:
            continue
        seen.add(k)
        seen.add(("key", r["key"]))
        out.append(r)
    return out


# Near-duplicates (issue #25): a templated prompt sent once per worktree differs only in its paths, ids, numbers and a
# branch name, and filled 8 of a semantic top 10. Two hits are one when their word 3-grams overlap >= NEAR (Jaccard),
# compared on the first 800 characters after lowercasing and replacing paths, hex ids and numbers. Claude Code's
# mid-turn wrapper is removed first, or two different short messages would match on the wrapper alone.
_VARYING = re.compile(r"(?:~|\.{0,2})?(?:/[\w.@%+-]+)+/?|\b[0-9a-f]{7,}\b|\d+")
_WRAPPER = re.compile(r"the user sent a new message while you were working:|this is how claude code surfaces messages the user "
                      r"sends mid-turn.*?(?:conversation turn\.|$)|address the message above as you continue this turn\.")
NEAR = 0.8


def near_key(r: Json) -> str:
    t = " ".join((r.get("text") or "").lower().split())
    return _VARYING.sub("#", _WRAPPER.sub(" ", t))[:800]


def _shingles(t: str) -> set[tuple[str, ...]]:
    w = t.split()
    return {tuple(w[i:i + 3]) for i in range(max(1, len(w) - 2))}


def collapse(rows: list[Json]) -> list[Json]:
    """Keep the first (best) hit of each near-duplicate group; it carries _dups = how many it stands for."""
    kept: list[tuple[set[tuple[str, ...]], Json]] = []
    for r in rows:
        sh = _shingles(near_key(r))
        for ksh, k in kept:
            if sh and ksh and len(sh & ksh) / len(sh | ksh) >= NEAR:
                k["_dups"] = k.get("_dups", 0) + 1
                break
        else:
            kept.append((sh, r))
    return [k for _, k in kept]


def vector_hits(index: "Index", slug: str, vector: Sequence[float], vf: "VecFilter", want: int) -> list[Json]:
    """Semantic hits, folded and collapsed; fetches more while the collapse thins the page."""
    k = int(want * 1.5) + 8
    while True:
        raw = index.vector(slug, vector, vf, k)
        got = collapse(fold(raw, set()))
        if len(got) >= want or len(raw) < k or k >= CAP:
            return got
        k = min(k * 4, CAP)


def run(index: "Index", query: str, layers: list[str], where: str | None, want: int) -> list[Json]:
    """Folded hits of every layer, prose first; fetches more while the fold drops rows."""
    seen: set[tuple[object, ...]] = set()
    out: list[Json] = []
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


def pick_model(index: "Index", model: str | None) -> str:
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


def search(relic: "Relic5", index: "Index", query: str, since: str | None = None, until: str | None = None,
           horizon: str | None = None, repo: str | None = None, session: str | None = None, role: str | None = None,
           tier: str | None = None, with_: str | None = None, limit: int = 20, cursor: str | None = None,
           vector: Sequence[float] | None = None, model: str | None = None, hybrid: bool = False, sort: str | None = None,
           min_chars: int | None = None, cwd: str | None = None, branch: str | None = None, title: str | None = None,
           via: str | None = None, chat: str | None = None, from_user: str | None = None) -> Json:
    from .query import UsageError, like, repo_pattern
    if sort not in (None, "", "relevant", "newest"):
        raise UsageError("sort is relevant | newest")
    words = query.split()
    if with_ == "memory":   # the memory notes alone: rules, decisions, references (memory.py); not mixed with talk
        layers = ["memory"]
    else:
        layers = ["prose"] + ([w for w in (with_ or "").split(",") if w] if with_ != "all" else ["tools", "thinking", "memory"])
    layers = ["prose" if l == "vault" else l for l in layers]
    layers = list(dict.fromkeys(layers))
    for l in layers:
        if l not in ("prose", "tools", "thinking", "memory"):
            raise UsageError(f"with {l}: one of tools, thinking, vault, memory, all")
    try:
        lo, hi, _ = window(since, until, None)
    except ValueError as ex:
        raise UsageError(str(ex))
    if horizon and (since or until):
        raise UsageError("horizon and since/until each set the window - pick one.")
    if horizon and horizon not in HORIZONS:
        raise UsageError(f"horizon {horizon}: one of {' | '.join(HORIZONS)}")
    conds: list[str] = []
    filt: "VecFilter" = {"hi": hi, "role": role, "sid_prefix": session}
    if min_chars is not None:
        filt["min_chars"] = min_chars
    for c, v in (("ts <= {}", hi), ("role = {}", role)):
        if v:
            conds.append(c.format(q_(v)))
    if session:
        conds.append(f"sid LIKE {q_(session.replace('%', '') + '%')}")
    if cwd and not relic.meta_has("cwd"):
        raise UsageError("cwd is not in the index yet (needs relic-scan >= PR #37 on every machine)")
    channel: dict[str, str | None] = {"via": via, "chat": chat, "from_user": from_user}   # relic3 --via/--chat/--from-user: session-level substrings
    for col, v in (("branch", branch), ("title", title), *channel.items()):
        if v and not relic.meta_has(col):
            raise UsageError(f"{col} is not in the index yet (needs a newer relic-scan meta on some machine)")
    if repo or tier or cwd or branch or title or any(channel.values()):
        meta = relic._meta()
        if not meta:
            raise UsageError("repo/tier need relic-scan's meta/sessions.parquet on the hub (push it)")
        sub: list[str] = []
        sp: list[str] = []
        if repo:
            sub.append("proj ILIKE ? ESCAPE '\\'")
            sp.append(repo_pattern(repo))
        if tier:
            sub.append("tier = ?")
            sp.append(tier)
        if cwd:   # sessions that ran in PATH or below it (relic3 --cwd)
            sub.append("(cwd = ? OR starts_with(cwd, ?))")
            sp += [cwd.rstrip("/"), cwd.rstrip("/") + "/"]
        if branch:
            sub.append("branch = ?")
            sp.append(branch)
        if title:   # a substring of the host's session title, case-blind
            sub.append("title ILIKE ? ESCAPE '\\'")
            sp.append(like(title))
        for col, v in channel.items():   # the session's first channel message: every row of the session matches
            if v:
                sub.append(f"{col} ILIKE ? ESCAPE '\\'")
                sp.append(like(v))
        sids: list[str] = [r["sid"] for r in relic._rows(f"SELECT DISTINCT sid FROM {meta} WHERE {' AND '.join(sub)}", sp)]
        if not sids:
            return {"hits": [], "next_cursor": None, "horizon": horizon or "archive", "horizons_tried": [], "widened": False,
                    "searched_weeks": [], "searched_months": [], "scope_empty": True}
        conds.append("sid IN (" + ",".join(q_(s) for s in sids) + ")")
        filt["sids"] = set(sids)
    sig = hashlib.sha1(json.dumps([query, lo, hi, repo, session, role, tier, with_, sort, cwd, branch, title, via, chat, from_user]).encode()).hexdigest()[:12]
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
    tried: list[str] = []
    hits: list[Json] = []
    chosen: str | None = None
    want = off + limit + 1
    for hz in ([fixed] if fixed else WIDEN):
        start = lo if hz == "window" else window(horizon=hz)[0]
        where = " AND ".join(conds + ([f"ts >= {q_(start)}"] if start else [])) or None
        vf = filt | {"lo": start}
        tried.append(hz)
        if vector is not None and hybrid:   # reciprocal-rank fusion (k = 60) of the BM25 and the vector lists
            k = int(want * 1.5) + 8
            lists = [run(index, query, ["prose"], where, k), vector_hits(index, slug, vector, vf, k)]
            fused: dict[str, list[Any]] = {}   # uid -> [fused score, row]
            for lst in lists:
                for rank, r in enumerate(lst):
                    f = fused.setdefault(r["uid"], [0.0, r])
                    f[0] += 1 / (60 + rank + 1)
            hits = []
            for sc, r in sorted(fused.values(), key=lambda x: -x[0]):
                hits.append(r | {"_score": sc})
            hits = collapse(fold(hits, set()))
        elif vector is not None:
            hits = vector_hits(index, slug, vector, vf, want)
        else:
            hits = run(index, query, layers, where, want)
        chosen = hz
        if fixed or len(hits) >= min(10, limit):
            break
    # Widening stops at the first window with min(10, limit) hits, and a hit count is not relevance: "trinity" found 10
    # in October and never reached the August and September sessions Nat meant (issue #19). So when no window was asked
    # for and widening stopped short of archive, everything older is searched too and its best hits follow the window's.
    # The page cursor pins `chosen`; this runs again on every page, so paging is stable.
    older = 0
    note = None
    if vector is None and not horizon and not (lo or hi or session) and chosen not in (None, "archive", "window"):
        cut = window(horizon=chosen)[0]
        if cut:
            old_where = " AND ".join(conds + [f"ts < {q_(cut)}"])
            seen: set[tuple[object, ...]] = {(r["ts"], r["role"], " ".join((r["text"] or "").split())) for r in hits} | {("key", r["key"]) for r in hits}
            more_hits = fold(run(index, query, layers, old_where, want), seen)
            older = len(more_hits)
            hits = hits + more_hits
            note = (f"{len(hits) - older} hits in the last {chosen}, then the best {older} older ones" if older
                    else f"nothing older than {chosen} matches")
    if sort == "newest":   # relic3: the most relevant 600, newest first (query.ts:106-107)
        if len(hits) < min(600, off + limit + 1) and vector is None:
            hits = run(index, query, layers, where, 600)
        hits = sorted(hits[:600], key=lambda r: r["ts"] or "", reverse=True)
    page = hits[off:off + limit]
    more = len(hits) > off + limit
    repos = relic._repos({h["sid"] for h in page if h["sid"]})
    names = relic._names({h["sid"] for h in page if h["sid"]})
    out: list[Json] = []
    for r in page:
        out.append({"uid": r["uid"], "partition": r["month"], "session_uuid": r["sid"], "role": r["role"], "ts": r["ts"],
                    "day": (r["ts_th"] or "")[:10] or None, "repo_key": repos.get(r["sid"]),
                    "session_name": names.get(r["sid"]), "text_snippet": snippet(r["text"] or "", words), "score": round(float(r["_score"]), 4),
                    "layer": r["layer"], "source_present": False,
                    "ephemeral": sorted(set(EPHEMERAL.findall(r["text"] or "")))[:5] or None, "machines": r["machines"], "title": r.get("title"),
                    "link": f"relic5://{r['month']}/{r['uid']}",
                    "locator": {"month": r["month"], "stream": r["layer"], "key": r["key"], "chunk": r["chunk"]}}
                   | ({"near_duplicates": r["_dups"]} if r.get("_dups") else {}))
    nxt = base64.urlsafe_b64encode(json.dumps({"o": off + limit, "q": sig, "h": chosen}).encode()).decode().rstrip("=") if more else None
    months = sorted({h["month"] for h in hits if h.get("month")})
    extra: Json = {"semantic": True, "model": slug, "hybrid": bool(hybrid)} if vector is not None else {}
    return {**extra, "hits": out, "next_cursor": nxt, "horizon": chosen, "horizons_tried": tried, "widened": len(tried) > 1,
            "searched_weeks": months, "searched_months": months, "older_hits": older, "note": note,
            "collapsed": sum(h.get("near_duplicates", 0) for h in out), "freshness": freshness(index.root)}


def freshness(root: str) -> Json:
    """How current a result is (issue #25): when the published BM25 generation was built, when vectors were last
    published, and how many messages still wait for one. Cheap: two small files, no scan."""
    import os
    from datetime import datetime, timezone
    from .fts import search_dir
    sd = search_dir(root)
    cur = os.path.join(sd, "current.json")
    built = datetime.fromtimestamp(os.path.getmtime(cur), timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ") if os.path.exists(cur) else None
    vp = os.path.join(sd, "vectors.json")
    try:
        vs = json.load(open(vp))
        pending: int | None = sum(int(v["pending"]) for w in vs.get("models", {}).values() for v in w.values())
        vat = vs.get("at")
    except (OSError, ValueError, KeyError):
        pending, vat = None, None
    return {"index_built": built, "vectors_at": vat, "vectors_pending": pending}
