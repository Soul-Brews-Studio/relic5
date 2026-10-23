"""evaluate.py: `relic5 eval tests/eval/semantic.json [--semantic] [--url URL]`: recall@10 of a query file against the
hub, over HTTP like any client. A query passes when any session it wants is among the top-10 hits' sessions."""
import json, os, sys, urllib.parse, urllib.request


def run(path, semantic=False, url=None, limit=10):
    spec = json.load(open(path))
    url = (url or os.environ.get("RELIC5_URL", "http://white.follow-rankine.ts.net:8795")).rstrip("/")
    ok, rows = 0, []
    for item in spec["queries"]:
        p = {"q": item["q"], "limit": limit, "horizon": "archive"}
        if semantic:
            p["semantic"] = "1"
        with urllib.request.urlopen(f"{url}/api/search?{urllib.parse.urlencode(p)}", timeout=120) as r:
            hits = json.load(r)["hits"]
        got = [h["session_uuid"] for h in hits]
        want = {spec["sessions"][w] for w in item["want"]}
        rank = next((i + 1 for i, s in enumerate(got) if s in want), None)
        ok += rank is not None
        rows.append({"q": item["q"], "rank": rank})
    return {"recall@10": round(ok / len(spec["queries"]), 3), "passed": ok, "queries": len(spec["queries"]),
            "mode": "semantic" if semantic else "keyword", "rows": rows}


def main(args):
    sem = "--semantic" in args
    args = [a for a in args if a != "--semantic"]
    r = run(args[0] if args else "tests/eval/semantic.json", semantic=sem)
    for x in r["rows"]:
        print(f"  {'rank ' + str(x['rank']) if x['rank'] else 'miss':<8} {x['q']}")
    print(f"{r['mode']} recall@10 = {r['recall@10']} ({r['passed']}/{r['queries']})")
    return r
