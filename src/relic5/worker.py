"""worker.py: `relic5 embed` on a client. Asks the hub which chunks have no vector, embeds them here, ships a shard.

  relic5 embed --probe [--n 200]        parity: re-embed n keys the hub already has; cosine of each with the stored vector
  relic5 embed [--limit 5000] [--prefix 0-7]   embed up to limit missing chunks (newest first), rsync a shard, then
                                        `relic5 index --vectors` on the hub. --prefix: take only keys starting with one
                                        of these hex digits, so two workers (m5, gb300) never take the same key

Shard: vectors/<model@hash>/<machine>-<engine>-<run>.parquet (key, vector) with parquet key-value metadata
engine / precision / machine / at, and one embed job in the hub's jobs.jsonl (via `relic5 index --vectors`).
Engines (Nat, 2026-10-23: "sometimes m5, sometimes gb300, sometimes ANE"): mps (here, float32), gb300 (relic4's
remote_embed, bf16), ane (ANEEmbedBar 11435: other prompts, so its own model@hash unless the probe says otherwise).
"""
import json, os, socket, subprocess, sys, time, urllib.parse, urllib.request

from .encode import encode

HUB = os.environ.get("RELIC5_HUB_SSH", "nat@white.follow-rankine.ts.net")


def _get(url, path, **q):
    with urllib.request.urlopen(f"{url}{path}?{urllib.parse.urlencode(q)}", timeout=300) as r:
        return json.load(r)


def probe(url, model, n=200):
    """Re-embed n texts whose vectors the hub holds (from the seed); compare. -> {min, p05, mean}."""
    import duckdb
    rows = _get(url, "/api/probe", model=model, n=n)["rows"]
    mine = encode([r["text"] for r in rows], model, kind="document")
    cos = sorted(sum(a * b for a, b in zip(m, r["vector"])) for m, r in zip(mine, rows))
    return {"n": len(cos), "min": round(cos[0], 4), "p05": round(cos[len(cos) // 20], 4), "mean": round(sum(cos) / len(cos), 4)}


def run(url, model, limit=5000, prefixes="", engine="mps", log=print):
    import pyarrow as pa, pyarrow.parquet as pq
    t0 = time.time()
    rows = []
    for p in (prefixes.split(",") if prefixes else [""]):
        rows += _get(url, "/api/missing", model=model, limit=limit, prefix=p)["rows"]
    rows = rows[:limit]
    if not rows:
        log("embed: nothing missing")
        return 0
    vecs = encode([r["text"] for r in rows], model, kind="document")
    me = socket.gethostname().split(".")[0].lower()
    run_id = time.strftime("%Y%m%d-%H%M%S")
    name = f"{me}-{engine}-{run_id}.parquet"
    tmp = os.path.join(os.environ.get("TMPDIR", "/tmp"), name)
    tab = pa.table({"key": [r["key"] for r in rows], "vector": pa.array(vecs, type=pa.list_(pa.float32()))})
    tab = tab.replace_schema_metadata({"engine": engine, "precision": "float32" if engine == "mps" else engine,
                                       "machine": me, "at": time.strftime("%FT%T%z"), "model": model})
    pq.write_table(tab, tmp)
    dest = f"relic5/vectors/{model}/"
    subprocess.run(["rsync", "-a", "--timeout=120", tmp, f"{HUB}:{dest}.{name}"], check=True)
    # publish by rename on the hub, so the index never reads half a shard
    subprocess.run(["ssh", "-o", "BatchMode=yes", HUB, f"mv ~/{dest}.{name} ~/{dest}{name} && "
                    f"cd ~/relic5/app && docker compose run --rm index relic5 index --root /data --vectors >/dev/null 2>&1"], check=True)
    os.remove(tmp)
    log(f"embed: {len(rows):,} chunks on {engine} in {time.time() - t0:.0f}s -> {dest}{name}")
    return len(rows)


def main(args):
    from .cli import URL, _opt
    model = _opt(args, "--model", "unsloth--embeddinggemma-300m@806f5f90")
    if "--probe" in args:
        r = probe(URL, model, int(_opt(args, "--n", "200")))
        print(f"parity {model} on mps vs stored: n={r['n']} min={r['min']} p05={r['p05']} mean={r['mean']} "
              f"({'OK, > 0.99' if r['p05'] > 0.99 else 'NOT OK: these vectors need their own model@hash'})")
        return
    # an engine ships into a model@hash folder only when its vectors match the ones there (relic3 6a6d9d8: an --also
    # engine is admitted at cos median >= 0.998, min >= 0.99); exit 3 = parity refused, as relic3 embed
    r = probe(URL, model, 50)
    if r["n"] and r["p05"] <= 0.99:
        sys.exit(print(f"parity refused: {model} here p05={r['p05']} (want > 0.99); use a model@hash of its own", file=sys.stderr) or 3)
    run(URL, model, int(_opt(args, "--limit", "5000")), _opt(args, "--prefix", ""), _opt(args, "--engine", "mps"))
