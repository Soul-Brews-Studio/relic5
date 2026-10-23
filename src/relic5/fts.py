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

from .parts import Parts, sql_list, this_month

FTS_SETTINGS = dict(base_tokenizer="icu", stem=False, remove_stop_words=False, max_token_length=128)
LAYERS = {"prose": ("text", "vault"), "tools": ("tools",), "thinking": ("thinking",)}
COLS = ["uid", "msgkey", "chunk", "key", "month", "sid", "ts", "ts_th", "role", "engine", "cat", "layer", "machines", "text", "title"]
KEEP = 3


def search_dir(root):
    return os.path.join(root, "index", "_search")


def current(root):
    p = os.path.join(search_dir(root), "current.json")
    return json.load(open(p)) if os.path.exists(p) else {}


def _select(parts, layer, months):
    """SQL for the folded rows of one layer over some months (vault, a single file, goes to history)."""
    srcs = []
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


def _sig(parts, layer, months):
    """What a table was built from: per month, the manifest entry of the layer's own streams (files, sizes, mtimes,
    rows per machine), so a new tools part does not rebuild prose."""
    sig = {}
    for m in months:
        p = parts.manifest_path(m)
        if os.path.exists(p):
            st = json.load(open(p))["streams"]
            sig[m] = {s: st[s] for s in LAYERS[layer] if s in st}
    return sig


def build(root, con, log=print, now=None, force=False):
    """Rebuild every table whose months changed; publish one new generation. Returns the tables rebuilt."""
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
    plan = {}
    for layer in LAYERS:
        for part, ms in groups.items():
            name = f"{layer}_{part}"
            sig = _sig(parts, layer, ms) | ({"vault": [os.path.getmtime(p) for p in vault]} if layer == "prose" and part == "history" else {})
            sig = json.loads(json.dumps(sig))
            if force or state.get(name, {}).get("sig") != sig or name not in current(root):
                plan[name] = (layer, ms + (["history"] if part == "history" else []), sig)
    if not plan:
        return []
    gen = time.strftime("%Y%m%d-%H%M%S")
    gdir = os.path.join(sd, gen)
    db = lancedb.connect(gdir)
    cur = dict(current(root))
    done = []
    for name, (layer, ms, sig) in plan.items():
        t = time.time()
        sql = _select(parts, layer, ms)
        tab = con.execute(sql).arrow() if sql else None
        if hasattr(tab, "read_all"):
            tab = tab.read_all()
        if tab is None or tab.num_rows == 0:
            cur.pop(name, None)
            state[name] = {"sig": sig, "rows": 0, "built": gen}
            continue
        tb = db.create_table(name, tab, mode="overwrite")
        tb.create_index("text", config=FTS(**FTS_SETTINGS), replace=True)
        cur[name] = f"{gen}/{name}.lance"
        state[name] = {"sig": sig, "rows": tab.num_rows, "built": gen, "seconds": round(time.time() - t, 1)}
        done.append(name)
        log(f"fts {name}: {tab.num_rows:,} rows ({time.time() - t:.1f}s)")
    for p, obj in ((state_p, state), (os.path.join(sd, "current.json"), cur)):   # current.json last: the publish point
        with open(p + ".tmp", "w") as f:
            json.dump(obj, f, indent=1)
        os.replace(p + ".tmp", p)
    _prune(sd, cur)
    return done


def _prune(sd, cur):
    live = {v.split("/")[0] for v in cur.values()}
    gens = sorted(d for d in os.listdir(sd) if os.path.isdir(os.path.join(sd, d)) and d[:8].isdigit())
    for g in gens[:-KEEP]:
        if g not in live:
            shutil.rmtree(os.path.join(sd, g))


class Index:
    """The published tables, reopened when current.json changes (a new generation)."""

    def __init__(self, root):
        self.root = os.path.abspath(os.path.expanduser(root))
        self.seen, self.tables = None, {}

    def _load(self):
        p = os.path.join(search_dir(self.root), "current.json")
        m = os.path.getmtime(p) if os.path.exists(p) else None
        if m != self.seen:
            import lancedb
            cur = current(self.root)
            tabs = {}
            for name, rel in cur.items():
                gen, fname = rel.split("/")
                tabs[name] = lancedb.connect(os.path.join(search_dir(self.root), gen)).open_table(fname[:-6])
            self.tables, self.seen = tabs, m
        return self.tables

    def built(self):
        return bool(self._load())

    def query(self, layer, q, where, limit):
        """BM25 hits of one layer (history + open), best first."""
        out = []
        for part in ("open", "history"):
            tb = self._load().get(f"{layer}_{part}")
            if tb is None:
                continue
            qb = tb.search(q, query_type="fts").limit(limit)
            if where:
                qb = qb.where(where, prefilter=True)
            out += qb.select(COLS + ["_score"]).to_list()
        out.sort(key=lambda r: (-r["_score"], r["ts"] or ""), reverse=False)
        return out[:limit]
