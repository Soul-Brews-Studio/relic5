"""universe.py: the hub's sessions as points in space, for the Map view (Nat, 2026-10-24: "vector 3d interactive
visualization ... and 2d", after lanceglass's Session vector map, Atlas 3D / Flat 2D, 2026-09-01).

One point per session: the mean of its prose chunks' vectors, made unit length, so sessions about the same thing sit
together. Projected by PCA to three axes (the 2D view draws the first two), the same deterministic projection
lanceglass ships as deterministic-pca-3d: no random seed, the same hub gives the same map. Each axis is scaled to
[-1, 1]. One map per index generation and model, kept in memory; a new generation rebuilds it on the next call.

Points carry the session's id, name, repo, newest time, chunk count and machines; the page colours them by repo.
"""
import threading
from typing import TYPE_CHECKING

from .types_ import Json

if TYPE_CHECKING:
    from .query import Relic5

_LOCK = threading.Lock()
_CACHE: dict[tuple[object, str, int, int], Json] = {}
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

    centred = means - means.mean(axis=0)
    _, s, vt = np.linalg.svd(centred, full_matrices=False)
    k = min(3, vt.shape[0])   # fewer sessions than axes: the missing axes stay 0
    xyz = np.zeros((len(keep), 3), dtype=np.float32)
    xyz[:, :k] = centred @ vt[:k].T
    # a fixed sign per axis (the largest loading positive), so the map does not mirror between rebuilds
    xyz[:, :k] *= np.sign(vt[:k][np.arange(k), np.abs(vt[:k]).argmax(axis=1)])
    span = np.abs(xyz).max(axis=0)
    xyz /= np.where(span > 0, span, 1)
    var = s ** 2
    explained = [round(float(v / var.sum()), 4) for v in var[:k]] if var.sum() > 0 else []

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

