"""evaluate.py: `relic5 eval tests/eval/semantic.json [--semantic] [--url URL]`: recall@10 of a query file against the
hub, over HTTP like any client. A query passes when any session it wants is among the top-10 hits' sessions."""
import json, os, sys, urllib.parse, urllib.request


def _post(url, q, vector, limit, hybrid=False):
    body = {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "relic_search", "arguments": {
        "query": q, "semantic": True, "vector": vector, "limit": limit, **({"hybrid": True} if hybrid else {})}}}
    req = urllib.request.Request(f"{url}/mcp", data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as r:
        res = json.load(r)["result"]
    if res.get("isError"):
        raise SystemExit(res["content"][0]["text"])
    return json.loads(res["content"][0]["text"])["hits"]


def run(path, semantic=False, url=None, limit=10, model="unsloth--embeddinggemma-300m@806f5f90", hybrid=False):
    spec = json.load(open(path))
    url = (url or os.environ.get("RELIC5_URL", "http://white.follow-rankine.ts.net:8795")).rstrip("/")
    ok, rows = 0, []
    vecs = {}
    if semantic:
        from .encode import encode
        vecs = dict(zip([i["q"] for i in spec["queries"]], encode([i["q"] for i in spec["queries"]], model)))
    for item in spec["queries"]:
        if semantic:
            hits = _post(url, item["q"], vecs[item["q"]], limit, hybrid)
        else:
            p = {"q": item["q"], "limit": limit, "horizon": "archive"}
            with urllib.request.urlopen(f"{url}/api/search?{urllib.parse.urlencode(p)}", timeout=120) as r:
                hits = json.load(r)["hits"]
        got = [h["session_uuid"] for h in hits]
        want = {spec["sessions"][w] for w in item["want"]}
        rank = next((i + 1 for i, s in enumerate(got) if s in want), None)
        ok += rank is not None
        rows.append({"q": item["q"], "rank": rank})
    mrr = sum(1 / x["rank"] for x in rows if x["rank"]) / len(rows)
    return {"recall@10": round(ok / len(spec["queries"]), 3), "mrr": round(mrr, 3), "passed": ok, "queries": len(spec["queries"]),
            "mode": ("hybrid" if hybrid else "semantic") if semantic else "keyword", "rows": rows}


def main(args):
    sem, hyb = "--semantic" in args or "--hybrid" in args, "--hybrid" in args
    args = [a for a in args if a not in ("--semantic", "--hybrid")]
    r = run(args[0] if args else "tests/eval/semantic.json", semantic=sem, hybrid=hyb)
    for x in r["rows"]:
        print(f"  {'rank ' + str(x['rank']) if x['rank'] else 'miss':<8} {x['q']}")
    print(f"{r['mode']} recall@10 = {r['recall@10']} ({r['passed']}/{r['queries']}) · MRR {r['mrr']}")
    # every run is kept: the measurement over time (Nat: "keep measurement precision and recall")
    import time
    os.makedirs("tests/eval/runs", exist_ok=True)
    with open("tests/eval/runs/results.jsonl", "a") as f:
        f.write(json.dumps({"at": time.strftime("%FT%T%z"), "file": args[0] if args else "tests/eval/semantic.json",
                            **{k: r[k] for k in ("mode", "recall@10", "mrr", "passed", "queries")}, "rows": r["rows"]}, ensure_ascii=False) + "\n")
    return r
