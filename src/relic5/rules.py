"""rules.py: one rule's chain, read from what relic5 already holds (issue #269 step 2; relic_rule).

The fleet re-issues a rule until someone is annoyed, and nothing notices: "Tailscale is the only VPN" was written as
eight memory notes in eight repos between 2026-04-02 and 2026-10-24. Given a phrase, rule() assembles:

  restatements  memory notes that carry the phrase's key word, oldest first, each with the repo it was written in and
                the cwd its project folder encodes. They are CANDIDATES: a phrase cannot tell a restatement from a note
                that only mentions the word, so none counts as "re-issued" until a relic_rule_event binds it to a rule
                id (#270). The candidate count is reported next to the triple, never hidden: an unbound restatement is
                itself the sign that the rule has no identity yet.
  config        every current CLAUDE.md / AGENTS.md / SKILL.md section (the config layer) that carries every word of
                the phrase, and the older wordings of it the hub has seen.
  reachability  for each restatement, the config files that load at its cwd: the real parent chain, walked upward
                from the cwd (the repo, its org, its host, the ghq root; a worktree's wt/<slug> reaches its repo's own
                file), plus the global ~/.claude*/CLAUDE.md of the accounts on that machine. Not a fixed ladder: any
                directory holding a CLAUDE.md on the way up counts. Each answer says what it rests on: "dated by its
                heading" (the rule's own "(Nat, 2026-10-22)") or "seen since" (the first push that held it). relic5
                never held these files before the config layer, so an absence before first_seen is not observed.
  contradictions  with forbids (the retired things: "netbird", "192.168.", "black.local"): every current memory note
                and config section with a sentence that names one as the place something is (an address, a host, a
                route verb) and carries no retirement word (no, never, retired, deprecated, no longer, history...).
                Time-aware: only notes written on or after the term's retirement date, which is the first restatement
                that names the term. A note naming NetBird before NetBird was retired is history, not a contradiction.
                A note marked "Superseded <date>" / "keep as history" is flagged but acknowledged, and not counted
                live. Flag, never fix: nothing here writes to any file.
  digs          the recorded search chains (trace.searched) that asked for the key word or landed on one of the
                rule's notes or sections: an agent that had to dig for a rule shows the rule was not where it worked.

  triple        re-issued N (bound, 0 until #270) · candidates C · dug for M · contradicted K live (of F flagged)
"""
import os, re
from typing import Any

from . import store as rfs
from .types_ import Json

STOP = {"the", "and", "for", "are", "with", "not", "use", "any", "all", "one", "our", "its", "this", "that", "from"}
RULE_ROLES = ("memory-feedback", "memory-project", "memory-user", "memory-reference", "memory-note")

NEG = re.compile(r"(?i)\b(?:no|not|never|don'?t|do not|isn'?t|aren'?t|without|retire[sd]?|retiring|deprecated|no longer|"
                 r"replaced|removed?|dead|legacy|history|historical|superseded|was|were|used to|stop(?:ped)?|"
                 r"uninstall(?:ed)?|burned|banned|forbidden|avoid|instead of|rather than|disconnected|gone|old|"
                 r"went away|dropped)\b|\bnever\b|ไม่")   # last: Thai "mai" (not)
PLACE = [("an IP address", re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}\b")),
         ("a URL", re.compile(r"://")),
         ("a host name", re.compile(r"(?i)\b[\w-]+\.(?:local|netbird|wg|lan|internal)\b")),
         ("a port", re.compile(r"(?<![\w.]):\d{2,5}\b")),
         ("a route verb", re.compile(r"(?i)\b(?:reach(?:es|ed)?|serves?|served|serving|via|over|connects?|connected|ssh|curl|"
                                     r"listens?|listening|bind|bound|routes?|routed|lives?|runs? on|points? at|open|uses?|"
                                     r"address|interface|peer)\b"))]
ACK = re.compile(r"(?i)\bsuperseded\b[^\n]{0,40}?(\d{4}-\d\d-\d\d)|\bkeep (?:this |it )?as history\b")
# sentences: at . ! ?, a blank line, or a new list item / table row / heading; a wrapped line stays in its sentence
# ("- **Do NOT**: write ... a NetBird address (*.netbird,\n  black.oracle.netbird)" is one sentence with its "NOT")
_SENT = re.compile(r"(?<=[.!?])\s+|\n\s*\n|\n(?=\s*(?:[-*+|#>]|\d+[.)]\s))")


def words_of(phrase: str) -> list[str]:
    return [w for w in re.findall(r"[\w.-]+", phrase.lower()) if len(w) > 2 and w not in STOP] or phrase.lower().split()


def _read(root: str, d: str, f: str, cols: list[str] | None = None) -> list[Json]:
    p = os.path.join(root, "index", d, f)
    if not rfs.exists(p):
        return []
    t = rfs.read_parquet(p)
    return [r for r in t.to_pylist()]


def _enc(path: str) -> str:
    return re.sub(r"[/.]", "-", path)


def known_dirs(sections: list[Json]) -> set[str]:
    """Every directory of the ghq tree that holds a config file: 'github.com/laris-co/neo-oracle', 'github.com', ''."""
    out: set[str] = set()
    for s in sections:
        sc = str(s.get("scope") or "")
        if sc.startswith("ghq/"):
            out.add(os.path.dirname(sc[4:]))
    return out


def cwd_of(project: str, dirs: set[str]) -> str | None:
    """The ghq-relative directory a memory note's project folder names ('-opt-Code-github-com-laris-co-neo-oracle-wt-x'
    -> 'github.com/laris-co/neo-oracle'): the longest known directory whose encoding ends the folder name or is followed
    by '-'. The folder's encoding is lossy (/ . - all become -), so only directories the config layer knows can match."""
    best: str | None = None
    for d in dirs:
        if not d:
            continue
        e = "-" + _enc(d)
        i = project.find(e)
        if i >= 0 and (i + len(e) == len(project) or project[i + len(e)] == "-") and (best is None or len(d) > len(best)):
            best = d
    return best


def chain_at(cwd: str | None, machine: str, home: str, sections: list[Json]) -> list[str]:
    """The config files that load at cwd, as their scopes: every ghq-tree file whose directory is cwd or one of its
    parents (walked from the path, any depth), and the home CLAUDE.md / AGENTS.md of each account on this machine
    using this home."""
    parts = (cwd or "").split("/") if cwd else []
    up = {"/".join(parts[:i]) for i in range(len(parts) + 1)}
    out: set[str] = set()
    for s in sections:
        sc = str(s.get("scope") or "")
        if sc.startswith("ghq/"):
            if os.path.dirname(sc[4:]) in up and (cwd or os.path.dirname(sc[4:]) == ""):
                out.add(sc)
        elif re.match(rf"[^:]+:home/{re.escape(home)}/(CLAUDE|AGENTS)\.md$", sc) and machine in (s.get("machines") or []):
            out.add(sc)
    return sorted(out)


def _carries(text: str, words: list[str]) -> bool:
    t = text.lower()
    return all(w in t for w in words)


def flag(text: str, terms: list[str]) -> list[Json]:
    """The sentences of a text that name a retired term as a live place: [{term, cue, sentence}]. A sentence with any
    retirement word is not flagged; neither is one that names the term without an address, host, port, URL or route verb."""
    out: list[Json] = []
    for sent in _SENT.split(text):
        low = sent.lower()
        hit = next((t for t in terms if t.lower() in low), None)
        if not hit or NEG.search(sent):
            continue
        cue = next((name for name, rx in PLACE if rx.search(sent)), None)
        if cue:
            out.append({"term": hit, "cue": cue, "sentence": " ".join(sent.split())[:240]})
    return out


def _link(r: Json) -> str:
    return f"relic5://{r['month']}/{r['msgkey']}"


def commits(root: str, terms: list[str]) -> list[Json]:
    """The git commits (gitlog.py's table) whose text names any of the terms, read whole: never a snippet, since the
    sentence that matters can sit anywhere in a message."""
    p = os.path.join(root, "index", "_git", "commits.parquet")
    if not terms or not rfs.exists(p):
        return []
    import duckdb
    con = rfs.duck(duckdb.connect(), root)
    where = " OR ".join(["contains(lower(text), ?)"] * len(terms))
    cur = con.execute(f"SELECT msgkey, month, ts, repo, hash, title, text FROM read_parquet('{p}') WHERE {where}", [t.lower() for t in terms])
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def commit_total(root: str) -> int:
    p = os.path.join(root, "index", "_git", "commits.parquet")
    if not rfs.exists(p):
        return 0
    import duckdb
    return int(rfs.duck(duckdb.connect(), root).execute(f"SELECT count(*) FROM read_parquet('{p}')").fetchone()[0])  # type: ignore[index]


def own_repos(root: str, notes: list[Json], dirs: set[str]) -> set[str]:
    """The fleet's own repos ('github.com/org/repo'): one with a commit gitlog.py kept (it keeps only our commits of
    open-source clones) or one an agent's memory folder names."""
    out = {str(cwd) for n in notes if (cwd := cwd_of(str(n["sid"] or "")[len("memory:"):], dirs)) and cwd.count("/") >= 2}
    out = {"/".join(c.split("/")[:3]) for c in out}
    p = os.path.join(root, "index", "_git", "commits.parquet")
    if rfs.exists(p):
        import duckdb
        con = rfs.duck(duckdb.connect(), root)
        out |= {str(r[0]) for r in con.execute(f"SELECT DISTINCT repo FROM read_parquet('{p}')").fetchall() if r[0]}
    return out


def rule(root: str, phrase: str, forbids: list[str] | None = None, since: str | None = None, until: str | None = None,
         searched: Any = None, retired_at: dict[str, str] | None = None) -> Json:
    from .query import UsageError
    words = words_of(phrase)
    if not phrase.strip() or not words:
        raise UsageError("relic_rule needs a phrase: the rule's own words ('tailscale only')")
    key = max(words, key=len)
    forbids = [f.strip() for f in (forbids or []) if f.strip()]
    notes = [n for n in _read(root, "_memory", "notes.parquet") if (not since or n["ts"] >= since) and (not until or n["ts"][:10] <= until)]
    secs = _read(root, "_config", "sections.parquet")
    cur = [s for s in secs if s.get("current")]
    dirs = known_dirs(cur)

    pre: list[tuple[Json, list[Json]]] = []
    def about(n: Json) -> bool:   # a note ABOUT the rule: the key word in its title or first paragraph
        head = (str(n["title"] or "") + "\n" + (n["text"] or "").split("\n\n", 1)[0]).lower()
        return n["role"] in RULE_ROLES and key in head

    for n in notes:
        f = flag(n["text"] or "", forbids) if forbids and not about(n) else []
        pre.append((n, f))

    rest: list[Json] = []
    for n, f in pre:
        if not about(n):
            continue
        project = str(n["sid"] or "")[len("memory:"):]
        cwd = cwd_of(project, dirs)
        machine = (n.get("machines") or [n.get("machine")])[0]
        loads = chain_at(cwd, machine, n.get("engine") or "claude", cur)
        carry = [s for s in cur if s["scope"] in loads and _carries(s["text"] or "", words)]
        carrying = sorted({s["scope"] for s in carry})
        # then: only what existed when the note was written, by the section's heading date, else when the hub first saw it
        then = sorted({s["scope"] for s in carry if str(s.get("dated") or str(s.get("first_seen"))[:10]) <= n["ts"][:10]})
        rest.append({"ts": n["ts"], "repo": n["cat"], "name": n["title"], "role": n["role"], "link": _link(n),
                     "machines": n.get("machines"), "cwd": cwd, "project": project, "origin": n.get("origin"),
                     "names": [t for t in forbids if t.lower() in (n["text"] or "").lower()],
                     "loading": loads, "carried_by": carrying, "carried_then": then,
                     "reachable": bool(carrying) if loads else None, "reachable_then": bool(then) if loads else None})
    rest.sort(key=lambda r: r["ts"])
    by_key = {_link(n): n for n in notes}

    # each retired term's own date (a note before it is history, not a contradiction): the earliest of a restatement
    # that names the term in a sentence with a retirement word ("not WireGuard", "NetBird is deprecated"), a config
    # section carrying the rule that names it (its heading date), or a date given by the caller (retired_at).
    first = rest[0]["ts"] if rest else None
    retired: dict[str, str | None] = {}
    retired_by: dict[str, str] = {}
    for t in forbids:
        ev: list[tuple[str, str]] = []
        if retired_at and retired_at.get(t):
            ev.append((str(retired_at[t]), "given"))
        for r, n in ((r, by_key[r["link"]]) for r in rest):
            if any(t.lower() in x.lower() and NEG.search(x) for x in _SENT.split(n["text"] or "")):
                ev.append((r["ts"], f"memory {r['repo']}/{r['name']}"))
                break
        for sc in secs:
            if t.lower() in (sc["text"] or "").lower() and _carries(sc["text"] or "", words):
                ev.append(((sc["ts"] if sc.get("dated") else str(sc.get("first_seen"))), f"config {sc['scope']} \u203a {sc['title']}"))
        given = [e for e in ev if e[1] == "given"]
        best = given[0] if given else min(ev) if ev else None
        retired[t] = best[0] if best else None
        retired_by[t] = best[1] if best else f"no retirement found for it: from the rule's first restatement ({str(first)[:10]})"

    config = []
    for s in sorted(secs, key=lambda s: (s["scope"], s["section"], s.get("first_seen") or "")):
        if not _carries(s["text"] or "", words):
            continue
        home = not str(s["scope"]).startswith("ghq/")
        config.append({"scope": s["scope"], "file": s["file"], "title": s["title"], "current": s["current"],
                       "dated": s.get("dated"), "first_seen": s.get("first_seen"), "last_seen": s.get("last_seen"),
                       "accounts": s.get("accounts"), "link": _link(s),
                       "since": (f"dated {s['dated']} by its heading" if s.get("dated") else f"seen since {str(s.get('first_seen'))[:10]}")
                                + ("" if s["current"] else f", replaced (last seen {str(s.get('last_seen'))[:10]})"),
                       "basis": "heading date" if s.get("dated") else "observed",
                       "global": home and s["file"] == "CLAUDE.md"})

    flags: list[Json] = []
    if forbids:
        for n, f0 in pre:
            # only sentences written after their term was retired (a note naming NetBird before then is history)
            f = [x for x in f0 if not ((retired.get(x["term"]) or first) and n["ts"] < str(retired.get(x["term"]) or first))]
            if f:
                x = f[0]
                since_t = retired.get(x["term"]) or first
                ack = ACK.search(n["text"] or "")
                where = [f"{m}:~/.{n.get('engine') or 'claude'} memory/{str(n['sid'] or '')[len('memory:'):]}" for m in (n.get("machines") or [])]
                flags.append({"ts": n["ts"], "kind": "memory", "repo": n["cat"], "name": n["title"], "link": _link(n),
                              "where": where, "weight": 4, "loads": "a memory note (read when recalled)", **x, "sentences": f, "retired_since": since_t,
                              "acknowledged": (f"marked superseded {ack.group(1)}" if ack and ack.group(1) else "marked as history") if ack else None,
                              "reason": f"names {x['term']!r} as a place in use ({x['cue']}) with no retirement word in the sentence,"
                                        f" written {n['ts'][:10]}, after the rule named it retired ({str(since_t)[:10]})"})
        own = own_repos(root, notes, dirs)
        swept_config = 0
        for s in cur:
            path = str(s["scope"])
            if path.startswith("ghq/") and path.count("/") >= 4 and "/".join(path[4:].split("/")[:3]) not in own:
                continue   # a clone of someone else's repo (netbirdio/netbird documents NetBird): not the fleet's rule to break
            if _carries(s["text"] or "", words):
                continue   # the rule's own section names what it retires
            swept_config += 1
            fs = flag(s["text"] or "", forbids)
            if fs:
                x = fs[0]
                home = not path.startswith("ghq/")
                weight, reach = ((0, "loads into every session of " + ", ".join(s.get("accounts") or [])) if home and s["file"] in ("CLAUDE.md", "AGENTS.md")
                                 else (1, "a skill of " + ", ".join(s.get("accounts") or [])) if s["role"] == "config-skill"
                                 else (2, "loads under the whole " + (os.path.dirname(path[4:]) or "ghq root") + " tree") if path.count("/") < 4
                                 else (3, "loads in " + "/".join(path[4:].split("/")[:3])))
                where = [q.replace(":home/", ":~/.", 1) for q in (s.get("paths") or [])]
                flags.append({"ts": s.get("first_seen"), "kind": "config", "repo": s["cat"], "name": s["title"], "link": _link(s),
                              "where": where, "weight": weight, "loads": reach, **x, "sentences": fs, "retired_since": retired.get(x["term"]) or first, "acknowledged": None,
                              "reason": f"a loading config file names {x['term']!r} as a place in use ({x['cue']}): it enforces the retired thing"})
        for c in commits(root, forbids):
            f = [x for x in flag(c["text"] or "", forbids) if not ((retired.get(x["term"]) or first) and c["ts"] < str(retired.get(x["term"]) or first))]
            if f:
                x = f[0]
                since_t = retired.get(x["term"]) or first
                flags.append({"ts": c["ts"], "kind": "commit", "repo": c["repo"], "name": f"{str(c['hash'])[:7]} {c['title'] or ''}".strip(),
                              "link": _link(c), "where": [c["repo"]], "weight": 5, "loads": "history (a commit message)", **x, "sentences": f, "retired_since": since_t, "acknowledged": None,
                              "reason": f"a commit names {x['term']!r} as a place in use ({x['cue']}), {c['ts'][:10]},"
                                        f" after the rule named it retired ({str(since_t)[:10]})"})
        # enforcement first: a global CLAUDE.md that loads everywhere, then skills, tree-level and repo files, notes, commits
        flags.sort(key=lambda g: (g["weight"], str(g["ts"])))

    digs: dict[str, Json] = {}
    if searched is None:
        from .trace import searched as searched_fn
        searched = searched_fn
    for q in ([key] + [r["link"] for r in rest] + [c["link"] for c in config]):
        try:
            res = searched(root, query=q, limit=1000) if not q.startswith("relic5://") else searched(root, link=q, limit=1000)
        except Exception:
            continue
        for c in res.get("chains") or []:
            if not c.get("root"):
                continue   # records from before trace ids
            d = digs.setdefault(c["root"], {"root": c["root"], "first": c["first"], "queries": c["queries"][:3], "found": bool(c["found"]), "why": []})
            for w in c["why"]:
                if w not in d["why"]:
                    d["why"].append(w)
    dug = sorted(digs.values(), key=lambda d: str(d["first"]))

    live = [g for g in flags if not g["acknowledged"]]
    swept = {"memory": len(notes), "config": swept_config if forbids else 0, "commit": commit_total(root) if forbids else 0}
    live_by = {k: sum(1 for g in live if g["kind"] == k) for k in swept}
    given_terms = [t for t in forbids if retired_by.get(t) == "given"]
    globals_now = [c for c in config if c["global"] and c["current"]]
    triple = {"reissued": 0, "candidates": len(rest), "dug": len(dug), "contradicted": len(live) if forbids else None,
              "flagged": len(flags) if forbids else None, "swept": swept if forbids else None, "live_by": live_by if forbids else None}
    line = (f"re-issued {triple['reissued']} bound · candidates {triple['candidates']} · dug for {triple['dug']} · "
            + (f"contradicted {len(live)} live ({len(flags)} flagged) of {sum(swept.values()):,} swept: {live_by['config']} of"
               f" {swept['config']:,} config sections, {live_by['commit']} of {swept['commit']:,} commits, {live_by['memory']} of"
               f" {swept['memory']:,} memory notes · retirement dates: {len(given_terms)} given ({', '.join(given_terms) or 'none'}),"
               f" {len(forbids) - len(given_terms)} derived" if forbids else "contradicted ? (pass forbids)"))
    return {"phrase": phrase, "key": key, "words": words, "forbids": forbids, "triple": triple, "line": line,
            "restatements": rest, "config": config,
            "reachability": {
                "carried_now": sorted({c["scope"] for c in config if c["current"]}),
                "global": [{"scope": c["scope"], "since": c["since"], "basis": c["basis"]} for c in globals_now],
                "unreached": [r["name"] for r in rest if r["reachable"] is False],
                "note": "a heading date is the rule's own claim; 'seen since' is the first push that held the file. relic5"
                        " held no config before its first push, so an earlier absence is not observed."},
            "retired": retired, "retired_by": retired_by, "contradictions": flags, "digs": dug}
