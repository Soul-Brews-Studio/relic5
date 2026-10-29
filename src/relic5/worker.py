"""worker.py: `relic5 embed` on a client. Asks the hub which chunks have no vector, embeds them here, ships a shard.

  relic5 embed --probe [--n 200]        parity: re-embed n keys the hub already has; cosine of each with the stored vector
  relic5 embed [--engine auto|ane|ane2|mps|gb300] [--limit 5000] [--prefix 0-7]   auto = the policy ([embed] in
                                        ~/.config/relic5/config.toml): backlog > 50,000 -> gb300, else ane. Embeds missing
                                        chunks (newest first), rsyncs a shard, then
                                        `relic5 index --vectors` on the hub. --prefix: take only keys starting with one
                                        of these hex digits, so two workers (m5, gb300) never take the same key

Shard: vectors/<model@hash>/<machine>-<engine>-<run>.parquet (key, vector) with parquet key-value metadata
engine / precision / machine / at, and one embed job in the hub's jobs.jsonl (via `relic5 index --vectors`).
Engines (Nat, 2026-10-23: "sometimes m5, sometimes gb300, sometimes ANE"): mps (here, float32), gb300 (relic4's
remote_embed, bf16), ane (ANEEmbedBar 11435: other prompts, so its own model@hash unless the probe says otherwise).
ane2 (ane2.py: ANEEmbedBar's packages in-process on the Neural Engine + float32 on the GPU, two processes; no app).
"""
import json, os, socket, subprocess, sys, time, urllib.parse, urllib.request
from typing import Callable, TypedDict

from .encode import encode
from .types_ import Json
from . import store as rfs

HUB = os.environ.get("RELIC5_HUB_SSH", "nat@white.follow-rankine.ts.net")
RELIC4 = os.environ.get("RELIC5_RELIC4", "/opt/Code/github.com/Soul-Brews-Studio/agent-relic-v4")
CONFIG = os.path.expanduser(os.environ.get("RELIC5_CONFIG", "~/.config/relic5/config.toml"))
# Nat, 2026-10-23: "all data huge go gb300, this month (smaller) ANE from m5". Overridden by [embed] in CONFIG.
class Policy(TypedDict):
    backlog_gb300: int
    small: str
    big: str
    query: list[str]


class Probe(TypedDict):
    n: int
    min: float
    p05: float
    mean: float
    texts_per_s: float | None


POLICY: Policy = {"backlog_gb300": 50000, "small": "ane", "big": "gb300", "query": ["ane", "mps"]}


def policy() -> Policy:
    p = POLICY.copy()
    if rfs.exists(CONFIG):
        import tomllib
        p |= tomllib.load(open(CONFIG, "rb")).get("embed", {})
    return p


def choose(pending: int, p: Policy | None = None) -> tuple[str, str]:
    """-> (engine, why): a big backlog goes to gb300, an increment to the small engine (ANE on m5)."""
    p = p or policy()
    if pending > p["backlog_gb300"]:
        return p["big"], f"backlog {pending:,} > {p['backlog_gb300']:,}: {p['big']}"
    return p["small"], f"increment {pending:,}: {p['small']}"


def gb300(rows: list[Json], model: str) -> list[list[float]]:
    """relic4's remote_embed (agent-relic-v4 src/relic4/embed.py, PR #6 @b399119): gb300 GPU, bf16, 100k texts a round
    trip, resumable. Run in relic4's own venv with a scratch RELIC4_ROOT, so its shards land here, not in relic4's cache."""
    import tempfile, pyarrow as pa, pyarrow.parquet as pq
    d = tempfile.mkdtemp(prefix="relic5-gb300-")
    # relic4 rsyncs each result shard into RELIC4_ROOT/vec/_cache/<model@hash>/ and does not create that folder:
    # without it every run failed at the rsync (exit 3) after gb300 had done the work (2026-10-29)
    os.makedirs(os.path.join(d, "vec", "_cache", model), exist_ok=True)
    src = os.path.join(d, "missing.parquet")
    pq.write_table(pa.table({"key": [r["key"] for r in rows], "text": [r["text"] for r in rows]}), src)
    out = subprocess.run([os.path.join(RELIC4, ".venv/bin/python"), "-c",
                          "import json,sys; from relic4.embed import remote_embed; print(json.dumps(remote_embed(sys.argv[1], 'unsloth/embeddinggemma-300m')))", src],
                         env=dict(os.environ, RELIC4_ROOT=d), capture_output=True, text=True, check=True)
    shards = json.loads(out.stdout.strip().splitlines()[-1])
    vec: dict[str, list[float]] = {}
    for sh in shards:
        t = pq.read_table(sh)
        vec.update(zip(t.column("key").to_pylist(), t.column("vector").to_pylist()))
    return [vec[r["key"]] for r in rows]


def _get(url: str, path: str, **q: str | int) -> Json:
    with urllib.request.urlopen(f"{url}{path}?{urllib.parse.urlencode(q)}", timeout=300) as r:
        res: Json = json.load(r)
        return res


def probe(url: str, model: str, n: int = 200, engine: str = "mps") -> Probe:
    """Re-embed n texts whose vectors the hub holds (from the seed); compare. -> {min, p05, mean}."""
    rows = _get(url, "/api/probe", model=model, n=n)["rows"]
    t = time.time()
    mine = encode([r["text"] for r in rows], model, kind="document", engine=engine)
    secs = time.time() - t
    cos = sorted(sum(a * b for a, b in zip(m, r["vector"])) for m, r in zip(mine, rows))
    return {"n": len(cos), "min": round(cos[0], 4), "p05": round(cos[len(cos) // 20], 4), "mean": round(sum(cos) / len(cos), 4),
            "texts_per_s": round(len(cos) / secs, 1) if secs else None}


PARITY = os.path.expanduser("~/.cache/relic5/parity.json")
PARITY_TTL_S = 86400


def parity_fresh(model: str, engine: str, now: float | None = None) -> bool:
    """A passed parity probe for this engine and model in the last day (the probe cost 6 s of every embed)."""
    try:
        at = float(rfs.read_json(PARITY)[f"{model}|{engine}"]["at"])
    except (OSError, ValueError, KeyError, TypeError):
        return False
    return (now or time.time()) - at < PARITY_TTL_S


def parity_ok(model: str, engine: str, p05: float) -> None:
    try:
        d: dict[str, Json] = rfs.read_json(PARITY)
    except (OSError, ValueError):
        d = {}
    d[f"{model}|{engine}"] = {"at": time.time(), "p05": p05}
    os.makedirs(os.path.dirname(PARITY), exist_ok=True)
    with open(PARITY + ".tmp", "w") as f:
        json.dump(d, f)
    os.replace(PARITY + ".tmp", PARITY)


def note(state: str, message: str, **kw: object) -> None:
    """One JobEvent in the hub's logs/jobs.jsonl: the policy decision and the outcome."""
    ev = {"job": f"embed-{socket.gethostname().split('.')[0].lower()}-{os.getpid()}", "verb": "embed", "state": state,
          "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "pid": os.getpid(), "host": socket.gethostname(), "message": message, **kw}
    subprocess.run(["ssh", "-o", "BatchMode=yes", HUB, "mkdir -p ~/relic5/logs && cat >> ~/relic5/logs/jobs.jsonl"],
                   input=json.dumps(ev) + "\n", text=True, timeout=30)


def run(url: str, model: str, limit: int = 5000, prefixes: str = "", engine: str = "mps",
        log: Callable[[str], object] = print, rows: list[Json] | None = None) -> int:
    import pyarrow as pa, pyarrow.parquet as pq
    t0 = time.time()
    if rows is None:
        rows = []
        for p in (prefixes.split(",") if prefixes else [""]):
            rows += _get(url, "/api/missing", model=model, limit=limit, prefix=p)["rows"]
    rows = rows[:limit]
    if not rows:
        log("embed: nothing missing")
        return 0
    vecs = gb300(rows, model) if engine == "gb300" else encode([r["text"] for r in rows], model, kind="document", engine=engine)
    me = socket.gethostname().split(".")[0].lower()
    run_id = time.strftime("%Y%m%d-%H%M%S")
    name = f"{me}-{engine}-{run_id}.parquet"
    tmp = os.path.join(os.environ.get("TMPDIR", "/tmp"), name)
    tab = pa.table({"key": [r["key"] for r in rows], "vector": pa.array(vecs, type=pa.list_(pa.float32()))})
    tab = tab.replace_schema_metadata({"engine": engine, "precision": {"mps": "float32", "ane": "w8a16", "ane2": "w8a16+float32", "gb300": "bfloat16"}.get(engine, engine),
                                       "machine": me, "at": time.strftime("%FT%T%z"), "model": model})
    pq.write_table(tab, tmp)
    dest = f"relic5/vectors/{model}/"
    subprocess.run(["rsync", "-a", "--timeout=120", tmp, f"{HUB}:{dest}.{name}"], check=True)
    # publish by rename on the hub, so the index never reads half a shard
    # the vector tables rebuild on the hub after this returns (index --wait queues behind a running one); waiting
    # here made a 100-chunk embed a 60 s step (2026-10-24). RELIC5_EMBED_WAIT=1 keeps the old, blocking behaviour.
    index = "cd ~/relic5/app && docker compose run --rm index relic5 index --root /data --vectors --wait >/dev/null 2>&1"
    if os.environ.get("RELIC5_EMBED_WAIT") != "1":
        index = f"nohup sh -c '{index}' >/dev/null 2>&1 </dev/null &"
    subprocess.run(["ssh", "-o", "BatchMode=yes", HUB, f"mv ~/{dest}.{name} ~/{dest}{name} && {index}"], check=True)
    os.remove(tmp)
    log(f"embed: {len(rows):,} chunks on {engine} in {time.time() - t0:.0f}s -> {dest}{name}")
    return len(rows)


def main(args: list[str]) -> None:
    from .cli import URL, _opt
    model = _opt(args, "--model", "unsloth--embeddinggemma-300m@806f5f90")
    engine = _opt(args, "--engine", "auto")
    if "--probe" in args:
        engine = "mps" if engine == "auto" else engine
        r = probe(URL, model, int(_opt(args, "--n", "200")), engine)
        print(f"parity {model} on {engine} ({r['texts_per_s']} texts/s) vs stored: n={r['n']} min={r['min']} p05={r['p05']} mean={r['mean']} "
              f"({'OK, > 0.99' if r['p05'] > 0.99 else 'NOT OK: these vectors need their own model@hash'})")
        return
    limit = int(_opt(args, "--limit", "5000"))
    prefix = _opt(args, "--prefix", "")
    why = None
    first: Json | None = None
    if engine == "auto":
        first = _get(URL, "/api/missing", model=model, limit=limit)    # the count and the rows in one call
        pending = int(first["pending"])
        if not pending:
            print("embed: nothing missing")
            return
        engine, why = choose(pending)
        print(f"embed policy: {why}")
        if engine == policy()["big"]:
            limit, first = max(limit, pending), None
    note("start", why or f"engine {engine} (asked)", engine=engine)
    # an engine ships into a model@hash folder only when its vectors match the ones there (relic3 6a6d9d8: an --also
    # engine is admitted at cos median >= 0.998, min >= 0.99); exit 3 = parity refused, as relic3 embed
    if engine != "gb300" and not parity_fresh(model, engine):   # gb300 made the stored vectors: it is the reference
        r = probe(URL, model, 50, engine)
        if r["n"] and r["p05"] > 0.99:
            parity_ok(model, engine, r["p05"])
        if r["n"] and r["p05"] <= 0.99:
            note("error", f"parity refused on {engine}: p05 {r['p05']}", rc=3)
            sys.exit(print(f"parity refused: {model} here p05={r['p05']} (want > 0.99); use a model@hash of its own", file=sys.stderr) or 3)
    try:
        n = run(URL, model, limit, prefix, engine, rows=first["rows"] if first is not None and not prefix else None)
    except Exception as ex:
        note("error", f"{engine}: {type(ex).__name__}: {ex}"[:300], rc=1)
        raise
    note("done", f"{n:,} chunks on {engine}", rc=0, done=n, unit="chunks")
