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
import json, os, shutil, threading, time
from collections.abc import Callable, Collection, Sequence
from datetime import datetime
from typing import TYPE_CHECKING, TypedDict

from .parts import Parts, sql_list, this_month
from .types_ import Json
from . import store as rfs

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
LAYERS = {"prose": ("text", "vault"), "tools": ("tools",), "thinking": ("thinking",), "memory": ("memory",), "git": ("git",)}
SIDE = {"memory": ("_memory", "notes.parquet"), "git": ("_git", "commits.parquet")}
"""Layers built from a table the hub folds itself (memory.py, gitlog.py), not from month parts: history only."""
COLS = ["uid", "msgkey", "chunk", "key", "month", "sid", "ts", "ts_th", "role", "engine", "cat", "layer", "machines", "text", "title"]
HOME_COLS = ["home", "homes", "agent"]
"""Which .claude (or .codex) a row came from (Nat, 2026-10-25: "can we separate like .claude from user nat / .claude
from user beta or .claude project of some project"): home is the last .claude*/.codex* folder before projects*,
sessions or backups in relic-scan's src_path (/Users/beta/.claude, /Users/nat/.claude1, a project's own
.../exp/.claude-hello/.claude); homes, every home that holds the message (a copy lives in several), newline-joined;
agent, relic-scan's user@host. Tables built before this have none of them (index --force adds them)."""
# with any folders under the home before projects/, sessions/ or a Claude project folder (-Users-...):
# .codex-team/1/sessions, .codex/path-migration-backup-*/sessions, .claude/rescued-*/full-backup-*/-Users-nat-x
# (2026-10-25: those left 1,587 sessions without a home)
# other agents' homes and copies that hold no .claude/.codex: ~/.omp/agent/sessions, <repo>/.thclaws/sessions,
# ~/.relic-mirrors/<name>/2026/..., ~/.tmp/projects-bak/-home-nat-x (2026-10-25: the last 648 sessions without a home)
HOME_SQL = (r"coalesce(nullif(regexp_extract(src_path, '^(.*/\.(?:claude|codex)[^/]*(?:/[^/]+)*?)/(?:(?:projects|sessions|backups|archived|jobs|transcripts)[^/]*|-[^/]+)/', 1), ''),"
            r" nullif(regexp_extract(src_path, '^(.*/\.(?:omp|thclaws|relic-mirrors|relic3-mirror|tmp)[^/]*(?:/[^/]+)*?)/(?:(?:projects|sessions|state)[^/]*|-[^/]+|20[0-9][0-9])/', 1), ''),"
            # last: the folder holding Claude project folders (-Users-..., -home-...), under projects/ or not:
            # ~/mba-claude-backup/-Users-nat-x, <repo>/accounts/2/projects/-home-nat-x
            r" nullif(regexp_extract(src_path, '^(/.*?)/(?:projects[^/]*/)?-(?:Users|home|opt|private|tmp|var|Volumes)-[^/]*/', 1), ''))")
KEEP = 3


def tokens(text: str) -> list[str]:
    """The words the BM25 index sees in a text: lance's own query tokenizer with the index's settings (ICU, so Thai
    splits into words; lower case; no stemming, no stop words). The Search page shows a query this way."""
    import lance
    return [t.text for t in lance.tokenize(text, base_tokenizer=FTS_SETTINGS["base_tokenizer"], stem=FTS_SETTINGS["stem"],
                                            remove_stop_words=FTS_SETTINGS["remove_stop_words"],
                                            max_token_length=FTS_SETTINGS["max_token_length"])]


def search_dir(root: str) -> str:
    """Where the search index lives. On a disk: <root>/index/_search. On an S3 root: the local cache, because the index
    is derived (rebuilt from the parts) and every query reads it: from the bucket a search took 1.2-1.6 s where the
    disk hub took 0.3 s (2026-10-25). RELIC5_INDEX_LOCAL=0 keeps it in the bucket."""
    root = str(root)
    if rfs.is_s3(root) and os.environ.get("RELIC5_INDEX_LOCAL", "1") != "0":
        return rfs.cache_dir(root.rstrip("/"), "index", "_search")
    return os.path.join(root, "index", "_search")


def seed_local(root: str, log: Callable[[str], object] = print) -> int:
    """Copy the bucket's index/_search down (a mirror of a disk hub carries one), the pointers last, so an S3 hub
    searches at once: when there is no local index yet, and again when the bucket publishes a newer one while the
    local index is still the one seeded from it (a hub that built its own index keeps it). Files already here at the
    same size are not copied again; generations neither pointer names are removed. -> files copied."""
    root = str(root).rstrip("/")
    if not rfs.is_s3(root) or os.environ.get("RELIC5_INDEX_LOCAL", "1") == "0":
        return 0
    local, remote = search_dir(root), os.path.join(root, "index", "_search")
    if not rfs.isfile(os.path.join(remote, "current.json")):
        return 0
    cur = rfs.read_json(os.path.join(remote, "current.json"))
    seeded_p, here_p = os.path.join(local, "seeded.json"), os.path.join(local, "current.json")
    here = rfs.read_json(here_p) if os.path.exists(here_p) else None
    seeded = rfs.read_json(seeded_p) if os.path.exists(seeded_p) else None
    if here is not None and (here != seeded or cur == here):
        return 0   # built here (not a seed), or already the bucket's
    from concurrent.futures import ThreadPoolExecutor
    from .mirror import _copy_one
    gens = {v.split("/")[0] for v in cur.values()}
    todo = [(p, n) for g in sorted(gens) for p, n, _ in rfs.files(os.path.join(remote, g))]
    todo = [(p, n) for p, n in todo if not (os.path.isfile(q := os.path.join(local, p[len(remote) + 1:])) and os.path.getsize(q) == n)]
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda pn: _copy_one(pn[0], os.path.join(local, pn[0][len(remote) + 1:])), todo))
    for f in ("names.parquet", "homes.parquet", "shard_months.json", "vectors.json", "state.json", "current.json"):
        if rfs.isfile(os.path.join(remote, f)):
            _copy_one(os.path.join(remote, f), os.path.join(local, f))
    rfs.write_json(seeded_p, cur)
    keep = gens | {v.split("/")[0] for v in (here or {}).values()}   # the previous one: a query may still hold it open
    for g in os.listdir(local):
        if os.path.isdir(os.path.join(local, g)) and g[:1].isdigit() and g not in keep:
            shutil.rmtree(os.path.join(local, g), ignore_errors=True)
    log(f"seeded the local index from {remote}: {len(todo)} files")
    return len(todo)


_MX_LOCK = threading.Lock()
SEEDING: dict[str, str] = {}   # root -> when its local index began copying from the bucket


def seed_in_background(root: str, every: float = 0) -> threading.Thread:
    """seed_local in a thread; every > 0: again every that many seconds (a newer index mirrored into the bucket)."""
    def run() -> None:
        SEEDING[root] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        while True:
            try:
                seed_local(root, log=lambda m: print(f"relic5: {m}", flush=True))
            except Exception as ex:   # no seed: the auto-index builds one
                print(f"relic5: could not seed the local index: {ex}", flush=True)
            finally:
                SEEDING.pop(root, None)
            if not every:
                return
            time.sleep(every)
    t = threading.Thread(target=run, name="relic5-seed", daemon=True)
    t.start()
    return t


def current(root: str) -> dict[str, str]:
    p = os.path.join(search_dir(root), "current.json")
    return rfs.read_json(p) if rfs.exists(p) else {}


def _columns(con: "duckdb.DuckDBPyConnection | None", files: list[str]) -> set[str]:
    """The columns a set of parts has between them (old parts have no src_path)."""
    if con is None or not files:
        return set()
    try:
        return {r[0] for r in con.execute(f"DESCRIBE SELECT * FROM read_parquet({sql_list(files)}, union_by_name = true)").fetchall()}
    except Exception:
        return set()


def _select(parts: Parts, layer: str, months: Collection[str], con: "duckdb.DuckDBPyConnection | None" = None) -> str | None:
    """SQL for the folded rows of one layer over some months (vault, a single file, goes to history; so do memory and
    git, already folded by memory.py and gitlog.py)."""
    if layer in SIDE:
        p = os.path.join(parts.root, "index", *SIDE[layer])
        if "history" not in months or not rfs.exists(p):
            return None
        return f"""SELECT msgkey AS uid, msgkey, chunk, key, month, sid, ts, ts_th, role, engine, cat, '{layer}' AS layer,
                   machines, text, title, NULL::VARCHAR AS home, NULL::VARCHAR AS homes, NULL::VARCHAR AS agent
                   FROM read_parquet({sql_list([p])}) ORDER BY ts, msgkey"""
    srcs: list[str] = []
    for s in LAYERS[layer]:
        fs = [p for _, mon, p in parts.files(s) if (s == "vault" and "history" in months) or mon in months]
        if fs:
            title = "title" if s == "vault" else "NULL::VARCHAR AS title"
            have = _columns(con, fs)
            home = (f"{HOME_SQL} AS home" if "src_path" in have else "NULL::VARCHAR AS home") + ", " + \
                   ("src_agent AS agent" if "src_agent" in have else "NULL::VARCHAR AS agent")
            srcs.append(f"""SELECT regexp_extract(filename, '/parts/([^/]+)/', 1) AS machine, msgkey, chunk, key,
                coalesce(month, substr(ts_th, 1, 7)) AS month, sid, ts, ts_th, role, engine, cat, '{layer}' AS layer, text, {title}, {home}
                FROM read_parquet({sql_list(fs)}, union_by_name = true, filename = true) WHERE text IS NOT NULL AND text <> ''""")
    if not srcs:
        return None
    u = " UNION ALL BY NAME ".join(srcs)
    return f"""SELECT msgkey || CASE WHEN chunk > 0 THEN ':' || chunk ELSE '' END AS uid,
               * EXCLUDE (rn, machine, home_list) REPLACE (coalesce(home, home_list[1]) AS home),
               nullif(array_to_string(list_sort(list_distinct(home_list)), chr(10)), '') AS homes FROM (
               SELECT *, list(machine) OVER w AS machines, list(home) FILTER (WHERE home IS NOT NULL) OVER w AS home_list,
               row_number() OVER (PARTITION BY msgkey, chunk ORDER BY machine) AS rn FROM ({u})
               WINDOW w AS (PARTITION BY msgkey, chunk ORDER BY machine ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING))
               WHERE rn = 1 ORDER BY ts, msgkey, chunk"""


def _sig(parts: Parts, layer: str, months: Collection[str]) -> Json:
    """What a table was built from: per month, the manifest entry of the layer's own streams (files, sizes, mtimes,
    rows per machine), so a new tools part does not rebuild prose."""
    sig: Json = {}
    for m in months:
        p = parts.manifest_path(m)
        if rfs.exists(p):
            st = rfs.read_json(p)["streams"]
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
    rfs.makedirs(sd)
    rfs.duck(con, root)
    state_p = os.path.join(sd, "state.json")
    state = rfs.read_json(state_p) if rfs.exists(state_p) else {}
    vault = [p for _, _, p in parts.files("vault")]
    from . import gitlog, memory
    if lane == "fts":
        memory.build(root)
        gitlog.build(root)
    side_sig = {"memory": {"notes": memory.sig(root)}, "git": {"logs": gitlog.sig(root)}}
    plan: dict[str, tuple[str, list[str], Json]] = {}
    for layer in (LAYERS if lane == "fts" else ()):
        for part, ms in groups.items():
            name = f"{layer}_{part}"
            sig = _sig(parts, layer, ms) | ({"vault": [rfs.getmtime(p) for p in vault]} if layer == "prose" and part == "history" else {})
            if layer in SIDE:
                if part != "history" or not next(iter(side_sig[layer].values())):   # no notes / no logs pushed: no table
                    continue
                sig = side_sig[layer]
            sig = json.loads(json.dumps(sig))
            if force or state.get(name, {}).get("sig") != sig or name not in current(root):
                plan[name] = (layer, ms + (["history"] if part == "history" else []), sig)
    from . import vec as V
    for model in (V.models(root) if lane == "vectors" else ()):
        layer = "vec_" + V.slug(model)
        sm = V.shard_months(root, model, con, parts)
        sizes = {os.path.basename(f): rfs.getsize(f) for f in V.shards(root, model)}
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
    db = rfs.lancedb_connect(gdir)
    cur = dict(current(root))
    done = []
    for name, (layer, ms, sig) in plan.items():
        t = time.time()
        is_vec = layer.startswith("vec:")
        sql = V.table_sql(parts, root, layer[4:], ms) if is_vec else _select(parts, layer, ms, con)
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
    if rfs.exists(state_p):
        state = {k: v for k, v in rfs.read_json(state_p).items() if (k.startswith("vec_")) != (lane == "vectors")} | {k: v for k, v in state.items() if (k.startswith("vec_")) == (lane == "vectors")}
    for p, obj in ((state_p, state), (os.path.join(sd, "current.json"), cur)):   # current.json last: the publish point
        rfs.write_json(p, obj, indent=1)
    _prune(sd, cur)
    return done


def _prune(sd: str, cur: dict[str, str]) -> None:
    live = {v.split("/")[0] for v in cur.values()}
    names = [d for d in rfs.listdir(sd) if d[:8].isdigit() and rfs.isdir(os.path.join(sd, d))]
    # by age on disk, not by name, where a folder has an age; on S3 a prefix has none, and the names are UTC times
    gens = names if rfs.is_s3(sd) else sorted(names, key=lambda d: rfs.getmtime(os.path.join(sd, d)))
    for g in sorted(gens)[:-KEEP] if rfs.is_s3(sd) else gens[:-KEEP]:
        if g not in live:
            rfs.rmtree(os.path.join(sd, g))


class Index:
    """The published tables, reopened when current.json changes (a new generation)."""
    seen: float | None                       # current.json's mtime when the tables were opened
    tables: "dict[str, lancedb.table.Table]"
    _mx: "dict[str, Matrix]"                # vector matrices of generation _mx_seen, made on first use
    _mx_seen: float | None

    def __init__(self, root: str) -> None:
        self.root = rfs.root_of(root)
        self.seen, self.tables = None, {}

    def _load(self) -> "dict[str, lancedb.table.Table]":
        p = os.path.join(search_dir(self.root), "current.json")
        m = rfs.getmtime(p) if rfs.exists(p) else None
        if m != self.seen:
            import lancedb
            cur = current(self.root)
            tabs: dict[str, lancedb.table.Table] = {}
            missing: list[str] = []
            for name, rel in cur.items():
                gen, fname = rel.split("/")
                try:   # a table current.json names but the folder lacks (a copy caught mid-publish): serve the rest
                    tabs[name] = rfs.lancedb_connect(os.path.join(search_dir(self.root), gen)).open_table(fname[:-6])
                except (ValueError, OSError, FileNotFoundError):
                    missing.append(name)
            self.tables, self.seen, self.missing = tabs, m, missing
        return self.tables
        return self.tables

    def has_column(self, col: str) -> bool:
        tabs = self._load()
        return bool(tabs) and all(col in t.schema.names for n, t in tabs.items() if not n.startswith("vec_"))

    def built(self) -> bool:
        return bool(self._load())

    def matrices(self, model: str) -> "list[Matrix]":
        """The in-memory vector matrices (open, history) of one model, made on first use per generation."""
        from . import vec as V
        tabs = self._load()
        # one builder at a time: a hub's first page asks several routes at once, and each thread built its own copy of
        # the same 3.4 GB matrix (white's serve peaked at 38 GB after a restart, 2026-10-25)
        with _MX_LOCK:
            if getattr(self, "_mx_seen", None) != self.seen:
                self._mx, self._mx_seen = {}, self.seen
            out: list[V.Matrix] = []
            for part in ("open", "history"):
                name = f"vec_{V.slug(model)}_{part}"
                if name not in tabs:
                    continue
                if name not in self._mx:
                    self._mx[name] = V.Matrix(tabs[name])
                out.append(self._mx[name])
            return out

    def vector(self, model: str, vector: Sequence[float], filt: "VecFilter", limit: int) -> list[Json]:
        from . import perf
        t0 = time.perf_counter()
        out = self._vector_untimed(model, vector, filt, limit)
        perf.query("vector", (time.perf_counter() - t0) * 1000, len(out), f'model {model}', name="Index.vector")
        return out

    def _vector_untimed(self, model: str, vector: Sequence[float], filt: "VecFilter", limit: int) -> list[Json]:
        """Nearest prose rows to a unit query vector: exact, in memory (vec.Matrix), best first; _score = cosine."""
        out: list[Json] = []
        for mx in self.matrices(model):
            out += mx.search(vector, filt, limit)
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
            have = set(tb.schema.names)
            out += qb.select([c for c in COLS + HOME_COLS if c in have] + ["_score"]).to_list()
        out.sort(key=lambda r: (-r["_score"], r["ts"] or ""))
        return out[:limit]

    def count(self, layer: str, q: str, cap: int) -> int:
        """Rows of one layer (history + open) that match q, counted up to cap: a term's document frequency."""
        n = 0
        for part in ("open", "history"):
            tb = self._load().get(f"{layer}_{part}")
            if tb is not None:
                n += len(tb.search(q, query_type="fts").limit(cap).select(["uid", "_score"]).to_arrow())
        return min(n, cap)

    def size(self, layer: str) -> int:
        """Rows in one layer's BM25 tables (history + open)."""
        return sum(tb.count_rows() for part in ("open", "history") if (tb := self._load().get(f"{layer}_{part}")) is not None)

    def query(self, layer: str, q: str, where: str | None, limit: int) -> list[Json]:
        from . import perf
        t0 = time.perf_counter()
        out = self._query_untimed(layer, q, where, limit)
        perf.query("bm25", (time.perf_counter() - t0) * 1000, len(out), f'{layer}: {q}', name=f"Index.query {layer}")
        return out

    def _query_untimed(self, layer: str, q: str, where: str | None, limit: int) -> list[Json]:
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
