"""universe.py: the hub's sessions as points in space, for the Map view (Nat, 2026-10-24: "vector 3d interactive
visualization ... and 2d", after lanceglass's Session vector map, Atlas 3D / Flat 2D, 2026-09-01).

One point per session: the mean of its prose chunks' vectors, made unit length, so sessions about the same thing sit
together. Projected by PCA to three axes (the 2D view draws the first two), the same deterministic projection
lanceglass ships as deterministic-pca-3d: no random seed, the same hub gives the same map. Each axis is scaled to
[-1, 1]. One map per index generation and model, kept in memory; a new generation rebuilds it on the next call.

Points carry the session's id, name, repo, newest time, chunk count and machines; the page colours them by repo.
"""
import threading
from typing import TYPE_CHECKING, Any

from .types_ import Json

if TYPE_CHECKING:
    from .query import Relic5

_LOCK = threading.Lock()
_CACHE: dict[tuple[object, ...], Json] = {}
KEEP = 8          # maps kept in memory and on disk (sessions maps of a few limits, the memory map)


def _file(relic: "Relic5", key: tuple[object, ...]) -> str:
    import hashlib, os
    d = os.path.join(relic.parts.root, "index", "_maps")
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, hashlib.sha1(repr(key).encode()).hexdigest()[:16] + ".json")


def _get(relic: "Relic5", key: tuple[object, ...]) -> Json | None:
    """A map already made: in memory, else on disk (a map outlives a restart or a deploy: 41.6 s cold, measured
    2026-10-25 on white, for 3,000 sessions)."""
    import json, os
    with _LOCK:
        if key in _CACHE:
            return _CACHE[key]
    f = _file(relic, key)
    if os.path.exists(f):
        try:
            out: Json = json.load(open(f))
        except (OSError, ValueError):
            return None
        with _LOCK:
            _CACHE[key] = out
        return out
    return None


def _put(relic: "Relic5", key: tuple[object, ...], out: Json) -> None:
    import glob, json, os
    with _LOCK:
        _CACHE[key] = out
        while len(_CACHE) > KEEP:            # the oldest first (dicts keep insertion order)
            _CACHE.pop(next(iter(_CACHE)))
    f = _file(relic, key)
    with open(f + ".tmp", "w") as fh:
        json.dump(out, fh)
    os.replace(f + ".tmp", f)
    old = sorted(glob.glob(os.path.join(os.path.dirname(f), "*.json")), key=os.path.getmtime)[:-KEEP]
    for x in old:
        os.remove(x)


def keep_warm(relic: "Relic5", every: float = 60.0) -> None:
    """Make the maps and the biggest oracles' pages before anyone asks: at start, and again whenever the index gets a new generation (or the
    memory notes change). A background thread; any failure waits for the next round."""
    import threading, time

    def loop() -> None:
        time.sleep(5)
        while True:
            try:
                sessions_map(relic)
                memory_map(relic)
            except Exception:
                pass
            try:   # the biggest oracles' pages too: a first look at one cost 2.0-2.8 s (measured 2026-10-25)
                from . import oracles
                for o in oracles.listing(relic)["oracles"][:12]:
                    oracles.portrait(relic, o["name"])
            except Exception:
                pass
            time.sleep(every)
    threading.Thread(target=loop, name="relic5-maps", daemon=True).start()
MIN_CHUNKS = 3   # a session with one or two embedded lines lands wherever its one sentence points: noise on the map


LIMIT = 3000   # sessions on the Map by default


def sessions_map(relic: "Relic5", model: str | None = None, limit: int = LIMIT, min_chunks: int = MIN_CHUNKS) -> Json:
    """-> {model, sessions, chunks, explained, points: [{sid, x, y, z, n, ts, repo, name, machines}]}, newest
    sessions first up to limit (the projection is fitted on exactly those)."""
    import numpy as np
    from .search import pick_model
    index = relic.index
    slug = pick_model(index, model)
    mats = index.matrices(slug)
    key = ("sessions", index.seen, slug, int(limit), int(min_chunks))
    hit = _get(relic, key)
    if hit is not None:
        return hit
    if not mats:
        return {"model": slug, "sessions": 0, "chunks": 0, "explained": [], "points": []}

    sid = np.concatenate([m.cols["sid"].astype(str) for m in mats])
    ts = np.concatenate([m.cols["ts"].astype(str) for m in mats])
    # group rows by session: one sort by (sid, ts), then each run of rows is one session and its last row the newest
    order = np.lexsort((ts, sid))
    sid_s = sid[order]
    starts = np.flatnonzero(np.r_[True, sid_s[1:] != sid_s[:-1]])
    counts = np.diff(np.r_[starts, len(sid_s)])
    newest = ts[order][starts + counts - 1]
    keep = np.flatnonzero(counts >= min_chunks)
    keep = keep[np.argsort(newest[keep])[::-1][:limit]]   # the newest sessions first
    if not len(keep):
        return {"model": slug, "sessions": 0, "chunks": 0, "explained": [], "points": []}

    dim = mats[0].M.shape[1]
    means = np.zeros((len(keep), dim), dtype=np.float32)
    bounds = np.cumsum([0] + [m.n for m in mats])   # global row -> (matrix, row): rows are the matrices end to end
    for j, g in enumerate(keep):
        rows = order[starts[g]:starts[g] + counts[g]]
        acc = np.zeros(dim, dtype=np.float32)
        for k, m in enumerate(mats):
            r = rows[(rows >= bounds[k]) & (rows < bounds[k + 1])] - bounds[k]
            if len(r):
                acc += m.M[r].sum(axis=0)
        means[j] = acc
    means /= np.linalg.norm(means, axis=1, keepdims=True) + 1e-9

    xyz, explained = project(means)

    sids = [str(sid_s[starts[g]]) for g in keep]
    names, repos = relic._names(sids), relic._repos(sids)
    machines = {}
    for x, g in zip(sids, keep):
        r = int(order[starts[g]])
        k = int(np.searchsorted(bounds, r, side="right") - 1)
        machines[x] = list(mats[k].machines[r - bounds[k]])
    points: list[Json] = [{"sid": x, "x": round(float(p[0]), 4), "y": round(float(p[1]), 4), "z": round(float(p[2]), 4),
                           "n": int(counts[g]), "ts": str(newest[g]), "repo": repos.get(x), "name": names.get(x),
                           "machines": machines.get(x, [])}
                          for x, p, g in zip(sids, xyz, keep)]
    out: Json = {"model": slug, "sessions": len(points), "chunks": int(counts[keep].sum()), "explained": explained,
                 "projection": "pca-3d of per-session mean vectors", "points": points}
    _put(relic, key, out)
    return out


def project(vecs: "Any", basis: "dict[str, Any] | None" = None) -> "tuple[Any, list[float]]":
    """Unit vectors -> (n, 3) coordinates in [-1, 1] by PCA, and the share of variance each axis explains.
    Deterministic: no random seed, and a fixed sign per axis (the largest loading positive) so a rebuild never
    mirrors the map. Fewer rows than axes: the missing axes stay 0. With `basis` (a dict, filled in here) the
    projection is kept, so place() can put other vectors (one message's) in the same space."""
    import numpy as np
    mean = vecs.mean(axis=0)
    centred = vecs - mean
    _, s, vt = np.linalg.svd(centred, full_matrices=False)
    k = min(3, vt.shape[0])
    xyz = np.zeros((len(vecs), 3), dtype=np.float32)
    xyz[:, :k] = centred @ vt[:k].T
    sign = np.sign(vt[:k][np.arange(k), np.abs(vt[:k]).argmax(axis=1)])
    xyz[:, :k] *= sign
    span = np.abs(xyz).max(axis=0)
    span = np.where(span > 0, span, 1)
    xyz /= span
    if basis is not None:
        basis.update(mean=mean, axes=vt[:k] * sign[:, None], span=span[:k])
    var = s ** 2
    return xyz, ([round(float(v / var.sum()), 4) for v in var[:k]] if var.sum() > 0 else [])


_BASIS: dict[tuple[object, ...], dict[str, "Any"]] = {}   # (generation, model) -> the sessions map's projection


def place(relic: "Relic5", uids: list[str], scores: list[float] | None = None, model: str | None = None) -> Json:
    """Messages (by uid) as points in the sessions map's own 3D space: each one's vector through the map's PCA, so a
    search's hits can be drawn over the map. Also the hits' centre, their vectors averaged by score (the hub embeds no
    query: this is where the hits sit, not the query). Rows with no vector come back in `missing`."""
    import numpy as np
    from .search import pick_model
    index = relic.index
    slug = pick_model(index, model)
    key = (index.seen, slug)
    if key not in _BASIS:
        _BASIS.clear()
        mats = index.matrices(slug)
        if not mats:
            return {"points": [], "missing": uids, "centre": None}
        b: dict[str, Any] = {}
        # exactly sessions_map's rows (the newest `limit` sessions with at least MIN_CHUNKS chunks, each its unit mean),
        # so the PCA is the same one the Map drew; reduceat sums each session's rows in one pass
        sid = np.concatenate([m.cols["sid"].astype(str) for m in mats])
        ts = np.concatenate([m.cols["ts"].astype(str) for m in mats])
        allv = np.concatenate([m.M for m in mats])
        order = np.lexsort((ts, sid))
        sid_s = sid[order]
        starts = np.flatnonzero(np.r_[True, sid_s[1:] != sid_s[:-1]])
        counts = np.diff(np.r_[starts, len(sid_s)])
        newest = ts[order][starts + counts - 1]
        keep = np.flatnonzero(counts >= MIN_CHUNKS)
        keep = keep[np.argsort(newest[keep])[::-1][:LIMIT]]
        means = np.add.reduceat(allv[order], starts)[keep]
        means /= np.linalg.norm(means, axis=1, keepdims=True) + 1e-9
        project(means, b)
        _BASIS[key] = b
    b = _BASIS[key]
    want = list(dict.fromkeys(u for u in uids if u))
    found: dict[str, "Any"] = {}
    for m in index.matrices(slug):
        hit = np.flatnonzero(np.isin(m.cols["uid"].astype(str), want))
        for i in hit:
            found.setdefault(str(m.cols["uid"][i]), m.M[i])
    def xyz(v: "Any") -> list[float]:
        p = ((v - b["mean"]) @ b["axes"].T) / b["span"]
        p = np.clip(p, -1.6, 1.6)
        return [round(float(x), 4) for x in list(p) + [0.0] * (3 - len(p))]
    points = [{"uid": u, **dict(zip("xyz", xyz(found[u])))} for u in want if u in found]
    centre = None
    if found:
        w = {u: s for u, s in zip(uids, scores or [1.0] * len(uids))}
        acc = sum(found[u] * float(w.get(u, 1.0)) for u in found)
        centre = dict(zip("xyz", xyz(acc / (np.linalg.norm(acc) + 1e-9))))
    return {"model": slug, "points": points, "missing": [u for u in want if u not in found], "centre": centre,
            "projection": "the sessions map's pca-3d, applied to each message's own vector"}


def search_space(relic: "Relic5", uids: list[str], scores: list[float] | None = None) -> Json:
    """A search's hits placed (place) with the Map's own cloud of sessions (sessions_map, cached) behind them."""
    out = place(relic, uids, scores)
    cloud = sessions_map(relic)
    out["cloud"] = [{"sid": p["sid"], "x": p["x"], "y": p["y"], "z": p["z"], "repo": p.get("repo")} for p in cloud.get("points", [])]
    return out


def memory_map(relic: "Relic5", model: str | None = None) -> Json:
    """Every memory note with a vector of its own (vec.missing hands the notes to the embed worker), one point each.
    -> {model, notes, embedded, explained, points: [{uid, x, y, z, type, project, title, ts, machines}]}"""
    import os
    import numpy as np
    from . import vec as V
    root = relic.parts.root
    mem = os.path.join(root, "index", "_memory", "notes.parquet")
    have = V.vectors_sql(root, model or V.DEFAULT)
    if not os.path.exists(mem):
        return {"model": model or V.DEFAULT, "notes": 0, "embedded": 0, "explained": [], "points": []}
    m = mem.replace("'", "''")
    total = relic._rows(f"SELECT count(*) AS n FROM read_parquet('{m}')")[0]["n"]
    key = ("memory", os.path.getmtime(mem), model or "", total, os.path.getmtime(vd) if os.path.isdir(vd := os.path.join(root, V.VDIR, model or V.DEFAULT)) else 0)
    hit = _get(relic, key)
    if hit is not None:
        return hit
    if have is None:
        return {"model": model or V.DEFAULT, "notes": total, "embedded": 0, "explained": [], "points": []}
    cur = relic.con.cursor()
    rows = cur.execute(f"""SELECT n.msgkey, n.ts, n.role, n.cat, n.title, n.machines, v.vector::FLOAT[] AS vector
                           FROM read_parquet('{m}') n JOIN (SELECT key, any_value(vector) AS vector FROM {have} GROUP BY key) v USING (key)""").fetchall()
    if not rows:
        return {"model": model or V.DEFAULT, "notes": total, "embedded": 0, "explained": [], "points": []}
    vecs = np.asarray([r[6] for r in rows], dtype=np.float32)
    vecs /= np.linalg.norm(vecs, axis=1, keepdims=True) + 1e-9
    xyz, explained = project(vecs)
    points: list[Json] = [{"uid": r[0], "x": round(float(p[0]), 4), "y": round(float(p[1]), 4), "z": round(float(p[2]), 4),
                           "ts": r[1], "type": (r[2] or "memory-note")[7:], "project": r[3], "title": r[4], "machines": list(r[5] or [])}
                          for r, p in zip(rows, xyz)]
    out: Json = {"model": model or V.DEFAULT, "notes": total, "embedded": len(points), "explained": explained,
                 "projection": "pca-3d of each note's own vector", "points": points}
    _put(relic, key, out)
    return out
