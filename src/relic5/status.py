"""status.py: relic_status, in the shape of agent-relic-v3's StatusReport (src/contracts/status.ts @9f0bdb5).

Fields are additive, as there. Months take the place of weeks: `months` is the real list, and `weeks` repeats its
counts so a relic3 consumer that reads weeks.total still gets a number. Watermarks:
  index     the newest manifest (`relic5 index`) and the rows it counted, after the fold
  machines  per machine and stream: the newest ts it pushed (its watermark: every row at or before it is here)
  vectors   nothing embedded yet (embed milestone): pending = every folded text row
"""
import json, os, time
from datetime import datetime as _datetime

from . import __version__
from .parts import MONTH_STREAMS, Parts, this_month
from .types_ import JobEvent, Json
from . import store as rfs


BACKUP_STALE_S = 36 * 3600   # nightly, plus a day of slack (relic4-scan, 2026-10-24)


def last_backup(evs: list[JobEvent], now: _datetime | None = None, verb: str = "backup") -> Json:
    """The newest finished backup (bin/relic5-backup writes a JobEvent "backup"; bin/relic5-offsite one "offsite"):
    when, how big, how old."""
    from datetime import datetime
    from .window import utcnow
    b = next((e for e in evs if e.get("verb") == verb and e.get("state") == "done"), None)
    if not b:
        return {"at": None, "bytes": None, "message": None, "age_s": None, "host": None}
    try:
        age = round(((now or utcnow()) - datetime.fromisoformat(b["at"].replace("Z", "+00:00"))).total_seconds())
    except ValueError:
        age = None
    return {"at": b["at"], "bytes": b.get("done"), "message": b.get("message"), "age_s": age, "host": b.get("host")}


def copy_of(root: str) -> Json | None:
    """A hub restored from a backup snapshot to look at locally (COPY.json, written when it was copied: of, snapshot,
    at). It is not live: nothing pushes to it, so freshness, backup and seal-day checks are off and the UI says so."""
    p = os.path.join(root, "COPY.json")
    try:
        c: Json = rfs.read_json(p)
        return c
    except (OSError, ValueError):
        return None


def _sessions(root: str) -> int | None:
    """Sessions on the hub: the rows of the index's names.parquet (one per session), from the file's footer; None before
    the first index (2026-10-25: claude.ai asked relic_status for it and got null)."""
    import pyarrow.parquet as pq
    from .fts import search_dir
    p = os.path.join(search_dir(root), "names.parquet")
    try:
        if rfs.is_s3(p):
            with rfs.open_input(p) as f:
                return int(pq.ParquetFile(f).metadata.num_rows)
        return int(pq.ParquetFile(p).metadata.num_rows) if os.path.exists(p) else None
    except Exception:
        return None


def status(root: str, now: _datetime | None = None) -> Json:
    p = Parts(root)
    mans = p.manifests()
    months = p.months()
    stale = p.stale()
    warnings = [f"month {m}: parts newer than its manifest (run relic5 index)" for m in stale]
    machines: dict[str, dict[str, Json]] = {}
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
    from .fts import current, search_dir
    for name, rel in current(p.root).items():   # a table the index names but lacks (a copy caught mid-publish)
        if not rfs.isdir(os.path.join(search_dir(p.root), rel)):
            warnings.append(f"index table {name} is missing ({rel}): run relic5 index")
    for m in p.machines():
        if not rfs.isfile(os.path.join(p.dir, m, "meta", "sessions.parquet")):
            warnings.append(f"machine {m}: no meta/sessions.parquet (sessions and repo filters miss it)")
    versions: dict[str, Json] = {}
    for m in p.machines():
        vp = os.path.join(p.dir, m, "_versions.json")
        if rfs.isfile(vp):
            try:
                versions[m] = rfs.read_json(vp)
            except ValueError:
                warnings.append(f"machine {m}: unreadable _versions.json")
    chained = {m: v for m, v in versions.items() if not m.endswith("-import")}   # an import is a one-off push, not a machine with a chain
    # relic5-push is compared by its behaviour version (push-format), not its git hash; an old push without the field
    # counts as format 0, so a machine that never got the new script still shows
    for tool, key in (("relic-scan", "relic-scan"), ("relic-extract", "relic-extract"), ("relic5-push", "push-format")):
        seen = {v.get(key, 0 if key == "push-format" else None) for v in chained.values()}
        if len(seen) > 1:
            warnings.append(f"{tool} differs between machines: " + ", ".join(
                f"{m} {v.get(key, 0 if key == 'push-format' else None)}" + (f" ({v.get('relic5-push')})" if key == "push-format" else "")
                for m, v in sorted(chained.items())))
    rows = {s: sum(man["streams"].get(s, {}).get("rows", 0) for man in mans.values()) for s in MONTH_STREAMS}
    built = max((man["built"] for man in mans.values()), default=None)
    from .fts import current, search_dir
    import json as _json
    sp = os.path.join(search_dir(p.root), "state.json")
    fst = rfs.read_json(sp) if rfs.exists(sp) else {}
    live = current(p.root)
    fts = {"at": max((v["built"] for k, v in fst.items() if k in live), default=None),
           "rows": {k: v["rows"] for k, v in fst.items() if k in live}}
    from .fts import SEEDING
    if SEEDING.get(p.root.rstrip("/")) or SEEDING.get(p.root):
        warnings.append(f"copying the search index from the bucket to this machine since {SEEDING.get(p.root.rstrip('/')) or SEEDING.get(p.root)}: search answers by substring until it lands")
    elif not live:
        warnings.append("no BM25 index published: search answers by substring (run relic5 index)")
    from .jobs import read as read_jobs
    evs, running = read_jobs(p.root)
    last_error = next((e for e in evs if e.get("state") == "error"), None)
    if last_error and not any(e["verb"] == last_error["verb"] and e.get("state") == "done" and e["at"] > last_error["at"] for e in evs):
        warnings.append(f"last {last_error['verb']} failed at {last_error['at']}: {(last_error.get('message') or '')[:200]}")
    from . import seals as SL
    seal_info = SL.summary(p.root)
    vfy = seal_info["verify"]
    for prob in ((vfy.get("problems") if vfy else None) or [])[:3]:
        warnings.append(f"seal: {prob}")
    from . import sealday as SD
    seal_days = SD.summary(p.root)
    copy = copy_of(p.root)
    if not copy:   # a copy gets no pushes, backups or seals of its own: those checks belong to the live hub
        warnings += SD.overdue(seal_days, now)
    from .jobs import last_done
    # the tail (evs) first; a nightly event older than the tail is still the last backup, not "no backup yet"
    backup = last_backup(evs, now) if any(e.get("verb") == "backup" and e.get("state") == "done" for e in evs) \
        else last_backup([e for e in [last_done(p.root, "backup")] if e], now)
    offsite = last_backup(evs, now, "offsite") if any(e.get("verb") == "offsite" and e.get("state") == "done" for e in evs) \
        else last_backup([e for e in [last_done(p.root, "offsite")] if e], now, "offsite")   # white -> black RustFS bucket relic5-hub (bin/relic5-offsite)
    if not copy and offsite["age_s"] is not None and offsite["age_s"] > BACKUP_STALE_S:
        warnings.append(f"last offsite copy {offsite['age_s'] // 3600} h ago, at {offsite['at']} (should run nightly)")
    if copy:
        pass
    elif backup["at"] is None:
        warnings.append("no backup yet (bin/relic5-backup on m5 pulls one; see docs/RESTORE.md)")
    elif backup["age_s"] is not None and backup["age_s"] > BACKUP_STALE_S:
        warnings.append(f"last backup {backup['age_s'] // 3600} h ago, at {backup['at']} (should run nightly)")
    vp = os.path.join(search_dir(p.root), "vectors.json")
    vs = rfs.read_json(vp) if rfs.exists(vp) else {"at": None, "models": {}}
    vectors = {"at": vs["at"], "pending": sum(v["pending"] for w in vs["models"].values() for v in w.values()) if vs["models"] else rows["text"],
               "models": vs["models"], "tables": {k: v["rows"] for k, v in fst.items() if k in live and k.startswith("vec_")}}
    # freshness: how far behind each machine and each index is (relic-chain runs every 10 min on m5, 2026-10-23)
    t_now = time.time()
    def lag(iso: str | None) -> int | None:
        if not iso:
            return None
        try:
            from datetime import datetime
            return round(t_now - datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp())
        except ValueError:
            return None
    fresh: Json = {"machines": {}, "fts": {"at": fts["at"]}, "vectors": {"at": vectors["at"]}}
    for m in p.machines():
        x, v = machines.get(m, {}).get("text", {}), versions.get(m, {})
        pushed = v.get("at")
        fresh["machines"][m] = {"newest_ts": x.get("newest_ts"), "pushed_at": pushed, "lag_s": lag(x.get("newest_ts")),
                                "push_age_s": lag(pushed.replace("+0700", "+07:00").replace("+0000", "+00:00")) if pushed else None}
        age = fresh["machines"][m]["push_age_s"]
        if age is not None and age > 1800 and not m.endswith("-import") and not copy:
            warnings.append(f"machine {m}: last push {age // 60} min ago (relic-chain should push every 10 min)")
    for m in p.machines():   # the chain's own verdict (relic-chain SYNC OK / MISMATCH), as last pushed
        sp_ = os.path.join(p.dir, m, "_sync.json")
        if rfs.isfile(sp_):
            try:
                line = rfs.read_json(sp_).get("line", "")
            except ValueError:
                continue
            fresh["machines"].setdefault(m, {})["sync"] = line
            if "MISMATCH" in line:
                warnings.append(f"machine {m}: {line}")
    ip = os.path.join(p.root, "index", "_search", "current.json")
    fresh["fts"]["age_s"] = round(t_now - rfs.getmtime(ip)) if rfs.exists(ip) else None
    from . import selfknow
    store, res = selfknow.store(p.root), selfknow.resources()
    warnings += [w.replace("on the hub", "on this machine (a copy of the hub)") if copy else w for w in selfknow.warnings(store, res)]
    q = selfknow.queries(p.root)
    cur = this_month(now)
    sealed = [m for m in months if m != "undated" and m < cur]
    return {
        "api": 1, "home": p.root, "layout": {"version": 1, "unit": "month", "schema": 1} if months else None,
        "code": {"name": "relic5", "version": __version__},
        "watermarks": {"archive": {"at": None}, "index": {"at": built, "rows": rows["text"]}, "fts": fts,
                       "vectors": vectors},
        "months": {"total": len(months), "sealed": len(sealed), "open": cur if cur in months else None,
                   "list": [{"month": m, "sealed": m in sealed, "rows": {s: v["rows"] for s, v in mans.get(m, {}).get("streams", {}).items()}}
                            for m in months]},
        "weeks": {"total": len(months), "sealed": len(sealed), "open": cur if cur in months else None, "quarantine_rows": 0},
        "freshness": fresh,
        "store": store, "resources": res,
        "queries": {"running": q["running"], "last": q["last"], "per_hour": q["per_hour"], "top": q["top"][:10], "zero_hits": q["zero_hits"][:10]},
        "machines": machines,
        "versions": versions,
        "rows": {"events": rows["text"] + rows["thinking"], "text": rows["text"], "thinking": rows["thinking"],
                 "tools": rows["tools"], "sessions": _sessions(p.root), "files": sum(len(p.files(s)) for s in MONTH_STREAMS)},
        "jobs": {"running": running, "recent": evs[:10], "last_error": last_error},
        "backup": backup,
        "offsite": offsite,
        "copy": copy,
        "memory": __import__("relic5.memory", fromlist=["counts"]).counts(p.root),
        "git": __import__("relic5.gitlog", fromlist=["counts"]).counts(p.root),
        "seals": seal_info,
        "seal_days": seal_days,
        "warnings": warnings,
    }
