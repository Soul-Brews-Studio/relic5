"""names.py: a session's display name, relic3's rule (agent-relic-v3 src/read/name.ts nameOf @9f0bdb5, itself a port of
v2.1 src/query.ts:1557-1586), applied at `relic5 index` time to each session's first user message.

relic-extract has already cleaned the text (slash commands are "/cmd args", envelope tags dropped), so of nameOf's steps
these remain: a host boot directive is "(untitled)" (rule 3), a caveat block and <image> tags go, then any tag of up to
40 chars, whitespace collapses (rule 5), 70 chars (rule 6). Rule 1 (the host's own title) has no field in the parts yet.

  index/_search/names.parquet    sid, name, first_ts
"""
import os, re

PREAMBLE = re.compile(r"^\s*(# AGENTS\.md instructions|<environment_context>|<recommended_plugins>|<codex_internal_context>|"
                      r"You have oh-my-codex installed|<INSTRUCTIONS>)")


def name_of(text):
    d = str(text or "")
    if PREAMBLE.match(d):
        return "(untitled)"
    d = re.sub(r"<local-command-caveat>[\s\S]*$", "", d)
    d = re.sub(r"^\s*Caveat: The messages below were generated[\s\S]*$", "", d)
    d = re.sub(r"<image\b[^>]*>", " ", d, flags=re.I)
    d = re.sub(r"<[^>]{1,40}>", " ", d)
    d = re.sub(r"\s+", " ", d).strip()
    return d[:70] if d else "(untitled)"


def path(root):
    return os.path.join(root, "index", "_search", "names.parquet")


def build(root, con, parts):
    fs = [p for _, _, p in parts.files("text")]
    if not fs:
        return 0
    from .parts import sql_list
    rows = con.execute(f"""SELECT sid, arg_min(text, ts) AS first, min(ts) AS first_ts
                           FROM read_parquet({sql_list(fs)}, union_by_name = true)
                           WHERE role = 'user' AND chunk = 0 AND sid IS NOT NULL GROUP BY sid""").fetchall()
    con.execute("CREATE OR REPLACE TEMP TABLE _names(sid VARCHAR, name VARCHAR, first_ts VARCHAR)")
    con.executemany("INSERT INTO _names VALUES (?, ?, ?)", [(s, name_of(t), f) for s, t, f in rows])
    p = path(root)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    con.execute(f"COPY _names TO '{p}.tmp' (FORMAT parquet)")
    os.replace(p + ".tmp", p)
    return len(rows)
