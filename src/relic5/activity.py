"""activity.py: how much happened when, as counts a chart can draw (Nat, 2026-10-26: "let chat gpt help people to
extract all stuff and visualize all stuff ... if we missed method we add more!").

Counts messages of the text stream (each message once: chunk 0, one msgkey however many machines hold it) by a time
bucket and, optionally, one dimension. Bangkok time throughout (ts_th), as every other page of the hub.

  by     day | week | month | hour (YYYY-MM-DDTHH) | hour_of_day (00..23) | weekday (1 Mon .. 7 Sun) | weekday_hour (1-00 .. 7-23)
  group  none | role | project (relic-scan's cat: the repo's short name) | machine | engine | tool | file (tools stream)
  stream text (messages) | tools (tool calls) | thinking | git (commits: role commit-claude / commit-codex / commit)
"""
from typing import Any

from .types_ import Json

BY = {
    "day": "substr(ts_th, 1, 10)",
    "month": "substr(ts_th, 1, 7)",
    "hour": "substr(ts_th, 1, 13)",
    "hour_of_day": "substr(ts_th, 12, 2)",
    "week": "strftime(date_trunc('week', TRY_CAST(substr(ts_th, 1, 10) AS DATE)), '%Y-%m-%d')",
    "weekday": "CAST(isodow(TRY_CAST(substr(ts_th, 1, 10) AS DATE)) AS VARCHAR)",
    # a heatmap in one call: '1-09' = Monday 09:00-09:59 (ChatGPT fetched every hour and folded them itself, 2026-10-26)
    "weekday_hour": "CAST(isodow(TRY_CAST(substr(ts_th, 1, 10) AS DATE)) AS VARCHAR) || '-' || substr(ts_th, 12, 2)",
}
GROUP = {"none": "'all'", "role": "coalesce(role, '(none)')", "project": "coalesce(nullif(cat, ''), '(none)')", "machine": "machine",
         "engine": "engine", "tool": "coalesce(name, '(none)')",
         # the file an Edit / Write / MultiEdit / NotebookEdit call touched (ChatGPT asked for it, 2026-10-26); relic_files has more
         "file": """nullif(regexp_extract(text, '"(?:file_path|notebook_path)"\\s*:\\s*"([^"]+)"', 1), '')"""}
STREAMS = ("text", "tools", "thinking", "git")
UNIT = {"text": "messages", "tools": "tool calls", "thinking": "thinking blocks", "git": "commits"}


def activity(relic: Any, by: str = "day", group: str = "none", since: str | None = None, until: str | None = None,
             role: str | None = None, project: str | None = None, machine: str | None = None, top: int = 12,
             stream: str = "text") -> Json:
    """{by, group, buckets, series: [{name, total, counts: {bucket: n}}], total}: the top groups by total, the rest
    folded into 'other'. since/until: 'YYYY-MM-DD' or a longer Bangkok time prefix, on the message's time."""
    if by not in BY:
        raise ValueError(f"by is one of {', '.join(BY)}")
    if group not in GROUP:
        raise ValueError(f"group is one of {', '.join(GROUP)} (files changed most: relic_files)")
    if stream not in STREAMS:
        raise ValueError(f"stream is one of {', '.join(STREAMS)}")
    if group in ("tool", "file") and stream != "tools":
        raise ValueError(f"group {group} needs stream tools")
    if stream == "git":
        import os
        from . import gitlog
        p = gitlog.table(relic.parts.root)
        src = f"read_parquet('{p}')" if os.path.exists(p) else None
    else:
        src = relic.parts.source(stream)
    if not src:
        return {"by": by, "group": group, "buckets": [], "series": [], "total": 0}
    where: list[str] = ["chunk = 0", "ts_th IS NOT NULL"]
    params: list[object] = []
    if since:
        where.append("ts_th >= ?")
        params.append(since)
    if until:
        where.append("substr(ts_th, 1, ?) <= ?")
        params += [len(until), until]
    for col, v in (("role", role), ("machine", machine)):
        if v:
            where.append(f"{col} = ?")
            params.append(v)
    if project:
        where.append("cat ILIKE ?")
        params.append(f"%{project}%")
    if group == "file":
        where.append("name IN ('" + "','".join(EDIT_TOOLS) + "')")
    rows = relic._rows(f"""SELECT {BY[by]} AS b, {GROUP[group]} AS g, count(DISTINCT msgkey) AS n
                           FROM {src} WHERE {' AND '.join(where)} GROUP BY 1, 2""", params)
    totals: dict[str, int] = {}
    for r in rows:
        totals[str(r["g"])] = totals.get(str(r["g"]), 0) + int(r["n"])
    keep = [g for g, _ in sorted(totals.items(), key=lambda x: -x[1])[:max(top, 1)]]
    series: dict[str, dict[str, int]] = {g: {} for g in keep}
    for r in rows:
        if r["b"] is None:
            continue
        g = str(r["g"]) if str(r["g"]) in series else "other"
        series.setdefault(g, {})
        series[g][r["b"]] = series[g].get(r["b"], 0) + int(r["n"])
    buckets = sorted({b for s in series.values() for b in s})
    ranked = sorted(((g, c) for g, c in series.items() if c), key=lambda x: (x[0] == "other", -sum(x[1].values())))
    out: list[Json] = [{"name": g, "total": sum(c.values()), "counts": dict(sorted(c.items()))} for g, c in ranked]
    return {"by": by, "group": group, "stream": stream, "unit": UNIT[stream], "since": since, "until": until, "buckets": buckets, "series": out,
            "total": sum(sum(c.values()) for _, c in ranked),
            "note": f"{UNIT[stream]}, each once; weekday 1 = Monday; Bangkok time"}


EDIT_TOOLS = ("Edit", "Write", "MultiEdit", "NotebookEdit")


def files(relic: Any, since: str | None = None, until: str | None = None, project: str | None = None,
          contains: str | None = None, top: int = 30) -> Json:
    """The files the agents changed most (MCP relic_files): Edit / Write / MultiEdit / NotebookEdit calls of the tools
    stream, by file_path, with how many calls, sessions and days, the first and last time, and which tools."""
    src = relic.parts.source("tools")
    if not src:
        return {"files": [], "total_calls": 0}
    where: list[str] = ["chunk = 0", "name IN ('" + "','".join(EDIT_TOOLS) + "')"]
    params: list[object] = []
    if since:
        where.append("ts_th >= ?")
        params.append(since)
    if until:
        where.append("substr(ts_th, 1, ?) <= ?")
        params += [len(until), until]
    if project:
        where.append("cat ILIKE ?")
        params.append(f"%{project}%")
    path = """regexp_extract(text, '"(?:file_path|notebook_path)"\\s*:\\s*"([^"]+)"', 1)"""
    having = ""
    if contains:
        having = "HAVING f ILIKE ?"
        params.append(f"%{contains}%")
    rows = relic._rows(f"""SELECT {path} AS f, count(DISTINCT msgkey) AS calls, count(DISTINCT sid) AS sessions,
                                  count(DISTINCT substr(ts_th, 1, 10)) AS days, min(ts_th) AS first, max(ts_th) AS last,
                                  list(DISTINCT name) AS tools, list(DISTINCT cat) AS projects
                           FROM {src} WHERE {' AND '.join(where)} GROUP BY 1 {having}
                           ORDER BY calls DESC LIMIT {max(1, min(int(top), 500))}""", params)
    rows = [r for r in rows if r["f"]]
    total = relic._rows(f"SELECT count(DISTINCT msgkey) AS n FROM {src} WHERE {' AND '.join(where)}",
                        params[: len(params) - (1 if contains else 0)])
    return {"files": [{"file": r["f"], "calls": r["calls"], "sessions": r["sessions"], "days": r["days"], "first": r["first"],
                       "last": r["last"], "tools": sorted(r["tools"] or []), "projects": sorted(p for p in (r["projects"] or []) if p)}
                      for r in rows],
            "total_calls": total[0]["n"] if total else 0, "note": "edit and write calls by the agents; Bangkok time"}
