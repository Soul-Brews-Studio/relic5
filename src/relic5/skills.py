"""skills.py: the skills a human typed, and how often the agents launched them (MCP relic_skills, `relic5 skills`, issue #299).

Nat, 2026-11-23: "make feature of relic? about list skill". Which skills did I type, how often, in which sessions, and
how did that change (the book skills went mini-book -> complete-book -> proof-book / app-guide -> press-run)?

A typed skill is a `/name` (Claude Code) or `$name` (Codex) word in a user prompt of the text stream, where:

  - the session is a main session (relic-scan's tier = 'main'): subagent and workflow-agent prompts are written by an
    agent, not a human;
  - each prompt counts once per session: Claude Code stores a typed prompt twice, as `user` and as `api-request-blob`
    ~100 ms apart (same text, two msgkeys), and a message sent while the agent works ("The user sent a new message
    while you were working: ...") only as `api-request-blob`, so both types are read and identical text in one session
    is one prompt (counting rows doubled every number);
  - the text is not a relay: it does not start with `<` (system reminders, task notifications, pasted content, channel
    messages), `[` (agent relays such as "[m5:ajfon] ...", but not "[Image #3]" or "[Pasted text #1]", which a human
    attached), `PANE ` (a herdr pane-run result) or "<box> -> <box> ..." (a relay between machines), and is not a skill's
    own text pasted back ("Base directory for this skill");
  - the name is a real skill: one of the SKILL.md files relic5 already indexes (the config layer,
    index/_config/sections.parquet: home skills by folder name, plugin skills as `plugin:name`), or a built-in command
    (BUILTIN, kind "builtin"). all=true keeps every other `/word` too, as kind "unknown".

A prompt counts once per session (a /loop re-sends the same text every tick).

Not seen yet: a bare slash command with no arguments ("/return", "/rrr" alone on the line). relic-scan keeps it, but
relic-extract's clean step (commands = "args") rewrites a command to "/x args" and drops it when there are no args, so
it never reaches the hub (Soul-Brews-Studio/relic-extract#57). Commands with arguments are kept, as the plain text typed. A long prompt (>= AUTO_CHARS) whose exact
text appears in AUTO_SESSIONS or more sessions is a scheduled run (e.g. "/huginn — write the hourly digest ...", ~5,000
sessions), not typing: left out unless auto=true, and counted in `excluded`.

Launched = the agents' Skill tool calls (tools stream, name 'Skill', its "skill" argument), whoever asked for them.
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
WORD = r"(?:^|[\s(])[/$]([a-z][a-z0-9:_-]{1,80})"
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
    return f"""SELECT sid, md5(body) AS h, min(ts_th) AS first_at, any_value(machine) AS machine, any_value(cat) AS cat,
                      any_value(length(body)) AS chars, any_value(body) AS text,
                      regexp_extract_all(lower(any_value(body)), '{WORD}', 1) AS words
               FROM (SELECT *, trim(regexp_replace(regexp_replace(text, '^\\s*{MIDTURN}\\s*', ''),
                                                   '\\s*{MIDTURN_TAIL}[\\s\\S]*$', '')) AS body
                     FROM {src}
                     WHERE role = 'user' AND chunk = 0 AND ts_th IS NOT NULL
                       AND (contains(text, '/') OR contains(text, '$')) {tier}{extra})
               WHERE {relay}
               GROUP BY sid, md5(body)"""


def skills(relic: Any, since: str | None = None, until: str | None = None, project: str | None = None,
           machine: str | None = None, contains: str | None = None, top: int = 30, sessions: bool = False,
           session: str | None = None, all_words: bool = False, auto: bool = False) -> Json:
    """The skills typed by a human (see the module doc). Three shapes:
    default        {skills: [{skill, kind, prompts, sessions, days, first, last, machines, projects, launched, months}]}
    sessions=true  {sessions: [{sid, start, machine, project, title, prompts, skills: {name: prompts}}]}, newest first
    session=S      {session, prompts: [{at, skills, text}]}: one session's prompts that typed a skill, in order"""
    src = relic.parts.source("text")
    names = catalogue(relic.parts.root, relic._rows)
    builtin = set(BUILTIN)
    known = set(names) | builtin
    base: Json = {"since": since, "until": until, "catalogue": len(names),
                  "note": "typed = /name or $name in a human prompt of a main session, once per session; Bangkok time"}
    if not src:
        return base | {"skills": [], "sessions": [], "total_prompts": 0}
    where: list[str] = []
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
    if machine:
        where.append("machine = ?")
        params.append(machine)
    if session:
        where.append("starts_with(sid, ?)")
        params.append(session)
    meta = relic._meta()
    prompts = relic._rows(f"""WITH p AS ({_prompts_sql(src, meta, where)}),
                                   rep AS (SELECT h, count(DISTINCT sid) AS n FROM p GROUP BY h)
                              SELECT p.*, rep.n AS seen_in FROM p JOIN rep USING (h) ORDER BY first_at""", params)
    excluded = {"automated": 0, "unknown_words": 0}
    rows: list[Json] = []   # one per (prompt, skill)
    for p in prompts:
        if not auto and (p["chars"] or 0) >= AUTO_CHARS and (p["seen_in"] or 0) >= AUTO_SESSIONS:
            excluded["automated"] += 1
            continue
        for w in dict.fromkeys(p["words"] or []):   # each word once, in the order typed
            if w in known:
                kind = "builtin" if w in builtin and w not in names else "skill"
            elif all_words:
                kind = "unknown"
            else:
                excluded["unknown_words"] += 1
                continue
            if contains and contains.lower() not in w:
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
    launched = _launched(relic, since, until, project, machine)
    agg: dict[str, Json] = {}
    for r in rows:
        e = agg.setdefault(r["skill"], {"skill": r["skill"], "kind": r["kind"], "prompts": 0, "sids": set(), "days": set(),
                                        "first": r["at"], "last": r["at"], "machines": {}, "projects": {}, "months": {}})
        e["prompts"] += 1
        e["sids"].add(r["sid"])
        e["days"].add(r["at"][:10])
        e["first"], e["last"] = min(e["first"], r["at"]), max(e["last"], r["at"])
        e["machines"][r["machine"]] = e["machines"].get(r["machine"], 0) + 1
        if r["cat"]:
            e["projects"][r["cat"]] = e["projects"].get(r["cat"], 0) + 1
        e["months"][r["at"][:7]] = e["months"].get(r["at"][:7], 0) + 1
    out = []
    for e in sorted(agg.values(), key=lambda e: (-len(e["sids"]), -e["prompts"], e["skill"]))[:max(1, min(int(top), 1000))]:
        out.append({"skill": e["skill"], "kind": e["kind"], "prompts": e["prompts"], "sessions": len(e["sids"]),
                    "days": len(e["days"]), "first": e["first"], "last": e["last"],
                    "machines": dict(sorted(e["machines"].items(), key=lambda x: -x[1])),
                    "projects": dict(sorted(e["projects"].items(), key=lambda x: -x[1])[:3]),
                    "launched": launched.get(e["skill"], 0), "months": dict(sorted(e["months"].items()))})
    return base | {"skills": out, "total_skills": len(agg), "total_prompts": len({r["h"] + r["sid"] for r in rows}),
                   "sessions": len({r["sid"] for r in rows})}


def _by_session(relic: Any, rows: list[Json], meta: str | None, top: int) -> list[Json]:
    per: dict[str, Json] = {}
    for r in rows:
        e = per.setdefault(r["sid"], {"sid": r["sid"], "start": r["at"], "machine": r["machine"], "project": r["cat"],
                                      "prompts": set(), "skills": {}})
        e["start"] = min(e["start"], r["at"])
        e["prompts"].add(r["h"])
        e["skills"][r["skill"]] = e["skills"].get(r["skill"], 0) + 1
    got = sorted(per.values(), key=lambda e: e["start"], reverse=True)[:max(1, min(int(top), 1000))]
    titles: dict[str, str] = {}
    if meta and got and relic.meta_has("title"):   # older relic-scan session tables have no title
        ids = [e["sid"] for e in got]
        for t in relic._rows(f"SELECT sid, title FROM {meta} WHERE list_contains(?, sid)", [ids]):
            titles[t["sid"]] = t["title"] or ""
    return [{"sid": e["sid"], "start": e["start"], "machine": e["machine"], "project": e["project"],
             "title": titles.get(e["sid"], ""), "prompts": len(e["prompts"]), "skills": e["skills"]} for e in got]


def _launched(relic: Any, since: str | None, until: str | None, project: str | None, machine: str | None) -> dict[str, int]:
    """Skill tool calls by skill name (the agents launched them; a human may or may not have asked)."""
    src = relic.parts.source("tools")
    if not src:
        return {}
    where = ["chunk = 0", "name = 'Skill'"]
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
    if machine:
        where.append("machine = ?")
        params.append(machine)
    rows = relic._rows(f"""SELECT lower(json_extract_string(text, '$.skill')) AS s, count(DISTINCT msgkey) AS n FROM {src}
                           WHERE {' AND '.join(where)} AND json_valid(text) GROUP BY 1""", params)
    return {r["s"]: int(r["n"]) for r in rows if r["s"]}
