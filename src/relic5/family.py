"""family.py: the fleet as a family and as a working team (Nat, 2026-10-24: "can we visualize the lineage chart? or
team? or historical working team?").

Lineage: who budded from whom. The source is mother-oracle's frozen lineage scans (registry/lineage/vN_<date>_scan.json,
/oracle-lineage-scan: an oracle's CLAUDE.md "Budded from …" line, its birth date, awakened or not, canonical among
duplicates); relic5-push sends the newest as parts/<machine>/meta/lineage.json. Only canonical rows are kept, so a
worktree or a second copy of an oracle never shows twice.

Team: which oracles worked when, from the hub's own session table (relic-scan's meta/sessions.parquet, top-level
sessions only): sessions started per repo per Bangkok day, and the pairs of repos that worked on the same days, the
fleet's historical working teams.
"""
import glob, json, os, re
from collections import Counter
from typing import TYPE_CHECKING

from .types_ import Json

if TYPE_CHECKING:
    from .query import Relic5


def lineage(root: str) -> Json:
    """-> {source, scanned, nodes: [{name, repo, org, parent, origin, date, awakened, commits, children}], roots}."""
    fs = sorted(glob.glob(os.path.join(root, "parts", "*", "meta", "lineage.json")), key=os.path.getmtime, reverse=True)
    if not fs:
        return {"source": None, "scanned": None, "nodes": [], "roots": []}
    try:
        rows = json.load(open(fs[0]))
    except (OSError, ValueError):
        rows = []
    rows = [r for r in rows if isinstance(r, dict) and r.get("child") and r.get("canonical", True)]
    names = {r["child"] for r in rows}
    kids = Counter(r.get("parent") for r in rows if r.get("parent"))
    nodes = [{"name": r["child"], "repo": r.get("repo"), "org": r.get("org"), "origin": r.get("origin"),
              "parent": r.get("parent") if r.get("parent") in names else None, "parent_named": r.get("parent"),
              "date": r.get("date"), "awakened": bool(r.get("awakened")), "commits": r.get("commits") or 0,
              "children": kids.get(r["child"], 0)} for r in rows]
    roots = sorted({n["name"] for n in nodes if not n["parent"] and n["children"]})
    import time
    newest = max((str(r.get("date") or "") for r in rows), default="")
    return {"source": fs[0].split(os.sep)[-3], "newest_birth": newest or None,
            "pushed": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(os.path.getmtime(fs[0]))),
            "nodes": nodes, "roots": roots}


def team(relic: "Relic5", days: int = 90, top: int = 28) -> Json:
    """-> {days: [YYYY-MM-DD…], repos: [{repo, sessions, by_day: {day: n}}], pairs: [{a, b, days}]}: the repos with the
    most sessions started in the window, their sessions per Bangkok day, and which of them worked on the same days."""
    meta = relic._meta()
    if not meta:
        return {"days": [], "repos": [], "pairs": []}
    rows = relic._rows(f"""SELECT proj, strftime((TRY_CAST(first_ts AS TIMESTAMP) + INTERVAL 7 HOUR), '%Y-%m-%d') AS day, count(*) AS n
                           FROM {meta} WHERE parent_sid IS NULL AND proj IS NOT NULL AND proj <> ''
                             AND TRY_CAST(first_ts AS TIMESTAMP) >= now()::TIMESTAMP - INTERVAL {int(days)} DAY
                           GROUP BY 1, 2""")
    per: dict[str, dict[str, int]] = {}
    for r in rows:
        name = re.sub(r"^-?(opt-Code|Users-[^-]+(-Code)?|home-[^-]+(-Code)?)-github-com-", "", str(r["proj"]))
        name = re.sub(r"-wt-.*$|--claude-worktrees-.*$", "", name)
        d = per.setdefault(name, {})
        d[r["day"]] = d.get(r["day"], 0) + int(r["n"])
    ranked = sorted(per.items(), key=lambda kv: -sum(kv[1].values()))[:top]
    all_days = sorted({d for _, by in ranked for d in by})
    pairs: Counter[tuple[str, str]] = Counter()
    names = [n for n, _ in ranked]
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            shared = len(set(per[a]) & set(per[b]))
            if shared:
                pairs[(a, b)] = shared
    return {"window_days": days, "days": all_days,
            "repos": [{"repo": n, "sessions": sum(by.values()), "by_day": by} for n, by in ranked],
            "pairs": [{"a": a, "b": b, "days": n} for (a, b), n in pairs.most_common(40)]}
