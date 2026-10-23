"""recap.py: what happened in one session, and the block to hand it to the next one. Ported from agent-relic-v3
src/read/recap.ts and src/verbs/tail.ts --handoff (@9f0bdb5): projections of stored rows, never a generated summary.

  recap    the human's last N turns (default 20, 0 = all), the tools that ran (counts), the files edited, how it ended
  handoff  paste-ready for a new session's FIRST prompt: the human's turns in full, each under the agent's last
           message before it cut to half ("go" means nothing without the proposal it answered); time on the first and
           last line only, plus span, median gap and longest gap, which say one focused hour or a day of parallel work
"""
import json, re, statistics
from datetime import datetime

FILE = re.compile(r'"file_path"\s*:\s*"([^"]+)"')
EDITS = {"Edit", "Write", "MultiEdit", "NotebookEdit", "apply_patch"}


def _t(iso):
    return datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp() if iso else None


def _turns(relic, sid):
    src = relic.parts.source("text")
    if not src:
        return []
    from .query import folded
    return relic._rows(f"""SELECT role, ts, ts_th, string_agg(text, '' ORDER BY chunk) AS text FROM {folded(src, "sid = ?")}
                           GROUP BY msgkey, role, ts, ts_th ORDER BY ts, min(msgkey)""", [sid])


def _resolve(relic, ident):
    s = relic.session(ident)          # prefix -> one session, or a clear error
    return s["uuid"], s


def recap(relic, ident, limit=20):
    sid, s = _resolve(relic, ident)
    turns = _turns(relic, sid)
    user = [t for t in turns if t["role"] == "user"]
    shown = user if not limit else user[-limit:]
    tools, files = {}, {}
    src = relic.parts.source("tools")
    if src:
        from .query import folded
        for r in relic._rows(f"SELECT name, text FROM {folded(src, 'sid = ?')}", [sid]):
            tools[r["name"] or "?"] = tools.get(r["name"] or "?", 0) + 1
            if (r["name"] or "") in EDITS:
                for f in FILE.findall(r["text"] or ""):
                    files[f] = files.get(f, 0) + 1
    last = next((t for t in reversed(turns) if t["role"] == "assistant"), None)
    return {"uuid": sid, "name": s.get("name"), "repo": s.get("repo"), "startedAt": s.get("startedAt"), "endedAt": s.get("endedAt"),
            "turns": {"user": len(user), "shown": len(shown), "all": len(turns)},
            "asked": [{"ts": t["ts"], "text": t["text"]} for t in shown],
            "tools": dict(sorted(tools.items(), key=lambda x: -x[1])), "files_edited": dict(sorted(files.items(), key=lambda x: -x[1])),
            "ended": {"ts": last["ts"], "text": (last["text"] or "")[:1200]} if last else None,
            "more": None if not limit or len(user) <= limit else f"relic5 recap {sid[:8]} --limit 0   ({len(user) - limit} earlier turns)"}


def handoff(relic, ident, user_only=False):
    sid, s = _resolve(relic, ident)
    turns = _turns(relic, sid)
    user = [i for i, t in enumerate(turns) if t["role"] == "user"]
    if not user:
        return {"uuid": sid, "text": "", "turns": 0}
    lines, times = [], [_t(turns[i]["ts"]) for i in user]
    for n, i in enumerate(user):
        prev = next((turns[j] for j in range(i - 1, -1, -1) if turns[j]["role"] == "assistant"), None)
        if prev and not user_only:
            p = " ".join((prev["text"] or "").split())
            lines.append("  agent: " + (p[: max(80, len(p) // 2)] + ("…" if len(p) > max(80, len(p) // 2) else "")))
        stamp = f"[{turns[i]['ts_th'][:16].replace('T', ' ')}] " if n in (0, len(user) - 1) else ""
        lines.append(f"{stamp}me: {turns[i]['text'].strip()}")
    gaps = [b - a for a, b in zip(times, times[1:]) if a and b]
    span = (times[-1] - times[0]) if times[0] and times[-1] else 0
    head = (f"Handoff from session {sid} ({s.get('name') or ''}), {len(user)} turns over {span / 3600:.1f} h; "
            f"median gap {statistics.median(gaps) / 60 if gaps else 0:.0f} min, longest {max(gaps) / 3600 if gaps else 0:.1f} h.")
    return {"uuid": sid, "turns": len(user), "span_s": round(span), "median_gap_s": round(statistics.median(gaps)) if gaps else 0,
            "longest_gap_s": round(max(gaps)) if gaps else 0, "text": head + "\n\n" + "\n".join(lines)}
