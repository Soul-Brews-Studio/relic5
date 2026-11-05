"""session_readings.py: what a model made of one whole session (#280). Window readings (readings.py) read a stretch of
time across every session in it; nothing said what one session was about, so "which session built X" fell back to
reading the transcript, and a session titled "hello" stayed "hello".

relic-extract (report/session_readings.py) reads each main session once (again when it grows) and appends to
~/.relic-extract/report/session-readings.jsonl:

  {"sid": ..., "model": "zai:glm-5.3", "at": ISO, "events": n, "answer": {"type", "focus", "work": [...], "ended",
   "open": [...], "repos": [...], "en", "th"}}

The hub reads copies from <root>/readings/sessions/<machine>.jsonl (relic5-push rsyncs them); nothing here asks a model.
A session read more than once keeps its newest answer per model; `newest` picks the newest across models.
"""
import glob, json, os, re, threading

from .types_ import Json

KEEP = ("type", "focus", "work", "ended", "open", "repos", "en", "th")
GENERIC = re.compile(r"^(hello|hi|ok|okay|yes|go|continue|start|test|hey|/?model\b.*|/?clear|/?compact|/?resume|"
                     r"/?init|restart( self)?|now|next|done|thanks?|\.+|\?+)$", re.I)

_lock = threading.Lock()
_cache: dict[str, tuple[tuple[float, int], dict[str, dict[str, Json]]]] = {}


def files(root: str) -> list[str]:
    return sorted(glob.glob(os.path.join(root, "readings", "sessions", "*.jsonl")))


def _load(path: str) -> dict[str, dict[str, Json]]:
    """{sid: {model: reading}} of one file, newest answer per (sid, model)."""
    st = os.stat(path)
    sig = (st.st_mtime, st.st_size)
    with _lock:
        hit = _cache.get(path)
        if hit and hit[0] == sig:
            return hit[1]
    out: dict[str, dict[str, Json]] = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            try:
                d = json.loads(line)
            except ValueError:
                continue
            a, sid = d.get("answer"), d.get("sid")
            if not sid or not isinstance(a, dict) or not a.get("focus"):
                continue
            row: Json = {"sid": sid, "model": str(d.get("model") or "?"), "at": d.get("at"), "events": d.get("events"),
                         **{k: a.get(k) for k in KEEP if a.get(k) is not None}}
            cur = out.setdefault(sid, {}).get(row["model"])
            if cur is None or str(row["at"] or "") >= str(cur["at"] or ""):
                out[sid][row["model"]] = row
    with _lock:
        _cache[path] = (sig, out)
    return out


def _all(root: str) -> dict[str, list[Json]]:
    merged: dict[str, list[Json]] = {}
    for p in files(root):
        machine = os.path.splitext(os.path.basename(p))[0]
        for sid, by_model in _load(p).items():
            merged.setdefault(sid, []).extend(r | {"machine": machine} for r in by_model.values())
    return merged


def of(root: str, sid: str) -> list[Json]:
    """Every model's newest reading of one session, newest first."""
    return sorted(_all(root).get(sid, []), key=lambda r: str(r.get("at") or ""), reverse=True)


def newest(root: str, sids: list[str]) -> dict[str, Json]:
    if not files(root):
        return {}
    a = _all(root)
    return {s: max(a[s], key=lambda r: str(r.get("at") or "")) for s in sids if a.get(s)}


def search(root: str, words: str, limit: int = 20) -> list[Json]:
    """Session readings whose focus, work, en or th hold every word (case-blind), newest session first."""
    ws = [w.lower() for w in words.split()]
    if not ws or not files(root):
        return []
    hits: list[Json] = []
    for sid, rs in _all(root).items():
        r = max(rs, key=lambda x: str(x.get("at") or ""))
        hay = json.dumps({k: r.get(k) for k in ("focus", "work", "ended", "en", "th", "repos")}, ensure_ascii=False).lower()
        if all(w in hay for w in ws):
            hits.append({"sid": sid, "link": f"relic5://session/{sid}", "model": r["model"], "at": r.get("at"),
                         "focus": r.get("focus"), "ended": r.get("ended")})
    hits.sort(key=lambda h: str(h.get("at") or ""), reverse=True)
    return hits[:limit]


def generic(title: str | None) -> bool:
    """A title that says nothing about the session: empty, one stock word, a slash command, or a mid-turn wrapper."""
    t = " ".join((title or "").split()).strip(" .!?")
    return (not t or len(t) < 4 or bool(GENERIC.match(t)) or t.startswith("<") or t.lower().startswith("the user sent a new message")
            or t.lower().startswith("caveat:"))


def display_title(name: str | None, title: str | None, reading: Json | None = None, first_ask: str | None = None) -> str | None:
    """The title to show: the host's title, else the session's name (its first prompt), unless that is generic; then
    the reading's focus; then the first real ask, cut to one line."""
    for t in (title, name):
        if t and not generic(t):
            return " ".join(t.split())[:120]
    if reading and reading.get("focus"):
        return " ".join(str(reading["focus"]).split())[:120]
    if first_ask:
        from .timetravel import one_line
        line = one_line(first_ask, 120)
        if line and not generic(line):
            return line
    return title or name


def listing(root: str, q: str | None = None, limit: int = 50, offset: int = 0) -> Json:
    """Session readings newest first (for relic_readings kind=sessions)."""
    rows = [max(rs, key=lambda x: str(x.get("at") or "")) for rs in _all(root).values()]
    if q:
        ws = [w.lower() for w in q.split()]
        rows = [r for r in rows if all(w in json.dumps({k: r.get(k) for k in KEEP}, ensure_ascii=False).lower() for w in ws)]
    rows.sort(key=lambda r: str(r.get("at") or ""), reverse=True)
    out: Json = {"kind": "sessions", "total": len(rows), "offset": offset, "rows": rows[offset: offset + limit],
                 "files": [os.path.basename(p) for p in files(root)],
                 "next_offset": offset + limit if offset + limit < len(rows) else None}
    if not files(root):
        out["note"] = ("no session readings on the hub yet: relic-extract report/session_readings.py writes "
                       "~/.relic-extract/report/session-readings.jsonl, relic5-push copies it to <root>/readings/sessions/<machine>.jsonl")
    return out
