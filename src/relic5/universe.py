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
MIN_CHUNKS = 3   # a session with one or two embedded lines lands wherever its one sentence points: noise on the map


def sessions_map(relic: "Relic5", model: str | None = None, limit: int = 3000, min_chunks: int = MIN_CHUNKS) -> Json:
    """-> {model, sessions, chunks, explained, points: [{sid, x, y, z, n, ts, repo, name, machines}]}, newest
    sessions first up to limit (the projection is fitted on exactly those)."""
    import numpy as np
    from .search import pick_model
    index = relic.index
    slug = pick_model(index, model)
    mats = index.matrices(slug)
    key = (index.seen, slug, int(limit), int(min_chunks))
    with _LOCK:
        if key in _CACHE:
            return _CACHE[key]
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
    with _LOCK:
        _CACHE.clear()
        _CACHE[key] = out
    return out


def project(vecs: "Any") -> "tuple[Any, list[float]]":
    """Unit vectors -> (n, 3) coordinates in [-1, 1] by PCA, and the share of variance each axis explains.
    Deterministic: no random seed, and a fixed sign per axis (the largest loading positive) so a rebuild never
    mirrors the map. Fewer rows than axes: the missing axes stay 0."""
    import numpy as np
    centred = vecs - vecs.mean(axis=0)
    _, s, vt = np.linalg.svd(centred, full_matrices=False)
    k = min(3, vt.shape[0])
    xyz = np.zeros((len(vecs), 3), dtype=np.float32)
    xyz[:, :k] = centred @ vt[:k].T
    xyz[:, :k] *= np.sign(vt[:k][np.arange(k), np.abs(vt[:k]).argmax(axis=1)])
    span = np.abs(xyz).max(axis=0)
    xyz /= np.where(span > 0, span, 1)
    var = s ** 2
    return xyz, ([round(float(v / var.sum()), 4) for v in var[:k]] if var.sum() > 0 else [])


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
    key = (os.path.getmtime(mem), "memory", model or "", total)
    with _LOCK:
        if key in _CACHE:
            return _CACHE[key]
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
    with _LOCK:
        _CACHE[key] = out
    return out
