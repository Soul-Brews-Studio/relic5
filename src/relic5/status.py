"""status.py: relic_status, in the shape of agent-relic-v3's StatusReport (src/contracts/status.ts @9f0bdb5).

Fields are additive, as there. Months take the place of weeks: `months` is the real list, and `weeks` repeats its
counts so a relic3 consumer that reads weeks.total still gets a number. Watermarks:
  index     the newest manifest (`relic5 index`) and the rows it counted, after the fold
  machines  per machine and stream: the newest ts it pushed (its watermark: every row at or before it is here)
  vectors   nothing embedded yet (embed milestone): pending = every folded text row
"""
import os, time

from . import __version__
from .parts import MONTH_STREAMS, Parts, this_month


def status(root, now=None):
    p = Parts(root)
    mans = p.manifests()
    months = p.months()
    stale = p.stale()
    warnings = [f"month {m}: parts newer than its manifest (run relic5 index)" for m in stale]
    machines = {}
    for mon, man in mans.items():
        for s, v in man["streams"].items():
            for m, mv in v["machines"].items():
                e = machines.setdefault(m, {}).setdefault(s, {"rows": 0, "bytes": 0, "newest_ts": None, "pushed_at": None})
                e["rows"] += mv.get("rows", 0)
                e["bytes"] += mv.get("bytes", 0)
                if mv.get("newest_ts") and (e["newest_ts"] is None or mv["newest_ts"] > e["newest_ts"]):
                    e["newest_ts"] = mv["newest_ts"]
                if mv.get("mtime"):
                    at = time.strftime("%FT%T%z", time.localtime(mv["mtime"]))
                    e["pushed_at"] = max(e["pushed_at"] or "", at)
    for m in p.machines():
        if not os.path.isfile(os.path.join(p.dir, m, "meta", "sessions.parquet")):
            warnings.append(f"machine {m}: no meta/sessions.parquet (sessions and repo filters miss it)")
    rows = {s: sum(man["streams"].get(s, {}).get("rows", 0) for man in mans.values()) for s in MONTH_STREAMS}
    built = max((man["built"] for man in mans.values()), default=None)
    from .fts import current, search_dir
    import json as _json
    sp = os.path.join(search_dir(p.root), "state.json")
    fst = _json.load(open(sp)) if os.path.exists(sp) else {}
    live = current(p.root)
    fts = {"at": max((v["built"] for k, v in fst.items() if k in live), default=None),
           "rows": {k: v["rows"] for k, v in fst.items() if k in live}}
    if not live:
        warnings.append("no BM25 index published: search answers by substring (run relic5 index)")
    cur = this_month(now)
    sealed = [m for m in months if m != "undated" and m < cur]
    return {
        "api": 1, "home": p.root, "layout": {"version": 1, "unit": "month", "schema": 1} if months else None,
        "code": {"name": "relic5", "version": __version__},
        "watermarks": {"archive": {"at": None}, "index": {"at": built, "rows": rows["text"]}, "fts": fts,
                       "vectors": {"at": None, "pending": rows["text"]}},
        "months": {"total": len(months), "sealed": len(sealed), "open": cur if cur in months else None,
                   "list": [{"month": m, "sealed": m in sealed, "rows": {s: v["rows"] for s, v in mans.get(m, {}).get("streams", {}).items()}}
                            for m in months]},
        "weeks": {"total": len(months), "sealed": len(sealed), "open": cur if cur in months else None, "quarantine_rows": 0},
        "machines": machines,
        "rows": {"events": rows["text"] + rows["thinking"], "text": rows["text"], "thinking": rows["thinking"],
                 "tools": rows["tools"], "sessions": None, "files": sum(len(p.files(s)) for s in MONTH_STREAMS)},
        "jobs": {"running": []},
        "warnings": warnings,
    }
