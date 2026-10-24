"""oracles.py: one oracle at a time, brought to the human (Nat, 2026-10-24: "1 page that each oracle bring to human /
collect data and generate a prompt to create a character / style? and enlightenment").

Every oracle keeps a ψ vault; relic-scan lists them per machine in meta/vaults.json (name, path, kind, notes, the
count per section) and relic-extract pushes the notes themselves to parts/<machine>/vault/notes.parquet (text,
section, title, path, ts, the vault's name). The hub embeds nothing and runs no model, so the "character" and the
"enlightenment" are prompts built from the oracle's own words: what it says it is (memory/resonance, the soul notes),
what it learned (memory/learnings), how its sessions went (memory/retrospectives), the rules its human set (Claude
Code memory notes, feedback and user kinds, for the oracle's repo) and its newest sessions. Paste one into Claude, or
let an agent read the same fields over MCP. Nothing is invented: every line in a prompt is quoted from a note, with
the note's path.

  listing(relic)        every oracle that owns a vault (kind "own"; copies and links fold in), biggest first
  portrait(relic, name) one oracle: counts, its notes by section, sessions, rules, and the two prompts
"""
import glob, json, os, re
from collections import Counter
from typing import TYPE_CHECKING

from .types_ import Json

if TYPE_CHECKING:
    from .query import Relic5

SOUL = ("memory/resonance", "resonance", "soul", "identity", "memory/soul")
LEARN = ("memory/learnings", "learnings")
RETRO = ("memory/retrospectives", "retrospectives", "retros")
STOP = set("the a an and or of to in on for with is are was be it this that at by from as not no we you i our my md"
           " oracle session day note notes new into its".split())


def inside(section: str, tops: tuple[str, ...]) -> bool:
    """Is a section one of tops or under one ("memory/learnings/2026-10")? Not a prefix match: "soul-brews-studio/…"
    is a folder of copied notes, not the soul."""
    return any(section == t or section.startswith(t + "/") for t in tops)


def _vaults(root: str) -> list[Json]:
    out: list[Json] = []
    for f in sorted(glob.glob(os.path.join(root, "parts", "*", "meta", "vaults.json"))):
        machine = f.split(os.sep)[-3]
        try:
            vs = json.load(open(f)).get("vaults", [])
        except (OSError, ValueError, AttributeError):
            continue
        for v in vs:
            if isinstance(v, dict) and v.get("name"):
                out.append(v | {"machine": machine})
    return out


def listing(relic: "Relic5") -> Json:
    """-> {oracles: [{name, path, machines, notes, sections, newest}], vaults}. One row per oracle name: the copy with
    the most notes speaks for it; every machine that holds an own copy is listed."""
    by: dict[str, Json] = {}
    vs = _vaults(relic.parts.root)
    for v in vs:
        if v.get("kind") not in (None, "", "own"):
            continue
        n = str(v["name"])
        cur = by.get(n)
        if cur is None or int(v.get("notes") or 0) > int(cur.get("notes") or 0):
            by[n] = {"name": n, "path": v.get("path"), "notes": int(v.get("notes") or 0), "sections": v.get("sections") or {},
                     "newest": v.get("newest_ms"), "machines": sorted(set((cur or {}).get("machines", [])) | {v["machine"]})}
        else:
            cur["machines"] = sorted(set(cur["machines"]) | {v["machine"]})
    rows = sorted(by.values(), key=lambda r: -r["notes"])
    for r in rows:
        r["soul"] = sum(c for s, c in r["sections"].items() if inside(s, SOUL))
        r["learnings"] = sum(c for s, c in r["sections"].items() if inside(s, LEARN))
        r["retros"] = sum(c for s, c in r["sections"].items() if inside(s, RETRO))
    return {"oracles": rows, "vaults": len(vs)}


def _notes(relic: "Relic5", name: str, sections: tuple[str, ...], limit: int) -> list[Json]:
    files = glob.glob(os.path.join(relic.parts.root, "parts", "*", "vault", "notes.parquet"))
    if not files:
        return []
    lst = ", ".join("'" + f.replace("'", "''") + "'" for f in files)
    cond = " OR ".join("section = ? OR section LIKE ?" for _ in sections)
    params: list[object] = [name]
    for s in sections:
        params += [s, s + "/%"]
    rows = relic._rows(f"""SELECT any_value(title) AS title, any_value(path) AS path, any_value(section) AS section,
                              max(ts) AS ts, string_agg(text, '' ORDER BY chunk) AS text
                           FROM (SELECT DISTINCT msgkey, chunk, title, path, section, ts, text FROM read_parquet([{lst}], union_by_name = true)
                                 WHERE cat = ? AND ({cond}))
                           GROUP BY msgkey ORDER BY ts DESC LIMIT ?""", params + [limit * 3])
    seen: set[str] = set()
    out: list[Json] = []
    for r in rows:   # the same note in two folders (a worktree's ψ, an archive) is one note
        k = str(r.get("title") or r.get("path"))
        if k not in seen:
            seen.add(k)
            out.append(r)
    return out[:limit]


def _first(text: str, n: int) -> str:
    """The note's body without its frontmatter, as one paragraph of at most n characters."""
    t = re.sub(r"^---\n.*?\n---\n", "", text or "", flags=re.S)
    t = re.sub(r"\s+", " ", re.sub(r"^#+\s*", "", t, flags=re.M)).strip()
    return t if len(t) <= n else t[: n - 1].rsplit(" ", 1)[0] + "…"


_PORTRAITS: dict[tuple[object, ...], Json] = {}


def _stamp(root: str) -> tuple[float, ...]:
    """What a portrait is made from, by file time: every machine's vault notes and vaults.json, and the memory index."""
    fs = sorted(glob.glob(os.path.join(root, "parts", "*", "vault", "notes.parquet")) + glob.glob(os.path.join(root, "parts", "*", "meta", "vaults.json"))
                + [os.path.join(root, "index", "_memory", "notes.parquet")])
    return tuple(os.path.getmtime(f) for f in fs if os.path.exists(f))


def portrait(relic: "Relic5", name: str) -> Json:
    """One oracle's page, kept until its sources change (2.4 s a call before, measured 2026-10-25 on white)."""
    key = (name, _stamp(relic.parts.root))
    if key in _PORTRAITS:
        return _PORTRAITS[key]
    out = _portrait(relic, name)
    if "error" not in out:
        if len(_PORTRAITS) > 64:
            _PORTRAITS.pop(next(iter(_PORTRAITS)))
        _PORTRAITS[key] = out
    return out


def _portrait(relic: "Relic5", name: str) -> Json:
    from .memory import listing as memory_listing
    row = next((o for o in listing(relic)["oracles"] if o["name"] == name), None)
    if row is None:
        return {"error": f"no oracle named {name} on this hub"}
    soul = _notes(relic, name, SOUL, 8)
    learn = _notes(relic, name, LEARN, 14)
    retro = _notes(relic, name, RETRO, 6)
    repo = re.sub(r"[^A-Za-z0-9]", "-", str(row.get("path") or "").removesuffix("/ψ").rstrip("/")).lstrip("-")
    short = re.sub(r"^(opt-Code|Users-[^-]+(-Code)?|home-[^-]+(-Code)?)-github-com-", "", repo)
    rules = [n for n in memory_listing(relic.parts.root)["notes"] if n.get("project", "").endswith(short) and n.get("type") in ("feedback", "user")][:12]
    sessions: list[Json] = []
    try:
        res = relic.sessions(repo=name, limit=8)
        sessions = [{"sid": s.get("uuid") or s.get("sid"), "name": s.get("name"), "ts": s.get("endedAt") or s.get("last_ts")} for s in res.get("sessions", [])]
    except Exception:
        sessions = []
    words = Counter(w for n in learn + retro + soul for w in re.findall(r"[a-z][a-z0-9-]{2,}", str(n.get("title") or "").lower()) if w not in STOP)

    def lines(ns: list[Json], n: int) -> str:
        return "\n".join(f"- {_first(x.get('text') or '', n)} (ψ/{x.get('path')})" for x in ns) or "- (none on the hub yet)"

    character = f"""You are {name}, an oracle in Nat's fleet. Speak and work the way the notes below show {name} does. Do not add traits the notes do not show.

Who {name} says it is (its own soul notes, newest first):
{lines(soul, 420)}

What {name} has learned (its learnings):
{lines(learn[:8], 260)}

Rules its human set for it (Claude Code memory notes):
{chr(10).join(f"- {r.get('title','').replace('_', ' ')}: {r.get('description','')}" for r in rules) or "- (none on the hub yet)"}

Describe {name}'s character in one paragraph, then its voice and style as 5 short rules a writer could follow, then 3 sentences {name} would say. Quote the note behind each claim."""

    enlighten = f"""Here is what {name} wrote down lately: its newest learnings and retrospectives, from its ψ vault.

Learnings:
{lines(learn, 320)}

Retrospectives:
{lines(retro, 420)}

From these notes only: what has {name} come to understand? Name the 3 to 5 insights that run through them, each with the notes that show it, then one thing {name} should carry forward and one it should let go. Say plainly where the notes are thin."""

    pet = f"""Design the desk pet for {name}, for Pet Studio (studio_auto_sprite / studio_create_pack: one character
picture, then its seven state animations: idle, busy, attention, celebrate, dizzy, heart, sleep).

Draw one small character, front-facing, on a plain background, readable at 64x80 pixels, that shows who {name} is
from its own notes below. Pick one body colour and one accent, a simple silhouette, and one prop or mark that stands
for what it does. Then say in one line each how it moves in the seven states.

Who {name} says it is:
{lines(soul[:4], 300)}

What it works on (the words its notes use most): {", ".join(w for w, _ in words.most_common(12)) or "(not enough notes yet)"}

When the pack is made, keep it on {name}'s page: relic_artifact_put {{"oracle": "{name}", "filename": "<state>.gif", "data": "<base64>", "prompt": "<this prompt>"}}."""

    return {"name": name, "path": row.get("path"), "machines": row["machines"], "notes": row["notes"], "sections": row["sections"],
            "newest": row.get("newest"), "repo": short, "soul": [{"title": x["title"], "path": x["path"], "ts": x["ts"], "text": _first(x["text"], 900)} for x in soul],
            "learnings": [{"title": x["title"], "path": x["path"], "ts": x["ts"], "text": _first(x["text"], 400)} for x in learn],
            "retros": [{"title": x["title"], "path": x["path"], "ts": x["ts"], "text": _first(x["text"], 400)} for x in retro],
            "rules": [{"title": r.get("title"), "description": r.get("description"), "link": r.get("link")} for r in rules],
            "sessions": sessions, "words": [[w, n] for w, n in words.most_common(30)],
            "prompts": {"character": character, "enlighten": enlighten, "pet": pet}}
