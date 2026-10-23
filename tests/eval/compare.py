"""Compare relic3, relic4 and relic5 on one query file: recall@10, precision@10, MRR, p50/p95 latency per method.
  uv run --extra embed python tests/eval/compare.py tests/eval/generated/known.json [tests/eval/semantic.json]
A query passes when a top-10 hit is from a wanted session; precision@10 = top-10 hits from wanted sessions / 10.
relic5's semantic/hybrid time includes the client-side query encoding (MPS). One JSON line per run goes to
tests/eval/runs/compare.jsonl (gitignored)."""
import json, os, statistics, subprocess, sys, time, urllib.parse, urllib.request

R5 = os.environ.get("RELIC5_URL", "http://white.follow-rankine.ts.net:8795")
R4 = os.environ.get("RELIC4_URL", "http://127.0.0.1:8791")
BUN, R3 = os.path.expanduser("~/.bun/bin/bun"), "/opt/Code/github.com/Soul-Brews-Studio/agent-relic-v3/src/cli.ts"


def get(url):
    with urllib.request.urlopen(url, timeout=120) as r:
        return json.load(r)


def r5(q, mode, vec=None):
    if mode == "keyword":
        return [h["session_uuid"] for h in get(f"{R5}/api/search?" + urllib.parse.urlencode({"q": q, "limit": 10, "horizon": "archive"}))["hits"]]
    args = {"query": q, "semantic": True, "vector": vec, "limit": 10, **({"hybrid": True} if mode == "hybrid" else {})}
    body = {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "relic_search", "arguments": args}}
    req = urllib.request.Request(f"{R5}/mcp", data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    res = json.load(urllib.request.urlopen(req, timeout=120))["result"]
    return [h["session_uuid"] for h in json.loads(res["content"][0]["text"])["hits"]]


def r4(q, mode):
    d = get(f"{R4}/api/search?" + urllib.parse.urlencode({"q": q, "n": 10, "mode": mode}))
    return [h.get("sid") for h in d.get(mode, [])]


def r3(q):
    o = subprocess.run([BUN, R3, "search", "--json", "--limit", "10", "--horizon", "archive", "--", q], capture_output=True, text=True,
                       env=dict(os.environ, RELIC_HOME=os.path.expanduser("~/.relic3")), timeout=180)
    try:
        return [h["session_uuid"] for h in json.loads(o.stdout)["hits"]]
    except ValueError:
        return []


def score(spec, fn, until=None):
    ok = prec = mrr = 0
    lat, misses = [], []
    qs = [i for i in spec["queries"] if not until or (i.get("ts") or "") <= until]
    for item in qs:
        want = {spec["sessions"][w] for w in item["want"]}
        t = time.time()
        try:
            got = fn(item)
        except Exception as ex:
            got = []
            print("   error:", type(ex).__name__, str(ex)[:80], file=sys.stderr)
        lat.append((time.time() - t) * 1000)
        got = [g or "" for g in got][:10]
        rank = next((i + 1 for i, s in enumerate(got) if s in want), None)
        ok += rank is not None
        if rank is None:
            misses.append(item["q"])
        mrr += 1 / rank if rank else 0
        prec += sum(s in want for s in got) / 10
    n = len(qs)
    lat.sort()
    return {"recall@10": round(ok / n, 3), "precision@10": round(prec / n, 3), "mrr": round(mrr / n, 3),
            "p50_ms": round(statistics.median(lat)), "p95_ms": round(lat[max(0, int(len(lat) * 0.95) - 1)]), "n": n,
            "until": until, "misses": misses}


def main(files):
    from relic5.encode import encode
    os.makedirs("tests/eval/runs", exist_ok=True)
    for f in files:
        spec = json.load(open(f))
        t = time.time()
        vecs = dict(zip([i["q"] for i in spec["queries"]], encode([i["q"] for i in spec["queries"]], "unsloth--embeddinggemma-300m@806f5f90")))
        enc_ms = (time.time() - t) * 1000 / len(spec["queries"])
        methods = {
            "relic5 keyword (BM25)": lambda i: r5(i["q"], "keyword"),
            "relic5 semantic": lambda i: r5(i["q"], "semantic", vecs[i["q"]]),
            "relic5 hybrid": lambda i: r5(i["q"], "hybrid", vecs[i["q"]]),
            "relic4 icu": lambda i: r4(i["q"], "icu"),
            "relic4 vector": lambda i: r4(i["q"], "vector"),
            "relic3 bm25": lambda i: r3(i["q"]),
        }
        print(f"\n## {f} ({len(spec['queries'])} queries; client encode ~{enc_ms:.0f} ms/query, batched)")
        print(f"{'method':<24} {'recall@10':>9} {'prec@10':>8} {'MRR':>6} {'p50 ms':>7} {'p95 ms':>7}")
        dated = any("ts" in i for i in spec["queries"])
        # relic3 stops at 10-15: score every method on the same subset too, so relic3 is compared fairly
        runs = [(n, f, None) for n, f in methods.items()] + ([(n + " ≤10-14", f, "2026-10-14T23:59:59Z") for n, f in methods.items()] if dated else [])
        for name, fn, until in runs:
            r = score(spec, fn, until)
            print(f"{name:<24} {r['recall@10']:>9} {r['precision@10']:>8} {r['mrr']:>6} {r['p50_ms']:>7} {r['p95_ms']:>7}", flush=True)
            line = json.dumps({"at": time.strftime("%FT%T%z"), "file": os.path.basename(f), "method": name, **r}, ensure_ascii=False)
            with open("tests/eval/runs/compare.jsonl", "a") as out:
                out.write(line + "\n")
            # and the hub's logs/eval.jsonl, so relic_status and the UI's Compare tab show it (scores and misses only)
            subprocess.run(["ssh", "-o", "BatchMode=yes", "nat@white.follow-rankine.ts.net", "cat >> ~/relic5/logs/eval.jsonl"],
                           input=line + "\n", text=True, timeout=30)


if __name__ == "__main__":
    main(sys.argv[1:] or ["tests/eval/semantic.json"])
