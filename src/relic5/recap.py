"""recap.py: what happened in one session, and the block to hand it to the next one. Ported from agent-relic-v3
src/read/recap.ts and src/verbs/tail.ts --handoff (@9f0bdb5): projections of stored rows, never a generated summary.

  recap    the human's last N turns (default 20, 0 = all), the tools that ran (counts), the files edited, how it ended
  handoff  paste-ready for a new session's FIRST prompt: the human's turns in full, each under the agent's last
           message before it cut to half ("go" means nothing without the proposal it answered); time on the first and
           last line only, plus span, median gap and longest gap, which say one focused hour or a day of parallel work
"""
import json, re, statistics
from datetime import datetime
from typing import TYPE_CHECKING

from .types_ import Json

if TYPE_CHECKING:
    from .query import Relic5

FILE = re.compile(r'"file_path"\s*:\s*"([^"]+)"')
EDITS = {"Edit", "Write", "MultiEdit", "NotebookEdit", "apply_patch"}


def _t(iso: str | None) -> float | None:
    return datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp() if iso else None


def _turns(relic: "Relic5", sid: str) -> list[Json]:
    src = relic.parts.source("text")
    if not src:
        return []
    from .query import folded
    rows: list[Json] = relic._rows(f"""SELECT role, ts, ts_th, string_agg(text, '' ORDER BY chunk) AS text FROM {folded(src, "sid = ?")}
                           GROUP BY msgkey, role, ts, ts_th ORDER BY ts, min(msgkey)""", [sid])
    return _fold_repeats(rows)


IMAGE_SRC = re.compile(r"^\[Image: source: [^\]]*\]$", re.M)
SAME_WINDOW_S = 1800


def _said(text: str | None) -> str:
    """A user turn as the human typed it: no mid-turn wrapper, no [Image: source: ...] line, whitespace collapsed."""
    from .search import _WRAPPER
    t = IMAGE_SRC.sub(" ", text or "")
    return " ".join(_WRAPPER.sub(" ", " ".join(t.lower().split())).split())


def _fold_repeats(turns: list[Json]) -> list[Json]:
    """Claude Code stores a prompt twice: when it is typed (or queued mid-turn, in the wrapper) and when it is
    submitted, seconds to minutes later (session 1dbe53ae, 2026-10-24: every one of 66 prompts, up to 11 min apart).
    A user turn that says what the previous user turn said, within 30 minutes, is that second copy: dropped, the
    first (when it was said) kept. Assistant turns are never touched."""
    out: list[Json] = []
    last: tuple[str, float | None] | None = None
    for t in turns:
        if t["role"] == "user":
            said, at = _said(t["text"]), _t(t["ts"])
            if last and said and said == last[0] and at is not None and last[1] is not None and at - last[1] <= SAME_WINDOW_S:
                continue
            last = (said, at)
        out.append(t)
    return out


def _resolve(relic: "Relic5", ident: str) -> tuple[str, Json]:
    s = relic.session(ident)          # prefix -> one session, or a clear error
    return s["uuid"], s


def recap(relic: "Relic5", ident: str, limit: int = 20) -> Json:
    sid, s = _resolve(relic, ident)
    turns = _turns(relic, sid)
    user = [t for t in turns if t["role"] == "user"]
    shown = user if not limit else user[-limit:]
    tools: dict[str, int] = {}
    files: dict[str, int] = {}
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
            # ties by name: the counts come from an unordered scan, so a plain sort by count gave a new order each call
            "tools": dict(sorted(tools.items(), key=lambda x: (-x[1], x[0]))), "files_edited": dict(sorted(files.items(), key=lambda x: (-x[1], x[0]))),
            "ended": {"ts": last["ts"], "text": (last["text"] or "")[:1200]} if last else None,
            "more": None if not limit or len(user) <= limit else f"relic5 recap {sid[:8]} --limit 0   ({len(user) - limit} earlier turns)"}


def handoff(relic: "Relic5", ident: str, user_only: bool = False) -> Json:
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


def _call(name: str | None, text: str | None) -> str:
    """One tool call as a line: its description (what the agent said it was doing) and the command or file it ran on."""
    try:
        a = json.loads(text or "")
    except ValueError:
        return " ".join((text or "").split())[:400]
    if not isinstance(a, dict):
        return str(a)[:400]
    what = a.get("description") or ""
    how = a.get("command") or a.get("file_path") or a.get("pattern") or a.get("url") or a.get("query") or a.get("prompt") or ""
    return " · ".join(x for x in (str(what), " ".join(str(how).split())[:600]) if x)


def conversation(relic: "Relic5", ident: str, offset: int = 0, limit: int = 200, tools: bool = False,
                 role: str | None = None, since: str | None = None, until: str | None = None) -> Json:
    """The whole session in order, every turn whole (Nat, 2026-10-26: "get full conversation?"): the human's turns and
    the agent's replies, each once (_fold_repeats), and with tools=True each tool call between them (name, its
    description, the command or file). Tool results are not on the hub (relic-scan keeps calls only). Pages by offset."""
    sid, s = _resolve(relic, ident)
    turns = [t | {"kind": "text"} for t in _turns(relic, sid)]
    if tools:
        src = relic.parts.source("tools")
        if src:
            from .query import folded
            seen: set[tuple[str, str]] = set()
            for r in relic._rows(f"""SELECT ts, ts_th, name, string_agg(text, '' ORDER BY chunk) AS text FROM {folded(src, "sid = ?")}
                                     GROUP BY msgkey, ts, ts_th, name ORDER BY ts""", [sid]):
                line = _call(r["name"], r["text"])
                if (r["ts"], line) in seen:
                    continue
                seen.add((r["ts"], line))
                turns.append({"role": "tool", "kind": "call", "name": r["name"], "ts": r["ts"], "ts_th": r["ts_th"], "text": line})
            turns.sort(key=lambda t: (t["ts"] or "", 0 if t["kind"] == "text" else 1))
    if role:
        turns = [t for t in turns if t["role"] == role]
    if since:
        turns = [t for t in turns if (t["ts_th"] or "") >= since or (t["ts"] or "") >= since]
    if until:
        turns = [t for t in turns if (t["ts_th"] or "")[: len(until)] <= until]
    page = turns[offset: offset + limit] if limit else turns[offset:]
    nxt = offset + len(page)
    return {"uuid": sid, "name": s.get("name"), "repo": s.get("repo"), "startedAt": s.get("startedAt"), "endedAt": s.get("endedAt"),
            "total": len(turns), "offset": offset, "turns": page, "next_offset": nxt if nxt < len(turns) else None}
