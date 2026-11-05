"""timetravel.py: the hub's time-travel verbs, so /time-travel needs one call where it stitched five together (Nat,
2026-11-05: "all should be relic5 subcommands, not skill"). Projections of stored rows and of readings already on the
hub; nothing here asks a model.

  chain  the sessions before and after one session in the same worktree (or repo, or branch), with the gaps between
         them and the ones that ran in parallel: relic3's `session --tree` / `chain`, which relic5 lacked (#278)
  at     everything around one moment, a hit or a Bangkok time: the readings whose windows hold it, the sessions that
         were running, the commits and the hub searches inside the span, and the hit's own neighbours (#279)
  arc    how a topic began and changed: hits per month, first and last, the months where it turned, and the readings
         and found notes that name it (#281)
"""
import json, re
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

from .types_ import Json

if TYPE_CHECKING:
    from .query import Relic5

BKK = timedelta(hours=7)
EDITS = ("Edit", "Write", "MultiEdit", "NotebookEdit", "apply_patch")
FILE = re.compile(r'"file_path"\s*:\s*"([^"]+)"')
WRAPPER = re.compile(r"the user sent a new message while you were working:|this is how claude code surfaces messages the user "
                     r"sends mid-turn.*?(?:conversation turn\.|$)|address the message above as you continue this turn\.", re.I | re.S)
PASTE = re.compile(r"</?pasted_content[^>]*>", re.I)
SCOPES = ("auto", "worktree", "repo", "branch")


def _dt(iso: str | None) -> datetime | None:
    if not iso:
        return None
    try:
        d = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def _iso(d: datetime) -> str:
    """The form the parts store ts in: UTC, milliseconds, Z (string order = time order)."""
    return d.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + f"{d.microsecond // 1000:03d}Z"


def _th(d: datetime) -> str:
    return (d.astimezone(timezone.utc) + BKK).strftime("%Y-%m-%d %H:%M")


def _th_of(iso: str | None) -> str | None:
    d = _dt(iso)
    return _th(d) if d else None


def one_line(text: str | None, width: int = 200) -> str:
    """A turn as one readable line: no mid-turn wrapper, no paste tags, whitespace collapsed."""
    t = " ".join(PASTE.sub(" ", WRAPPER.sub(" ", text or "")).split())
    return t if len(t) <= width else t[: width - 1] + "…"


def span_s(span: str | int | None, default: int = 1800) -> int:
    """'30m' | '2h' | '1d' | seconds -> seconds."""
    if span is None or span == "":
        return default
    if isinstance(span, int):
        return span
    m = re.fullmatch(r"\s*(\d+)\s*([smhd]?)\s*", str(span))
    if not m:
        from .query import UsageError
        raise UsageError(f"span {span!r}: a number with s, m, h or d (30m, 2h)")
    return int(m[1]) * {"": 60, "s": 1, "m": 60, "h": 3600, "d": 86400}[m[2]]


def _ids(sids: list[str]) -> list[str]:
    return [s for s in dict.fromkeys(sids) if s]


def _ends(relic: "Relic5", sids: list[str], at: str | None = None) -> dict[str, Json]:
    """Per session: the human's first turn, the agent's last turn (before `at` when given) and how many turns each."""
    src = relic.parts.source("text")
    if not src or not sids:
        return {}
    cond, params = "chunk = 0 AND sid IN (SELECT unnest(?))", list[object]([sids])
    if at:
        cond += " AND ts <= ?"
        params.append(at)
    out: dict[str, Json] = {}
    for r in relic._rows(f"""SELECT sid, arg_min(text, ts) FILTER (WHERE role = 'user') AS first_ask,
                                    arg_max(text, ts) FILTER (WHERE role = 'assistant') AS last_said,
                                    arg_max(text, ts) AS last_any, arg_max(role, ts) AS last_role, max(ts) AS last_ts,
                                    count(DISTINCT msgkey) FILTER (WHERE role = 'user') AS asks
                             FROM {src} WHERE {cond} GROUP BY sid""", params):
        out[r["sid"]] = r
    return out


def _edited(relic: "Relic5", sids: list[str], top: int = 5) -> dict[str, list[str]]:
    src = relic.parts.source("tools")
    if not src or not sids:
        return {}
    names = "', '".join(EDITS)
    per: dict[str, Counter[str]] = {}
    for r in relic._rows(f"SELECT sid, text FROM {src} WHERE sid IN (SELECT unnest(?)) AND name IN ('{names}')", [sids]):
        c = per.setdefault(r["sid"], Counter())
        for f in FILE.findall(r["text"] or ""):
            c[f] += 1
    return {s: [f for f, _ in c.most_common(top)] for s, c in per.items()}


# ---- chain ---------------------------------------------------------------------------------------------------------

def chain(relic: "Relic5", ident: str, before: int = 3, after: int = 3, scope: str = "auto", gap_hours: float = 6.0) -> Json:
    """The sessions around one session, oldest first. scope: worktree (same cwd), repo (same project folder), branch
    (same branch in the same repo), auto (worktree when it holds two sessions or more, else repo). Each node: when, where,
    the first ask and the last reply in one line each, the files edited. Gaps longer than gap_hours and sessions that
    overlapped (parallel work) are marked between nodes."""
    from .query import UsageError
    if scope not in SCOPES:
        raise UsageError(f"scope is one of {', '.join(SCOPES)}")
    s = relic.session(ident)
    sid = s["uuid"]
    meta = relic._meta()
    has = {c: relic.meta_has(c) for c in ("cwd", "branch", "title")}
    cwd, proj, branch = s.get("cwd"), s.get("repo"), s.get("branch")

    def cond(sc: str) -> tuple[str, list[object]] | None:
        if sc == "worktree" and has["cwd"] and cwd:
            return "cwd = ?", [cwd]
        if sc == "branch" and has["branch"] and branch and proj:
            return "branch = ? AND proj = ?", [branch, proj]
        if sc == "repo" and proj:
            return "proj = ?", [proj]
        return None

    chosen = scope
    if scope == "auto":
        chosen = "repo"
        c = cond("worktree")
        if c:
            n = relic._rows(f"SELECT count(*) AS n FROM {meta} WHERE parent_sid IS NULL AND {c[0]}", c[1])[0]["n"]
            if n >= 2:
                chosen = "worktree"
    c = cond(chosen)
    if not c:
        raise UsageError(f"session {sid[:8]} has no {chosen} to chain by" + ("" if has["cwd"] else " (this hub's meta has no cwd yet)"))
    extra = ", ".join(x for x in ("cwd" if has["cwd"] else "", "branch" if has["branch"] else "", "title" if has["title"] else "") if x)
    rows = relic._rows(f"""SELECT sid, machine, engine, proj, first_ts, last_ts, n_rows{', ' + extra if extra else ''}
                           FROM {meta} WHERE parent_sid IS NULL AND sid IS NOT NULL AND {c[0]}
                           ORDER BY first_ts NULLS LAST, sid""", c[1])
    at = next((i for i, r in enumerate(rows) if r["sid"] == sid), None)
    if at is None:   # a subagent or a session the scope query missed: put it where its start says
        rows.append({"sid": sid, "machine": s.get("home"), "engine": s.get("source"), "proj": proj, "first_ts": s.get("startedAt"),
                     "last_ts": s.get("endedAt"), "n_rows": s.get("events"), "cwd": cwd, "branch": branch, "title": s.get("title")})
        rows.sort(key=lambda r: (r["first_ts"] or "", r["sid"]))
        at = next(i for i, r in enumerate(rows) if r["sid"] == sid)
    lo, hi = max(0, at - max(before, 0)), min(len(rows), at + max(after, 0) + 1)
    pick = rows[lo:hi]
    sids = [r["sid"] for r in pick]
    names, ends, files = relic._names(sids), _ends(relic, sids), _edited(relic, sids)
    from . import session_readings as SR
    reads = SR.newest(relic.parts.root, sids)
    nodes: list[Json] = []
    prev_end: datetime | None = None
    for r in pick:
        e = ends.get(r["sid"], {})
        start, end = _dt(r["first_ts"]), _dt(r["last_ts"])
        gap = round((start - prev_end).total_seconds()) if start and prev_end else None
        rd = reads.get(r["sid"])
        node: Json = {"uuid": r["sid"], "is_target": r["sid"] == sid, "link": f"relic5://session/{r['sid']}",
                      "title": SR.display_title(names.get(r["sid"]), r.get("title"), rd, e.get("first_ask")),
                      "startedAt": r["first_ts"], "endedAt": r["last_ts"],
                      "start_th": _th(start) if start else None, "end_th": _th(end) if end else None,
                      "machine": r["machine"], "engine": r["engine"], "branch": r.get("branch"), "events": r["n_rows"],
                      "asks": e.get("asks"), "first_ask": one_line(e.get("first_ask")), "last_reply": one_line(e.get("last_said")),
                      "files_edited": files.get(r["sid"], []), "gap_before_s": gap,
                      "gap_before": None if gap is None else ("parallel" if gap < 0 else "gap" if gap > gap_hours * 3600 else None)}
        if rd:
            node["reading"] = {k: rd.get(k) for k in ("focus", "ended", "en", "th") if rd.get(k)}
        nodes.append(node)
        prev_end = max(prev_end, end) if prev_end and end else (end or prev_end)
    machines = Counter(r["machine"] for r in rows)
    return {"target": sid, "scope": chosen, "scope_value": c[1][0], "in_scope": len(rows), "position": at + 1,
            "before": at - lo, "after": hi - at - 1, "nodes": nodes,
            "gaps": [{"before": n["uuid"], "seconds": n["gap_before_s"], "kind": n["gap_before"]} for n in nodes if n["gap_before"]],
            "machines": dict(machines),
            "more": None if lo == 0 and hi == len(rows) else f"{lo} earlier and {len(rows) - hi} later sessions in this {chosen}: raise before/after"}


# ---- at ------------------------------------------------------------------------------------------------------------

def _moment(relic: "Relic5", moment: str) -> tuple[datetime, Json | None]:
    """A relic5:// link or uid (the hit, shown with its neighbours) or a Bangkok time 'YYYY-MM-DD HH:MM[:SS]'."""
    from .query import UsageError
    m = moment.strip()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}([ T]\d{2}:\d{2}(:\d{2})?)?", m):
        d = datetime.fromisoformat(m.replace("T", " ") + ("" if " " in m.replace("T", " ") else " 12:00"))
        return d.replace(tzinfo=timezone(BKK)), None
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}T[\d:.]+(Z|[+-]\d{2}:?\d{2})", m):
        z = _dt(m)
        if z:
            return z, None
    shown = relic.show(m, before=2, after=2)
    t = _dt((shown.get("target") or {}).get("ts"))
    if not t:
        raise UsageError(f"{moment}: the hit has no time")
    return t, shown


def at(relic: "Relic5", moment: str, span: str | int | None = "30m", limit: int = 30) -> Json:
    t, shown = _moment(relic, moment)
    w = span_s(span)
    lo, hi = t - timedelta(seconds=w), t + timedelta(seconds=w)
    th = _th(t)
    out: Json = {"moment": _iso(t), "moment_th": th, "span_s": w, "from_th": _th(lo), "to_th": _th(hi)}
    # readings whose window holds the moment: one per grain and model
    from . import readings as R
    rows = R.readings(relic.parts.root, since=th[:10], until=th[:10], limit=1000)["rows"]
    held = [r for r in rows if r["start"] <= th < r["end"]]
    order = {g: i for i, g in enumerate(("15m", "1h", "3h", "day"))}
    out["readings"] = [{k: r.get(k) for k in ("grain", "start", "end", "model", "machine", "type", "focus", "en", "th") if r.get(k)}
                       for r in sorted(held, key=lambda r: (order.get(r["grain"], 9), r["model"]))]
    # sessions running in the span, with what each last said at the moment
    meta = relic._meta()
    sess: list[Json] = []
    if meta:
        found = relic._rows(f"""SELECT sid, machine, engine, proj, first_ts, last_ts, n_rows FROM {meta}
                                WHERE parent_sid IS NULL AND sid IS NOT NULL AND first_ts <= ? AND last_ts >= ?
                                ORDER BY last_ts DESC LIMIT ?""", [_iso(hi), _iso(lo), limit])
        sids = [r["sid"] for r in found]
        names, ends = relic._names(sids), _ends(relic, sids, at=_iso(hi))
        target_sid = ((shown or {}).get("target") or {}).get("sid")
        for r in found:
            e = ends.get(r["sid"], {})
            sess.append({"uuid": r["sid"], "link": f"relic5://session/{r['sid']}", "is_hit": r["sid"] == target_sid,
                         "title": names.get(r["sid"]), "machine": r["machine"], "engine": r["engine"], "repo": r["proj"],
                         "start_th": _th_of(r["first_ts"]), "end_th": _th_of(r["last_ts"]),
                         "last_turn": {"role": e.get("last_role"), "at_th": _th_of(e.get("last_ts")),
                                       "text": one_line(e.get("last_any"))} if e else None})
        sess.sort(key=lambda x: (not x["is_hit"], x["machine"] or "", x["start_th"] or ""))
    out["sessions"] = sess
    # commits inside the span
    from . import gitlog
    from . import store as rfs
    p = gitlog.table(relic.parts.root)
    commits: list[Json] = []
    if rfs.exists(p):
        for r in relic._rows(f"""SELECT ts, ts_th, repo, title, hash, author FROM read_parquet('{p}')
                                 WHERE ts >= ? AND ts <= ? ORDER BY ts LIMIT ?""", [_iso(lo), _iso(hi), limit]):
            commits.append({"at_th": (r["ts_th"] or "")[:16].replace("T", " "), "repo": r["repo"], "title": r["title"],
                            "hash": (r["hash"] or "")[:12], "author": r["author"]})
    out["commits"] = commits
    # what the hub was asked inside the span
    from . import trace
    a = trace.asked(relic.parts.root, since=_iso(lo), until=_iso(hi), limit=10)
    out["searches"] = [{"query": e["query"], "times": e["times"], "hits": e["hits"], "clients": e["clients"]} for e in a["top"]]
    out["found"] = [{k: f.get(k) for k in ("at", "goal", "found", "links")} for f in a["found"]]
    if shown:
        out["hit"] = {"target": shown.get("target"), "before": shown.get("before"), "after": shown.get("after")}
    return out


# ---- arc -----------------------------------------------------------------------------------------------------------

def _hits(relic: "Relic5", words: str, lo: str | None, hi: str | None, cap: int) -> tuple[list[Json], str]:
    """Up to cap prose hits for the words: BM25 when the index is built, else a substring scan (every word)."""
    from .search import q_
    from .query import like
    ws = words.split()
    if relic.index.built():
        conds = [f"ts >= {q_(lo)}" if lo else "", f"ts <= {q_(hi)}" if hi else ""]
        bw = " AND ".join(c for c in conds if c) or None
        rows = relic.index.query("prose", words, bw, cap)
        allw = [r for r in rows if all(w.lower() in (r.get("text") or "").lower() for w in ws)]
        if len(ws) > 1 and len(allw) >= 10:
            return allw, f"bm25, the {len(rows):,} best hits narrowed to the {len(allw):,} that hold every word"
        return rows, f"bm25, the {len(rows):,} best hits"
    src = relic.parts.source("text")
    if not src:
        return [], "no text on the hub"
    where: list[str] = ["chunk = 0"]
    params: list[object] = []
    for w in ws:
        where.append("text ILIKE ? ESCAPE '\\'")
        params.append(like(w))
    for cnd, v in (("ts >= ?", lo), ("ts <= ?", hi)):
        if v:
            where.append(cnd)
            params.append(v)
    from .query import folded
    rows = relic._rows(f"SELECT * FROM {folded(src, ' AND '.join(where))} ORDER BY ts LIMIT ?", params + [cap])
    return rows, f"substring scan (no BM25 index), {len(rows):,} hits holding every word"


def arc(relic: "Relic5", words: str, since: str | None = None, until: str | None = None, cap: int = 3000) -> Json:
    """How a topic began and changed: per month the hits, sessions, top projects and machines; the first and the last
    hit; turning points (a month whose top project changed, or whose hits doubled); then the day readings and the found
    notes that name it, oldest first. Every claim carries a relic5:// link."""
    from .query import UsageError
    from .window import window
    if not words.strip():
        raise UsageError("arc needs words")
    try:
        lo, hi, _ = window(since, until)
    except ValueError as ex:
        raise UsageError(str(ex))
    rows, how = _hits(relic, words, lo, hi, max(10, min(cap, 20000)))

    def link(r: Json) -> str:
        u = r.get("uid") or (r["msgkey"] + (f":{r['chunk']}" if r.get("chunk") else ""))
        return f"relic5://{r['month']}/{u}"

    def brief(r: Json) -> Json:
        return {"at_th": (r.get("ts_th") or "")[:16].replace("T", " "), "project": r.get("cat"), "role": r.get("role"),
                "session": r.get("sid"), "text": one_line(r.get("text"), 220), "link": link(r)}

    months: dict[str, Json] = {}
    for r in rows:
        m = r.get("month") or (r.get("ts_th") or "")[:7]
        if not m:
            continue
        e = months.setdefault(m, {"month": m, "hits": 0, "sessions": set(), "projects": Counter(), "machines": Counter(), "best": None})
        e["hits"] += 1
        e["sessions"].add(r.get("sid"))
        e["projects"][r.get("cat") or "?"] += 1
        ms = r.get("machines")
        for mc in (ms if isinstance(ms, list) else [r.get("machine")] if r.get("machine") else []):
            e["machines"][mc] += 1
        if e["best"] is None or (r.get("_score") or r.get("score") or 0) > (e["best"].get("_score") or e["best"].get("score") or 0):
            e["best"] = r
    ordered = [months[m] for m in sorted(months)]
    turns: list[Json] = []
    for i, e in enumerate(ordered):
        top = e["projects"].most_common(1)[0][0]
        prev = ordered[i - 1] if i else None
        why = []
        if prev is None:
            why.append("first month")
        else:
            if prev["projects"].most_common(1)[0][0] != top:
                why.append(f"top project {prev['projects'].most_common(1)[0][0]} -> {top}")
            if e["hits"] >= 2 * prev["hits"] and e["hits"] >= 5:
                why.append(f"hits {prev['hits']} -> {e['hits']}")
        if why:
            turns.append({"month": e["month"], "why": "; ".join(why), "hit": brief(e["best"])})
    first = min(rows, key=lambda r: r.get("ts") or "9") if rows else None
    last = max(rows, key=lambda r: r.get("ts") or "") if rows else None
    from . import readings as R, trace
    rd = R.readings(relic.parts.root, grain="day", q=words, limit=500)["rows"]
    rd = sorted(rd, key=lambda r: (r["start"], r["model"]))[:40]
    try:
        notes = trace.searched(relic.parts.root, query=words, limit=10)["chains"]
    except UsageError:
        notes = []
    from . import session_readings as SR
    return {"words": words, "how": how, "hits": len(rows),
            "first": brief(first) if first else None, "last": brief(last) if last else None,
            "months": [{"month": e["month"], "hits": e["hits"], "sessions": len(e["sessions"]),
                        "projects": dict(e["projects"].most_common(4)), "machines": dict(e["machines"].most_common(4))} for e in ordered],
            "turning_points": turns,
            "readings": [{"day": r["start"][:10], "model": r["model"], "focus": r.get("focus")} for r in rd],
            "sessions_read": SR.search(relic.parts.root, words, limit=15),
            "found": [{"root": g["root"], "last": g["last"], "queries": g["queries"][:3],
                       "found": [f.get("found") for f in g["found"]][:2], "links": g["links"][:3]} for g in notes],
            "note": "hits are the best matches, not every mention: months count those hits"}
