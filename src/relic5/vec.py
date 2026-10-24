"""vec.py: vectors on the hub. The hub embeds nothing: clients make vectors, the hub stores, indexes and searches them.

  <root>/vectors/<model@hash>/*.parquet     shards (key VARCHAR, vector FLOAT[]), float32, L2-normalised
      key = blake2b-128 of the chunk text (relic-extract's key); model@hash = relic4's cache name
      (agent-relic-v4 src/relic4/embed.py cache_name, PR #6 @b399119): the model plus doc_prompt, dtype, max_seq.
      Seeded from m5's ~/relic4-scratch/vec/_cache (1,031,819 keys, gemma-300m@806f5f90, 2026-10-23).
  vec_<slug>_history / vec_<slug>_open      LanceDB tables built by `relic5 index` (fts.py builds them beside BM25):
      the prose rows (text stream, folded across machines) that have a vector, sealed months / the open month.

A worker (m5 MPS or ANE, gb300 ad hoc) asks `missing()` (GET /api/missing) for keys without a vector, newest
watermark first, embeds them with the SAME model@hash and rsyncs a shard into vectors/<model@hash>/ over ssh: the
search server stays read-only. Any engine may write shards; vectors from another engine must pass a parity probe
before they go in the same folder (relic3: an --also engine passes a parity probe, hub/README.md).
"""
import os, re
from collections.abc import Collection, Sequence
from typing import TYPE_CHECKING, Any, TypedDict

from .parts import Parts, sql_list
from .types_ import Json

if TYPE_CHECKING:   # for annotations only: numpy, duckdb and lancedb are loaded where they are used
    import duckdb
    import lancedb.table
    from numpy.typing import NDArray

VDIR = "vectors"
MODEL_DIR = re.compile(r"^[A-Za-z0-9._-]+--[A-Za-z0-9._-]+@[0-9a-f]{8}$")
DEFAULT = "unsloth--embeddinggemma-300m@806f5f90"
# Rows shorter than this are not searched by vector: tiny texts ("Let me count the words.") sit near every short query.
# relic3 used 24 (src/vectors/select.ts:22-26); measured here on tests/eval/semantic.json, 2026-10-23: 0 and 24 -> 0/6,
# 80 -> 2/6, 160 -> 2/6. They are still searchable by keyword.
MIN_CHARS = int(os.environ.get("RELIC5_VEC_MIN_CHARS", "80"))   # applied per query (the `chars` column), tunable
BUILD_MIN = int(os.environ.get("RELIC5_VEC_BUILD_MIN", "1"))     # what goes in the table at all


class VecFilter(TypedDict, total=False):
    """The filters of one vector search (Matrix.search): a ts window, a role, a session prefix or set, min chars."""
    lo: str | None
    hi: str | None
    role: str | None
    sid_prefix: str | None
    sids: set[str]
    min_chars: int


def models(root: str) -> list[str]:
    d = os.path.join(root, VDIR)
    if not os.path.isdir(d):
        return []
    return sorted(m for m in os.listdir(d) if MODEL_DIR.match(m) and shards(root, m))


def shards(root: str, model: str) -> list[str]:
    d = os.path.join(root, VDIR, model)
    return sorted(os.path.join(d, f) for f in os.listdir(d) if f.endswith(".parquet") and not f.startswith(".")) if os.path.isdir(d) else []


def slug(model: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", model.lower()).strip("_")


def vectors_sql(root: str, model: str) -> str | None:
    """One vector per key: shards may overlap (relic4: read them as any_value ... GROUP BY key)."""
    fs = shards(root, model)
    return f"(SELECT key, any_value(vector) AS vector FROM read_parquet({sql_list(fs)}) GROUP BY key)" if fs else None


def text_sql(parts: Parts, months: Collection[str] | None = None) -> str | None:
    fs = [p for _, mon, p in parts.files("text") if months is None or mon in months]
    if not fs:
        return None
    return f"""(SELECT regexp_extract(filename, '/parts/([^/]+)/', 1) AS machine, msgkey, chunk, key, month, sid, ts, ts_th,
               role, engine, cat, text FROM read_parquet({sql_list(fs)}, union_by_name = true, filename = true)
               WHERE text IS NOT NULL AND text <> '')"""


def missing(root: str, con: "duckdb.DuckDBPyConnection", model: str = DEFAULT, limit: int = 1000, prefix: str = "",
            max_chars: int = 6000) -> Json:
    """Keys of the prose text stream with no vector yet, newest first (the open month first), one row per key.
    prefix: only keys starting with it, so two workers (m5, gb300) can take disjoint slices."""
    parts = Parts(root)
    src = text_sql(parts)
    if src is None:
        return {"model": model, "rows": [], "pending": 0}
    have = vectors_sql(root, model)
    anti = f"AND key NOT IN (SELECT key FROM {have})" if have else ""
    pre = "AND starts_with(key, ?)" if prefix else ""
    params: list[object] = [prefix] if prefix else []
    base = f"SELECT key, max(ts) AS ts, any_value(substr(text, 1, {int(max_chars)})) AS text FROM {src} WHERE TRUE {anti} {pre} GROUP BY key"
    one = con.execute(f"SELECT count(*) FROM ({base})", params).fetchone()
    assert one is not None   # count(*) always answers one row
    pending = one[0]
    rows = con.execute(f"SELECT key, ts, text FROM ({base}) ORDER BY ts DESC LIMIT ?", params + [int(limit)]).fetchall()
    return {"model": model, "pending": pending, "rows": [{"key": k, "ts": t, "text": x} for k, t, x in rows]}


def watermarks(root: str, con: "duckdb.DuckDBPyConnection", model: str = DEFAULT) -> dict[str, Json]:
    """Per machine: the newest ts at or before which every text chunk has a vector, and how many have none."""
    parts = Parts(root)
    src, have = text_sql(parts), vectors_sql(root, model)
    if src is None:
        return {}
    if have is None:
        return {m: {"at": None, "pending": n} for m, n in con.execute(f"SELECT machine, count(*) FROM {src} GROUP BY 1").fetchall()}
    rows = con.execute(f"""SELECT machine, min(ts) FILTER (WHERE v.key IS NULL) AS first_gap, max(ts) AS newest,
                           count(*) FILTER (WHERE v.key IS NULL) AS pending
                           FROM {src} t LEFT JOIN {have} v USING (key) GROUP BY machine""").fetchall()
    out: dict[str, Json] = {}
    for m, gap, newest, pending in rows:
        if gap is None:
            at = newest
        else:
            one = con.execute(f"SELECT max(ts) FROM {src} WHERE machine = ? AND ts < ?", [m, gap]).fetchone()
            assert one is not None   # max() always answers one row
            at = one[0]
        out[m] = {"at": at, "pending": pending}
    return out


def write_marks(root: str, con: "duckdb.DuckDBPyConnection", published: bool) -> dict[str, dict[str, Json]]:
    """Write index/_search/vectors.json: per model and machine the watermark and how many chunks have no vector.
    The vector lane (published=True) moves "at", the time vectors were last published. The fast lane recounts after
    every push (published=False, about 1 s), so pending grows as new messages land instead of reading 0 until the
    next embed; "counted_at" says when the count was taken."""
    import json, os, time
    from .fts import search_dir
    p = os.path.join(search_dir(root), "vectors.json")
    try:
        old = json.load(open(p)).get("at")
    except (OSError, ValueError, AttributeError):
        old = None
    marks = {m: watermarks(root, con, m) for m in models(root)}
    now = time.strftime("%FT%T%z")
    with open(p + ".tmp", "w") as f:
        json.dump({"at": now if published else old, "counted_at": now, "models": marks}, f, indent=1)
    os.replace(p + ".tmp", p)
    return marks


def table_sql(parts: Parts, root: str, model: str, months: Collection[str]) -> str | None:
    """Folded prose text rows of some months joined to their vectors (rows with no vector are left out)."""
    src, have = text_sql(parts, months), vectors_sql(root, model)
    if src is None or have is None:
        return None
    return f"""SELECT msgkey || CASE WHEN chunk > 0 THEN ':' || chunk ELSE '' END AS uid, * EXCLUDE (rn, machine) FROM (
               SELECT t.*, 'prose' AS layer, NULL::VARCHAR AS title, v.vector::FLOAT[] AS vector, length(t.text) AS chars,
                 list(machine) OVER (PARTITION BY msgkey, chunk ORDER BY machine
                   ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING) AS machines,
                 row_number() OVER (PARTITION BY msgkey, chunk ORDER BY machine) AS rn
               FROM {src} t JOIN {have} v USING (key) WHERE length(t.text) >= {BUILD_MIN}) WHERE rn = 1 ORDER BY ts, msgkey, chunk"""


def probe_rows(root: str, con: "duckdb.DuckDBPyConnection", model: str = DEFAULT, n: int = 200) -> list[Json]:
    """n random text chunks (>= MIN_CHARS) with their stored vector: a parity probe for another engine."""
    src, have = text_sql(Parts(root)), vectors_sql(root, model)
    if src is None or have is None:
        return []
    rows = con.execute(f"""SELECT key, any_value(substr(text, 1, 6000)) AS text FROM {src} WHERE length(text) >= {MIN_CHARS}
                           GROUP BY key USING SAMPLE reservoir({int(n)} ROWS) REPEATABLE (23)""").fetchall()
    keys = [k for k, _ in rows]
    vec = dict(con.execute(f"SELECT key, vector FROM {have} WHERE key IN (SELECT unnest(?))", [keys]).fetchall())
    return [{"key": k, "text": t, "vector": list(vec[k])} for k, t in rows if k in vec]


class Matrix:
    """Exact vector search held in memory, ported from agent-relic-v4 src/relic4/vecmem.py (PR #6 @b399119): LanceDB's
    flat scan cost ~2.2 s a query here (measured 2026-10-23, 593 k rows); one float32 matrix makes it a matmul plus a
    boolean mask for the filters, same results. Loaded on first use, replaced when a new generation is published."""
    META: list[str] = ["uid", "msgkey", "chunk", "key", "month", "sid", "ts", "ts_th", "role", "engine", "cat", "layer", "text", "title", "chars"]

    _ts: "NDArray[Any]"    # ts and sid as str arrays, made on the first search
    _sid: "NDArray[Any]"

    def __init__(self, table: "lancedb.table.Table") -> None:
        import numpy as np
        tab = table.to_lance().to_table(columns=self.META + ["machines", "vector"])
        n: int = tab.num_rows
        self.M: NDArray[np.float32] = tab.column("vector").combine_chunks().values.to_numpy(zero_copy_only=False).astype(np.float32).reshape(n, -1)
        self.cols: dict[str, NDArray[Any]] = {c: tab.column(c).to_numpy(zero_copy_only=False) for c in self.META}
        self.machines: list[list[str]] = tab.column("machines").to_pylist()
        self.n = n

    def search(self, q: Sequence[float], f: VecFilter, limit: int) -> list[Json]:
        """q: unit vector; f: {lo, hi, role, sid_prefix, sids, min_chars}. -> rows with _score = cosine.
        One matmul over every row, then the filters as a mask (no copy of the matrix: M[idx] copied 2.5 GB a query)."""
        import numpy as np
        c = self.cols
        if not hasattr(self, "_ts"):
            self._ts, self._sid = c["ts"].astype(str), c["sid"].astype(str)
        s = self.M @ np.asarray(q, dtype=np.float32)
        mask = c["chars"] >= f.get("min_chars", MIN_CHARS)
        if f.get("lo"):
            mask &= self._ts >= f["lo"]
        if f.get("hi"):
            mask &= self._ts <= f["hi"]
        if f.get("role"):
            mask &= c["role"] == f["role"]
        if sid_prefix := f.get("sid_prefix"):
            mask &= np.char.startswith(self._sid, sid_prefix)
        if f.get("sids") is not None:
            mask &= np.isin(self._sid, list(f["sids"]))
        s = np.where(mask, s, -np.inf)
        k = min(limit, int(mask.sum()))
        if k <= 0:
            return []
        top = np.argpartition(-s, k - 1)[:k]
        top = top[np.argsort(-s[top])]
        out: list[Json] = []
        for i in top:
            r: Json = {k2: (v.item() if hasattr(v, "item") else v) for k2, v in ((k2, c[k2][i]) for k2 in self.META)}
            r["machines"] = self.machines[i]
            r["_score"] = float(s[i])
            out.append(r)
        return out
