"""selfknow.py: the query log read by time, not by a fixed number of bytes."""
import json, os, time

from relic5 import selfknow


def test_searched_most_survives_big_eval_lines(root):
    """2026-10-26: eval runs logged large lines (their top hits); a fixed 2 MB read held only minutes of the log and
    "Searched most" showed one query. The reader goes back by time (7 days), however many bytes that takes."""
    os.makedirs(os.path.join(root, "logs"), exist_ok=True)
    at = lambda s: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - s))
    with open(os.path.join(root, "logs", "queries.jsonl"), "w") as f:
        for s in (2 * 86400, 2 * 86400 - 60):      # two days ago, twice
            f.write(json.dumps({"at": at(s), "tool": "relic_search", "query": "move relic data to s3", "ms": 50, "hits": 3}) + "\n")
        f.write(json.dumps({"at": at(9 * 86400), "tool": "relic_search", "query": "too old", "ms": 5, "hits": 1}) + "\n")
        big = "x" * 3000
        for i in range(1200):                        # about 3.6 MB of eval lines after them
            f.write(json.dumps({"at": at(3600 - i), "tool": "relic_search", "query": f"eval {i}", "client": "eval (http)",
                                "ms": 9, "hits": 1, "top": big}) + "\n")
    q = selfknow.queries(root)
    assert {"query": "move relic data to s3", "n": 2} in q["top"]
    assert q["eval_logged"] == 1200 and all(t["query"] != "too old" for t in q["top"])
