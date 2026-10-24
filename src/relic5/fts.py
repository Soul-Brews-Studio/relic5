"""fts.py: the keyword index. BM25 over ICU tokens (Thai inside words), relic3's design in months.

relic3 (agent-relic-v3 src/search/build.ts, fts.ts @9f0bdb5) keeps history.lance for sealed weeks and open.lance for
the open week, so a new line rebuilds only the small table. relic5 does the same with months, per layer:

  index/_search/<gen>/<layer>_history.lance    every sealed month (before the current Bangkok month)
  index/_search/<gen>/<layer>_open.lance       the open month
  index/_search/current.json                   {table: "<gen>/<layer>_<part>.lance"}: written last, by rename

layer = prose (text stream + ψ notes, role note, as relic3's prose), tools, thinking. Rows are folded by (msgkey, chunk)
across machines before they go in, with `machines` = every machine that sent the row. A table is rebuilt only when
one of its months' manifests changed since it was built. The newest 3 generations are kept; a table still named by
current.json is never removed. Tokenizer settings are relic3's, as relic4 carries them (agent-relic-v4
src/relic4/embed.py FTS_SETTINGS, PR #6 @b399119): icu, no stemming, no stop words, max token 128.
"""
import json, os, shutil, time
from collections.abc import Callable, Collection, Sequence
from datetime import datetime
from typing import TYPE_CHECKING, TypedDict

from .parts import Parts, sql_list, this_month
from .types_ import Json

if TYPE_CHECKING:   # for annotations only: duckdb and lancedb are loaded where they are used
    import duckdb
    import lancedb.table
    from .vec import Matrix, VecFilter


class FtsSettings(TypedDict):
    """lancedb.index.FTS's keyword arguments, as FTS_SETTINGS gives them."""
    base_tokenizer: str
    stem: bool
    remove_stop_words: bool
    max_token_length: int
    with_position: bool


FTS_SETTINGS = FtsSettings(base_tokenizer="icu", stem=False, remove_stop_words=False, max_token_length=128,
                    with_position=True)   # positions: exact-phrase hits rank first (eval 2026-10-23: common-word misses)
LAYERS = {"prose": ("text", "vault"), "tools": ("tools",), "thinking": ("thinking",), "memory": ("memory",)}
COLS = ["uid", "msgkey", "chunk", "key", "month", "sid", "ts", "ts_th", "role", "engine", "cat", "layer", "machines", "text", "title"]
KEEP = 3


def search_dir(root: str) -> str:
    return os.path.join(root, "index", "_search")


def current(root: str) -> dict[str, str]:
    p = os.path.join(search_dir(root), "current.json")
    return json.load(open(p)) if os.path.exists(p) else {}


def _select(parts: Parts, layer: str, months: Collection[str]) -> str | None:
    """SQL for the folded rows of one layer over some months (vault, a single file, goes to history; so does memory,
    already folded by memory.py)."""
    if layer == "memory":
        p = os.path.join(parts.root, "index", "_memory", "notes.parquet")
        if "history" not in months or not os.path.exists(p):
            return None
        return f"""SELECT msgkey AS uid, msgkey, chunk, key, month, sid, ts, ts_th, role, engine, cat, 'memory' AS layer,
                   machines, text, title FROM read_parquet({sql_list([p])}) ORDER BY ts, msgkey"""
    srcs: list[str] = []
    for s in LAYERS[layer]:
        fs = [p for _, mon, p in parts.files(s) if (s == "vault" and "history" in months) or mon in months]
        if fs:
            title = "title" if s == "vault" else "NULL::VARCHAR AS title"
            srcs.append(f"""SELECT regexp_extract(filename, '/parts/([^/]+)/', 1) AS machine, msgkey, chunk, key,
                coalesce(month, substr(ts_th, 1, 7)) AS month, sid, ts, ts_th, role, engine, cat, '{layer}' AS layer, text, {title}
                FROM read_parquet({sql_list(fs)}, union_by_name = true, filename = true) WHERE text IS NOT NULL AND text <> ''""")
    if not srcs:
        return None
    u = " UNION ALL BY NAME ".join(srcs)
    return f"""SELECT msgkey || CASE WHEN chunk > 0 THEN ':' || chunk ELSE '' END AS uid, * EXCLUDE (rn, machine) FROM (
               SELECT *, list(machine) OVER (PARTITION BY msgkey, chunk ORDER BY machine
                 ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING) AS machines,
               row_number() OVER (PARTITION BY msgkey, chunk ORDER BY machine) AS rn FROM ({u})) WHERE rn = 1
               ORDER BY ts, msgkey, chunk"""


def _sig(parts: Parts, layer: str, months: Collection[str]) -> Json:
    """What a table was built from: per month, the manifest entry of the layer's own streams (files, sizes, mtimes,
    rows per machine), so a new tools part does not rebuild prose."""
    sig: Json = {}
    for m in months:
        p = parts.manifest_path(m)
        if os.path.exists(p):
            st = json.load(open(p))["streams"]
            sig[m] = {s: st[s] for s in LAYERS[layer] if s in st}
    return sig


def build(root: str, con: "duckdb.DuckDBPyConnection", log: Callable[[str], object] = print, now: datetime | None = None,
          force: bool = False, lane: str = "fts") -> list[str]:
    """Rebuild every table of one lane whose inputs changed; publish one new generation. Returns the tables rebuilt.
    lane = "fts" (BM25, fast: every push) or "vectors" (vector tables: after an embed worker ships shards). The two never
    run together (Nat, 2026-10-23: "collect icu / fts search first / vector index embed later not same time")."""
    import lancedb
    from lancedb.index import FTS

    parts = Parts(root)
    cur_month = this_month(now)
    months = parts.months()
    groups = {"history": [m for m in months if m != "undated" and m < cur_month] + ["undated"], "open": [m for m in months if m >= cur_month]}
    sd = search_dir(root)
    os.makedirs(sd, exist_ok=True)
    state_p = os.path.join(sd, "state.json")
    state = json.load(open(state_p)) if os.path.exists(state_p) else {}
    vault = [p for _, _, p in parts.files("vault")]
    from . import memory
    memory.build(root) if lane == "fts" else None
    mem_sig = memory.sig(root)
    plan: dict[str, tuple[str, list[str], Json]] = {}
    for layer in (LAYERS if lane == "fts" else ()):
        for part, ms in groups.items():
            name = f"{layer}_{part}"
            sig = _sig(parts, layer, ms) | ({"vault": [os.path.getmtime(p) for p in vault]} if layer == "prose" and part == "history" else {})
            if layer == "memory":
                if part != "history":
                    continue
                sig = {"notes": mem_sig}
            sig = json.loads(json.dumps(sig))
            if force or state.get(name, {}).get("sig") != sig or name not in current(root):
                plan[name] = (layer, ms + (["history"] if part == "history" else []), sig)
    from . import vec as V
    for model in (V.models(root) if lane == "vectors" else ()):
        layer = "vec_" + V.slug(model)
        sm = V.shard_months(root, model, con, parts)
        sizes = {os.path.basename(f): os.path.getsize(f) for f in V.shards(root, model)}
        for part, ms in groups.items():
            name = f"{layer}_{part}"
            mine = set(ms) | ({"undated", None} if part == "history" else set())
            # only the shards holding keys of this table's months: a new October shard leaves history untouched
            shard_sig = [[n, sizes[n]] for n in sorted(sm) if mine & set(sm[n])]
            sig = json.loads(json.dumps({"text": _sig(parts, "prose", ms), "shards": shard_sig}))
            if force or state.get(name, {}).get("sig") != sig or name not in current(root):
                plan[name] = ("vec:" + model, ms, sig)
    if not plan:
        return []
    # UTC, always: the native venv and the container disagree on the local zone, and "newest" is by name
    gen = time.strftime("%Y%m%d-%H%M%S", time.gmtime()) + f"-{os.getpid()}"   # unique even for two runs in one second
    gdir = os.path.join(sd, gen)
    db = lancedb.connect(gdir)
    cur = dict(current(root))
    done = []
    for name, (layer, ms, sig) in plan.items():
        t = time.time()
        is_vec = layer.startswith("vec:")
        sql = V.table_sql(parts, root, layer[4:], ms) if is_vec else _select(parts, layer, ms)
        tab = con.execute(sql).arrow() if sql else None
        if tab is not None and hasattr(tab, "read_all"):
            tab = tab.read_all()
        if tab is None or tab.num_rows == 0:
            cur.pop(name, None)
            state[name] = {"sig": sig, "rows": 0, "built": gen}
            continue
        if is_vec:
            import pyarrow as pa
            dim = len(tab.column("vector")[0].as_py())
            i = tab.schema.get_field_index("vector")
            flat = tab.column("vector").combine_chunks().flatten().cast(pa.float32())
            tab = tab.set_column(i, "vector", pa.FixedSizeListArray.from_arrays(flat, dim))
        tb = db.create_table(name, tab, mode="overwrite")
        if not is_vec:
            tb.create_index("text", config=FTS(**FTS_SETTINGS), replace=True)
        cur[name] = f"{gen}/{name}.lance"
        state[name] = {"sig": sig, "rows": tab.num_rows, "built": gen, "seconds": round(time.time() - t, 1)}
        done.append(name)
        log(f"fts {name}: {tab.num_rows:,} rows ({time.time() - t:.1f}s)")
    # the other lane may have published meanwhile: merge on the newest files, keep only this lane's tables from us
    cur = {k: v for k, v in current(root).items() if (k.startswith("vec_")) != (lane == "vectors")} | {k: v for k, v in cur.items() if (k.startswith("vec_")) == (lane == "vectors")}
    if os.path.exists(state_p):
        state = {k: v for k, v in json.load(open(state_p)).items() if (k.startswith("vec_")) != (lane == "vectors")} | {k: v for k, v in state.items() if (k.startswith("vec_")) == (lane == "vectors")}
    for p, obj in ((state_p, state), (os.path.join(sd, "current.json"), cur)):   # current.json last: the publish point
        with open(p + ".tmp", "w") as f:
            json.dump(obj, f, indent=1)
        os.replace(p + ".tmp", p)
    _prune(sd, cur)
    return done


def _prune(sd: str, cur: dict[str, str]) -> None:
    live = {v.split("/")[0] for v in cur.values()}
    gens = sorted((d for d in os.listdir(sd) if os.path.isdir(os.path.join(sd, d)) and d[:8].isdigit()),
                  key=lambda d: os.path.getmtime(os.path.join(sd, d)))   # by age on disk, not by name
    for g in gens[:-KEEP]:
        if g not in live:
            shutil.rmtree(os.path.join(sd, g))


class Index:
    """The published tables, reopened when current.json changes (a new generation)."""
    seen: float | None                       # current.json's mtime when the tables were opened
    tables: "dict[str, lancedb.table.Table]"
    _mx: "dict[str, Matrix]"                # vector matrices of generation _mx_seen, made on first use
    _mx_seen: float | None

    def __init__(self, root: str) -> None:
        self.root = os.path.abspath(os.path.expanduser(root))
        self.seen, self.tables = None, {}

    def _load(self) -> "dict[str, lancedb.table.Table]":
        p = os.path.join(search_dir(self.root), "current.json")
        m = os.path.getmtime(p) if os.path.exists(p) else None
        if m != self.seen:
            import lancedb
            cur = current(self.root)
            tabs: dict[str, lancedb.table.Table] = {}
            for name, rel in cur.items():
                gen, fname = rel.split("/")
                tabs[name] = lancedb.connect(os.path.join(search_dir(self.root), gen)).open_table(fname[:-6])
            self.tables, self.seen = tabs, m
        return self.tables

    def built(self) -> bool:
        return bool(self._load())

    def vector(self, model: str, vector: Sequence[float], filt: "VecFilter", limit: int) -> list[Json]:
        """Nearest prose rows to a unit query vector: exact, in memory (vec.Matrix), best first; _score = cosine."""
        from . import vec as V
        tabs = self._load()
        if getattr(self, "_mx_seen", None) != self.seen:
            self._mx, self._mx_seen = {}, self.seen
        out: list[Json] = []
        for part in ("open", "history"):
            name = f"vec_{V.slug(model)}_{part}"
            if name not in tabs:
                continue
            if name not in self._mx:
                self._mx[name] = V.Matrix(tabs[name])
            out += self._mx[name].search(vector, filt, limit)
        out.sort(key=lambda r: -r["_score"])
        return out[:limit]

    def vector_models(self) -> list[str]:
        return sorted({n[4:].rsplit("_", 1)[0] for n in self._load() if n.startswith("vec_")})

    def _fts(self, layer: str, q: str, where: str | None, limit: int) -> list[Json]:
        out: list[Json] = []
        for part in ("open", "history"):
            tb = self._load().get(f"{layer}_{part}")
            if tb is None:
                continue
            qb = tb.search(q, query_type="fts").limit(limit)
            if where:
                qb = qb.where(where, prefilter=True)
            out += qb.select(COLS + ["_score"]).to_list()
        out.sort(key=lambda r: (-r["_score"], r["ts"] or ""))
        return out[:limit]

    def query(self, layer: str, q: str, where: str | None, limit: int) -> list[Json]:
        """BM25 hits of one layer (history + open), best first. A query of two or more words also runs as an exact
        phrase, and those hits come first: with any-term ranking, common words ("to use ego browser to") let longer
        texts outrank the one that says it (12 of 22 known-item misses, eval 2026-10-23). A quoted query is a phrase
        only; a table built without positions falls back to any-term."""
        q = q.strip()
        if q.startswith('"') and q.endswith('"') and len(q) > 2:
            return self._fts(layer, q, where, limit)
        if len(q.split()) < 2:
            return self._fts(layer, q, where, limit)
        try:
            phrase = self._fts(layer, '"' + q.replace('"', " ") + '"', where, limit)
        except Exception:
            phrase = []
        seen = {r["uid"] for r in phrase}
        return (phrase + [r for r in self._fts(layer, q, where, limit) if r["uid"] not in seen])[:limit]
