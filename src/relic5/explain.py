"""explain.py: how the hub reads a search (Nat, 2026-10-25: "search query this page can we show like how we tokenize?").

  tokens   the query as the BM25 index sees it: lance's ICU tokenizer with the index's own settings (fts.tokens), so
           Thai splits into words and case is folded
  terms    per token: in how many rows of the searched layers it appears (counted up to CAP), and its BM25 weight,
           idf = ln(1 + (N - df + 0.5) / (df + 0.5)), so a rare word counts for more than a common one
  phrase   a query of two or more words also runs as an exact phrase first (fts.Index.query): how many rows have it

Cached per (query, layers, index generation): the same search asked twice costs nothing the second time.
"""
import math
import time

from .fts import tokens
from .types_ import Json

CAP = 20_000
_cache: dict[tuple[str, str, object], Json] = {}


def explain(relic: object, q: str, with_: str | None = None) -> Json:
    from .query import UsageError
    index = getattr(relic, "index")
    if not q or not q.strip():
        raise UsageError("explain needs a query")
    if not index.built():
        raise UsageError("no index published yet")
    layers = [with_] if with_ in ("memory", "git") else ["prose"] + (
        ["tools", "thinking", "memory", "git"] if with_ == "all" else [w for w in (with_ or "").split(",") if w in ("tools", "thinking")])
    index._load()   # the generation now, so the cache never answers from an older index
    key = (q.strip(), ",".join(layers), index.seen)
    if key in _cache:
        return _cache[key]
    t0 = time.time()
    toks = tokens(q)
    n = sum(index.size(l) for l in layers)
    terms: list[Json] = []
    for t in dict.fromkeys(toks):
        df = sum(index.count(l, t, CAP) for l in layers)
        idf = math.log(1 + (n - df + 0.5) / (df + 0.5)) if n else None
        terms.append({"token": t, "rows": df, "capped": df >= CAP, "idf": round(idf, 3) if idf is not None else None})
    phrase = None
    if len(toks) >= 2:
        try:
            phrase = sum(index.count(l, '"' + q.replace('"', " ") + '"', CAP) for l in layers)
        except Exception:   # a table built without positions cannot run a phrase
            phrase = None
    out: Json = {"query": q, "tokens": toks, "layers": layers, "rows": n, "terms": terms, "phrase_rows": phrase,
                 "tokenizer": "lance ICU · lower case · no stemming · no stop words", "ms": round((time.time() - t0) * 1000)}
    if len(_cache) > 256:
        _cache.clear()
    _cache[key] = out
    return out
