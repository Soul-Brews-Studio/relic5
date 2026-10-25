"""readings.py: what relic-extract's models made of each stretch of time, served by the hub (Nat, 2026-10-26: "make mcp
to get like summarize of the work? ... full summarization of all jsonl? to output file from gb300 and zai? where? and
what?").

relic-extract (Soul-Brews-Studio/relic-extract, report/readings.py) asks a model to read every window of the history
(a day, 3 hours, 1 hour, 15 minutes: every prompt of every session in it) and answer type, focus, distraction, work,
agents, pattern, en, th, and with --deep friction and lesson. Every answer is appended to
~/.relic-extract/report/readings.jsonl on the machine that ran it. The hub reads copies of those files from
<root>/readings/*.jsonl (one per machine, pushed by rsync); nothing here asks a model.

Unit strings in the file, oldest format first:
  2025-09-21                      a day (the first qwen3:14b pass)
  2025-09-19 15                   3 hours from 15:00 (first pass)
  2025-09-19 15-1h                1 hour from 15:00 (first pass)
  2025-10-24 day                  a day
  2025-09-19 21:00-24:00 3h       3h, 1h or 15m with start and end
A window read more than once by one model keeps its newest answer.
"""
import glob, json, os, re, threading


from .types_ import Json

FULL = re.compile(r"^(\d{4}-\d{2}-\d{2}) (\d{2}:\d{2})-(\d{2}:\d{2}) (15m|1h|3h)$")
DAY = re.compile(r"^(\d{4}-\d{2}-\d{2})(?: day)?$")
OLD_1H = re.compile(r"^(\d{4}-\d{2}-\d{2}) (\d{2})-1h$")
OLD_3H = re.compile(r"^(\d{4}-\d{2}-\d{2}) (\d{2})$")
GRAINS = ("day", "3h", "1h", "15m")
KEEP = ("type", "focus", "distraction", "work", "agents", "pattern", "friction", "lesson", "en", "th")

_lock = threading.Lock()
_cache: dict[str, tuple[tuple[float, int], list[Json]]] = {}


def window(unit: str) -> tuple[str, str, str] | None:
    """(grain, start, end) of a unit string; start and end are 'YYYY-MM-DD HH:MM' (end exclusive, 24:00 allowed)."""
    if m := FULL.match(unit):
        return m[4], f"{m[1]} {m[2]}", f"{m[1]} {m[3]}"
    if m := DAY.match(unit):
        return "day", f"{m[1]} 00:00", f"{m[1]} 24:00"
    if m := OLD_1H.match(unit):
        return "1h", f"{m[1]} {m[2]}:00", f"{m[1]} {int(m[2]) + 1:02d}:00"
    if m := OLD_3H.match(unit):
        return "3h", f"{m[1]} {m[2]}:00", f"{m[1]} {int(m[2]) + 3:02d}:00"
    return None


def model_of(raw: str) -> tuple[str, bool]:
    """'zai:glm-5.3 deep' -> ('zai:glm-5.3', True); the first pass wrote gb300's qwen3:14b without its lane prefix."""
    deep = raw.endswith(" deep")
    m = raw[: -len(" deep")] if deep else raw
    return (m if ":" in m and m.split(":", 1)[0] in ("gb300", "zai") else f"gb300:{m}"), deep


def _load(path: str) -> list[Json]:
    st = os.stat(path)
    sig = (st.st_mtime, st.st_size)
    with _lock:
        hit = _cache.get(path)
        if hit and hit[0] == sig:
            return hit[1]
    newest: dict[tuple[str, str, bool], Json] = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            try:
                d = json.loads(line)
            except ValueError:
                continue
            w = window(str(d.get("unit") or ""))
            a = d.get("answer")
            if not w or not isinstance(a, dict) or not a.get("focus"):
                continue
            model, deep = model_of(str(d.get("model") or ""))
            row: Json = {"grain": w[0], "start": w[1], "end": w[2], "model": model, "deep": deep, "at": d.get("at"),
                         "secs": d.get("secs"), **{k: a.get(k) for k in KEEP if a.get(k) is not None}}
            k = (f"{w[0]} {w[1]}", model, deep)
            if k not in newest or str(row["at"] or "") >= str(newest[k]["at"] or ""):
                newest[k] = row
    rows = sorted(newest.values(), key=lambda r: (r["start"], r["grain"], r["model"]), reverse=True)
    with _lock:
        _cache[path] = (sig, rows)
    return rows


def files(root: str) -> list[str]:
    return sorted(glob.glob(os.path.join(root, "readings", "*.jsonl")))


def readings(root: str, since: str | None = None, until: str | None = None, grain: str | None = None,
             model: str | None = None, q: str | None = None, limit: int = 50, offset: int = 0) -> Json:
    """Readings newest first. since/until: a date or 'YYYY-MM-DD HH:MM' (Bangkok time, as the windows are),
    compared with the window's start. grain: day | 3h | 1h | 15m. model: substring (gb300, zai, qwen3:14b).
    q: words that must all appear in focus, work, en, th, friction or lesson (case-blind)."""
    if grain and grain not in GRAINS:
        raise ValueError(f"grain is one of {', '.join(GRAINS)}")
    src = files(root)
    rows: list[Json] = []
    for p in src:
        machine = os.path.splitext(os.path.basename(p))[0]
        rows += [r | {"machine": machine} for r in _load(p)]
    words = [w.lower() for w in (q or "").split()]

    def keep(r: Json) -> bool:
        if grain and r["grain"] != grain:
            return False
        if model and model.lower() not in r["model"].lower():
            return False
        if since and r["start"] < since:
            return False
        if until and r["start"][: len(until)] > until:
            return False
        if words:
            hay = json.dumps({k: r.get(k) for k in ("focus", "work", "en", "th", "friction", "lesson")}, ensure_ascii=False).lower()
            return all(w in hay for w in words)
        return True

    hit = [r for r in rows if keep(r)]
    hit.sort(key=lambda r: (r["start"], r["grain"], r["model"]), reverse=True)
    models: dict[str, int] = {}
    for r in hit:
        models[r["model"]] = models.get(r["model"], 0) + 1
    page = hit[offset: offset + limit]
    out: Json = {"total": len(hit), "offset": offset, "rows": page, "models": models,
                "files": [os.path.basename(p) for p in src],
                "next_offset": offset + limit if offset + limit < len(hit) else None}
    if not src:
        out["note"] = "no readings on the hub yet: relic-extract's ~/.relic-extract/report/readings.jsonl is rsynced to <root>/readings/<machine>.jsonl"
    return out
