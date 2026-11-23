"""skills.py: the skills a human typed, and the ones an AI launched on its own (MCP relic_skills, `relic5 skills`,
issues #299, #302).

Nat, 2026-11-23: "make feature of relic? about list skill". Which skills did I type, how often, in which sessions, and
how did that change (the book skills went mini-book -> complete-book -> proof-book / app-guide -> press-run)? Then:
"which ai auto use skill? without human explicit call?".

A typed skill is a `/name` (Claude Code) or `$name` (Codex) word in a user prompt of the text stream, where:

  - the session is a main session (relic-scan's tier = 'main'): subagent and workflow-agent prompts are written by an
    agent, not a human;
  - each prompt counts once per session: Claude Code stores a typed prompt twice, as `user` and as `api-request-blob`
    ~100 ms apart (same text, two msgkeys), and a message sent while the agent works ("The user sent a new message
    while you were working: ...") only as `api-request-blob`, so both types are read and identical text in one session
    is one prompt (counting rows doubled every number); a /loop re-sending the same text every tick is one prompt too;
  - the text is not a relay: it does not start with `<` (system reminders, task notifications, pasted content, channel
    messages), `[` (agent relays such as "[m5:ajfon] ...", but not "[Image #3]" or "[Pasted text #1]", which a human
    attached), `PANE ` (a herdr pane-run result) or "<box> -> <box> ..." (a relay between machines), and is not a skill's
    own text pasted back ("Base directory for this skill");
  - the name is a real skill: one of the SKILL.md files relic5 already indexes (the config layer,
    index/_config/sections.parquet: home skills by folder name, plugin skills as `plugin:name`), or a built-in command
    (BUILTIN, kind "builtin"). all=true keeps every other `/word` too, as kind "unknown".

A long prompt (>= AUTO_CHARS) whose exact text appears in AUTO_SESSIONS or more sessions is a scheduled run or a
broadcast (e.g. "/huginn — write the hourly digest ...", ~5,000 sessions), not typing: left out unless auto=true, and
counted in `excluded`.

Not seen yet: a bare slash command with no arguments ("/return", "/rrr" alone on the line). relic-scan keeps it, but
relic-extract's clean step (commands = "args") rewrites a command to "/x args" and drops it when there are no args, so
it never reaches the hub (Soul-Brews-Studio/relic-extract#57). Commands with arguments are kept, as the plain text typed.

Launched = the agents' Skill tool calls (tools stream, name 'Skill', its "skill" argument). A launch is by the AI on
its own (`ai`) when no human typed that skill in the same session before it: never typed there ("never_typed"), or
typed only later ("before_typed"). Typed-before is checked over the session's whole history, not only inside
since/until. ai=true lists the launched skills that way, with the same split by model (the session's main model) and by
project.
"""
import os
from typing import Any

from .types_ import Json

BUILTIN = ("goal", "loop", "model", "compact", "clear", "resume", "schedule", "init", "review", "security-review", "mcp",
           "status", "context", "fast", "memory", "agents", "hooks", "cost", "rename", "exit", "config", "plugin", "export",
           "effort", "statusline", "permissions", "doctor", "add-dir", "btw", "ultrareview", "code-review", "simplify")
RELAY_PREFIXES = ("<", "[", "PANE ", "Base directory for this skill")
AUTO_CHARS = 60
AUTO_SESSIONS = 10
# skill names run to 106 characters ("go-with-the-best-you-can-and-never-stop-..."); 80 missed them (#302)
WORD = r"(?:^|[\s(])[/$]([a-z][a-z0-9:_-]{1,200})"
TABLE = ("index", "_config", "sections.parquet")
MIDTURN = "The user sent a new message while you were working:"
MIDTURN_TAIL = "This is how Claude Code surfaces messages the user sends mid-turn"


def catalogue(root: str, con_rows: Any) -> list[str]:
    """Every skill name relic5 has seen a SKILL.md for: home skills by folder, plugin skills as plugin:name."""
    p = os.path.join(root, *TABLE)
    if not os.path.exists(p):
        return []
    q = p.replace("'", "''")
    rows = con_rows(f"""SELECT DISTINCT CASE WHEN path LIKE '%/plugins/cache/%'
            THEN regexp_extract(path, '/plugins/cache/[^/]+/([^/]+)/', 1) || ':' || regexp_extract(path, '/skills/([^/]+)/SKILL\\.md$', 1)
            ELSE regexp_extract(path, '/skills/([^/]+)/SKILL\\.md$', 1) END AS n
        FROM read_parquet('{q}') WHERE role = 'config-skill'""")
    out = set()
    for r in rows:
        n = (r["n"] or "").lower()
        if n and not n.endswith(":") and not n.startswith(":"):
            out.add(n)
            if ":" in n:
                out.add(n.split(":", 1)[1])   # a plugin skill is typed as /plugin:name or /name
    return sorted(out)


def _prompts_sql(src: str, meta: str | None, where_extra: list[str]) -> str:
    """One row per (session, distinct prompt body) that holds at least one /word or $word, with its words. The body is
    the text without Claude Code's mid-turn wrapper ("The user sent a new message while you were working: ... This is
    how Claude Code surfaces messages ..."), so a wrapped relay is still seen as a relay, and a wrapped copy and a plain
    copy of one text are one prompt and count toward the same repeat total."""
    lt = "ltrim(body)"
    relay = " AND ".join(f"NOT starts_with({lt}, '{p}')" for p in RELAY_PREFIXES if p != "[")
    # "[m5:ajfon] ...", "[portal ...]", "[⌘J from ...]" are relays; "[Image #3] ..." and "[Pasted text #1 ...]" are a human's own
    relay += f" AND NOT (starts_with({lt}, '[') AND NOT starts_with({lt}, '[Image') AND NOT starts_with({lt}, '[Pasted'))"
    relay += f" AND NOT regexp_matches({lt}, '^[A-Za-z0-9_.@-]+ -> [A-Za-z0-9_.@-]+')"   # "white -> m5 Laris: ..."
    tier = f"AND sid IN (SELECT sid FROM {meta} WHERE tier = 'main')" if meta else ""
    extra = "".join(f" AND {w}" for w in where_extra)
    # words, hash, length and a short snippet are taken per row, so the group carries no full text: blobs can be
    # 100 kB each, and carrying them through GROUP BY ran the hub out of its 6 GB DuckDB memory (#305)
    return f"""SELECT sid, h, min(ts_th) AS first_at, any_value(machine) AS machine, any_value(cat) AS cat,
                      any_value(chars) AS chars, any_value(snippet) AS text, any_value(words) AS words
               FROM (SELECT sid, ts_th, machine, cat, md5(body) AS h, length(body) AS chars, left(body, 300) AS snippet,
                            regexp_extract_all(lower(body), '{WORD}', 1) AS words
                     FROM (SELECT sid, ts_th, machine, cat,
                                  CASE WHEN starts_with(ltrim(text), '{MIDTURN}')   -- only wrapped texts pay for the regex
                                       THEN trim(regexp_replace(regexp_replace(text, '^\\s*{MIDTURN}\\s*', ''),
                                                                '\\s*{MIDTURN_TAIL}[\\s\\S]*$', ''))
                                       ELSE text END AS body
                           FROM {src}
                           WHERE role = 'user' AND chunk = 0 AND ts_th IS NOT NULL
                             AND (contains(text, '/') OR contains(text, '$')) {tier}{extra})
                     WHERE {relay})
               WHERE len(words) > 0
               GROUP BY sid, h"""


def _inside(at: str, since: str | None, until: str | None) -> bool:
    """The same window as the SQL filters elsewhere: ts_th >= since, and its first len(until) characters <= until."""
    return (not since or at >= since) and (not until or at[:len(until)] <= until)


def _bump(d: dict[str, int], k: str | None) -> None:
    if k:
        d[k] = d.get(k, 0) + 1


def _top(d: dict[str, int], n: int | None = None) -> dict[str, int]:
    return dict(sorted(d.items(), key=lambda x: (-x[1], x[0]))[:n])


def skills(relic: Any, since: str | None = None, until: str | None = None, project: str | None = None,
           machine: str | None = None, contains: str | None = None, top: int = 30, sessions: bool = False,
           session: str | None = None, all_words: bool = False, auto: bool = False, ai: bool = False) -> Json:
    """The skills typed by a human, or launched by an AI on its own (see the module doc). Four shapes:
    default        {skills: [{skill, kind, prompts, sessions, days, first, last, machines, projects, launched, ai, months}]}
    sessions=true  {sessions: [{sid, start, machine, project, title, prompts, skills: {name: prompts}}]}, newest first
    session=S      {session, prompts: [{at, skills, text}]}: one session's prompts that typed a skill, in order
    ai=true        {skills: [{skill, launched, ai, share, sessions, never_typed, before_typed, first, last, projects,
                    models, months}], total_launched, total_ai, by_model, by_project, by_month}"""
    src = relic.parts.source("text")
    names = catalogue(relic.parts.root, relic._rows)
    builtin = set(BUILTIN)
    known = set(names) | builtin
    top = max(1, min(int(top), 1000))
    base: Json = {"since": since, "until": until, "catalogue": len(names),
                  "note": "typed = /name or $name in a human prompt of a main session, once per session; "
                          "ai = a Skill tool call with no human /name typed before it in that session; Bangkok time"}
    where: list[str] = []   # no time filter here: typed-before needs the session's whole history
    params: list[object] = []
    if project:
        where.append("cat ILIKE ?")
        params.append(f"%{project}%")
    if machine:
        where.append("machine = ?")
        params.append(machine)
    if session:
        where.append("starts_with(sid, ?)")
        params.append(session)
    meta = relic._meta()
    calls = [] if (session or sessions) else _calls(relic, meta, since, until, project, machine, session)
    if src and (since or until):
        # typed-before needs a session's whole history, but only for the sessions active in the window: those with
        # text in it, and those with a Skill call in it (a session can launch at 11:00 what Nat typed at 08:00)
        win: list[str] = ["chunk = 0"]
        wp: list[object] = []
        if since:
            win.append("ts_th >= ?")
            wp.append(since)
        if until:
            win.append("substr(ts_th, 1, ?) <= ?")
            wp += [len(until), until]
        where.append(f"(sid IN (SELECT DISTINCT sid FROM {src} WHERE {' AND '.join(win)}) OR list_contains(?, sid))")
        params += wp + [sorted({c["sid"] for c in calls})]
    prompts = relic._rows(f"""WITH p AS ({_prompts_sql(src, meta, where)}),
                                   rep AS (SELECT h, count(DISTINCT sid) AS n FROM p GROUP BY h)
                              SELECT p.*, rep.n AS seen_in FROM p JOIN rep USING (h) ORDER BY first_at""", params) if src else []
    excluded = {"automated": 0, "unknown_words": 0}
    typed_at: dict[tuple[str, str], str] = {}   # (sid, skill) -> the first time a human typed it there, any time
    rows: list[Json] = []                        # one per (prompt, skill), inside since/until
    for p in prompts:
        inside = _inside(p["first_at"], since, until)
        if not auto and (p["chars"] or 0) >= AUTO_CHARS and (p["seen_in"] or 0) >= AUTO_SESSIONS:
            excluded["automated"] += inside
            continue
        for w in dict.fromkeys(p["words"] or []):   # each word once, in the order typed
            if w in known:
                kind = "builtin" if w in builtin and w not in names else "skill"
                k = (p["sid"], w)
                typed_at[k] = min(typed_at.get(k, p["first_at"]), p["first_at"])
            elif all_words:
                kind = "unknown"
            else:
                excluded["unknown_words"] += inside
                continue
            if not inside or (contains and contains.lower() not in w):
                continue
            rows.append({"skill": w, "kind": kind, "sid": p["sid"], "at": p["first_at"], "machine": p["machine"], "cat": p["cat"],
                         "h": p["h"], "text": p["text"]})
    base["excluded"] = excluded
    if session:
        by_prompt: dict[str, Json] = {}
        for r in rows:
            e = by_prompt.setdefault(r["h"], {"at": r["at"], "sid": r["sid"], "skills": [], "text": (r["text"] or "")[:300]})
            e["skills"].append(r["skill"])
        got = sorted(by_prompt.values(), key=lambda e: e["at"])
        return base | {"session": got[0]["sid"] if got else session, "prompts": got}
    if sessions:
        return base | {"sessions": _by_session(relic, rows, meta, top)}
    for c in calls:
        t = typed_at.get((c["sid"], c["skill"]))
        c["why"] = "never_typed" if t is None else "before_typed" if t > c["first_at"] else "typed"
    if ai:
        return base | _ai(calls, contains, top)
    launched: dict[str, int] = {}
    by_ai: dict[str, int] = {}
    for c in calls:
        _bump(launched, c["skill"])
        if c["why"] != "typed":
            _bump(by_ai, c["skill"])
    agg: dict[str, Json] = {}
    for r in rows:
        e = agg.setdefault(r["skill"], {"skill": r["skill"], "kind": r["kind"], "prompts": 0, "sids": set(), "days": set(),
                                        "first": r["at"], "last": r["at"], "machines": {}, "projects": {}, "months": {}})
        e["prompts"] += 1
        e["sids"].add(r["sid"])
        e["days"].add(r["at"][:10])
        e["first"], e["last"] = min(e["first"], r["at"]), max(e["last"], r["at"])
        _bump(e["machines"], r["machine"])
        _bump(e["projects"], r["cat"])
        _bump(e["months"], r["at"][:7])
    out = []
    for e in sorted(agg.values(), key=lambda e: (-len(e["sids"]), -e["prompts"], e["skill"]))[:top]:
        out.append({"skill": e["skill"], "kind": e["kind"], "prompts": e["prompts"], "sessions": len(e["sids"]),
                    "days": len(e["days"]), "first": e["first"], "last": e["last"], "machines": _top(e["machines"]),
                    "projects": _top(e["projects"], 3), "launched": launched.get(e["skill"], 0), "ai": by_ai.get(e["skill"], 0),
                    "months": dict(sorted(e["months"].items()))})
    return base | {"skills": out, "total_skills": len(agg), "total_prompts": len({r["h"] + r["sid"] for r in rows}),
                   "sessions": len({r["sid"] for r in rows})}


def _ai(calls: list[Json], contains: str | None, top: int) -> Json:
    """The launched skills, ranked by how many launches came with no human /name before them."""
    agg: dict[str, Json] = {}
    by_model: dict[str, list[int]] = {}
    by_project: dict[str, list[int]] = {}
    by_month: dict[str, list[int]] = {}
    total = total_ai = 0
    for c in calls:
        if contains and contains.lower() not in c["skill"]:
            continue
        is_ai = c["why"] != "typed"
        total += 1
        total_ai += is_ai
        for d, k in ((by_model, c["model"] or "?"), (by_project, c["cat"] or "?"), (by_month, c["first_at"][:7])):
            d.setdefault(k, [0, 0])
            d[k][0] += 1
            d[k][1] += is_ai
        e = agg.setdefault(c["skill"], {"skill": c["skill"], "launched": 0, "ai": 0, "sids": set(), "never_typed": 0,
                                        "before_typed": 0, "first": None, "last": None, "projects": {}, "models": {}, "months": {}})
        e["launched"] += 1
        if not is_ai:
            continue
        e["ai"] += 1
        e[c["why"]] += 1
        e["sids"].add(c["sid"])
        e["first"] = min(e["first"] or c["first_at"], c["first_at"])
        e["last"] = max(e["last"] or c["first_at"], c["first_at"])
        _bump(e["projects"], c["cat"])
        _bump(e["models"], c["model"])
        _bump(e["months"], c["first_at"][:7])
    ranked = sorted((e for e in agg.values() if e["ai"]), key=lambda e: (-e["ai"], -e["launched"], e["skill"]))[:top]
    def split(d: dict[str, list[int]], n: int | None = None) -> Json:
        return {k: {"launched": v[0], "ai": v[1]} for k, v in sorted(d.items(), key=lambda x: (-x[1][1], x[0]))[:n]}
    return {"skills": [{"skill": e["skill"], "launched": e["launched"], "ai": e["ai"], "share": round(e["ai"] / e["launched"], 3),
                        "sessions": len(e["sids"]), "never_typed": e["never_typed"], "before_typed": e["before_typed"],
                        "first": e["first"], "last": e["last"], "projects": _top(e["projects"], 3), "models": _top(e["models"], 3),
                        "months": dict(sorted(e["months"].items()))} for e in ranked],
            "total_launched": total, "total_ai": total_ai, "by_model": split(by_model, 12), "by_project": split(by_project, 12),
            "by_month": {k: {"launched": v[0], "ai": v[1]} for k, v in sorted(by_month.items())}}


def _by_session(relic: Any, rows: list[Json], meta: str | None, top: int) -> list[Json]:
    per: dict[str, Json] = {}
    for r in rows:
        e = per.setdefault(r["sid"], {"sid": r["sid"], "start": r["at"], "machine": r["machine"], "project": r["cat"],
                                      "prompts": set(), "skills": {}})
        e["start"] = min(e["start"], r["at"])
        e["prompts"].add(r["h"])
        e["skills"][r["skill"]] = e["skills"].get(r["skill"], 0) + 1
    got = sorted(per.values(), key=lambda e: e["start"], reverse=True)[:top]
    titles: dict[str, str] = {}
    if meta and got and relic.meta_has("title"):   # older relic-scan session tables have no title
        ids = [e["sid"] for e in got]
        for t in relic._rows(f"SELECT sid, title FROM {meta} WHERE list_contains(?, sid)", [ids]):
            titles[t["sid"]] = t["title"] or ""
    return [{"sid": e["sid"], "start": e["start"], "machine": e["machine"], "project": e["project"],
             "title": titles.get(e["sid"], ""), "prompts": len(e["prompts"]), "skills": e["skills"]} for e in got]


def _calls(relic: Any, meta: str | None, since: str | None, until: str | None, project: str | None, machine: str | None,
           session: str | None) -> list[Json]:
    """Every Skill tool call once (a message held by two machines is one call): sid, time, skill, project, model."""
    src = relic.parts.source("tools")
    if not src:
        return []
    join = f"LEFT JOIN {meta} m USING (sid)" if meta else ""
    cat = "coalesce(any_value(m.cat), any_value(t.cat))" if meta else "any_value(t.cat)"
    model = "any_value(m.models)[1]" if meta and relic.meta_has("models") else "NULL"
    where = ["t.chunk = 0", "t.name = 'Skill'", "json_valid(t.text)"]
    params: list[object] = []
    if since:
        where.append("t.ts_th >= ?")
        params.append(since)
    if until:
        where.append("substr(t.ts_th, 1, ?) <= ?")
        params += [len(until), until]
    if machine:
        where.append("t.machine = ?")
        params.append(machine)
    if session:
        where.append("starts_with(t.sid, ?)")
        params.append(session)
    having = ""
    if project:
        having = f"HAVING {cat} ILIKE ?"
        params.append(f"%{project}%")
    rows = relic._rows(f"""SELECT t.sid AS sid, min(t.ts_th) AS first_at, {cat} AS cat, {model} AS model,
                                  lower(json_extract_string(any_value(t.text), '$.skill')) AS skill
                           FROM {src} t {join} WHERE {' AND '.join(where)}
                           GROUP BY t.msgkey, t.sid {having}""", params)
    return [r for r in rows if r["skill"] and r["first_at"]]
