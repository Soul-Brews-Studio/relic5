"""names.py: a session's display name, relic3's rule (agent-relic-v3 src/read/name.ts nameOf @9f0bdb5, itself a port of
v2.1 src/query.ts:1557-1586), applied at `relic5 index` time to each session's first user message.

relic-extract has already cleaned the text (slash commands are "/cmd args", envelope tags dropped), so of nameOf's steps
these remain: the host's title wins (rule 1, from relic-scan's meta `title` when present), a host boot directive is "(untitled)" (rule 3), a caveat block and <image> tags go, then any tag of up to
40 chars, whitespace collapses (rule 5), 70 chars (rule 6).

  index/_search/names.parquet    sid, name, first_ts
"""
import os, re
from typing import TYPE_CHECKING
from . import store as rfs

if TYPE_CHECKING:
    import duckdb
    from .parts import Parts

PREAMBLE = re.compile(r"^\s*(# AGENTS\.md instructions|<environment_context>|<recommended_plugins>|<codex_internal_context>|"
                      r"You have oh-my-codex installed|<INSTRUCTIONS>)")


def name_of(text: str | None) -> str:
    d = str(text or "")
    if PREAMBLE.match(d):
        return "(untitled)"
    d = re.sub(r"<local-command-caveat>[\s\S]*$", "", d)
    d = re.sub(r"^\s*Caveat: The messages below were generated[\s\S]*$", "", d)
    d = re.sub(r"<image\b[^>]*>", " ", d, flags=re.I)
    d = re.sub(r"<[^>]{1,40}>", " ", d)
    d = re.sub(r"\s+", " ", d).strip()
    return d[:70] if d else "(untitled)"


def path(root: str) -> str:
    return os.path.join(root, "index", "_search", "names.parquet")


def homes_path(root: str) -> str:
    return os.path.join(root, "index", "_search", "homes.parquet")


def _write(con: "duckdb.DuckDBPyConnection", table: str, p: str) -> None:
    if rfs.is_s3(p):   # one PUT on S3 is whole already; DuckDB writes s3:// through httpfs
        rfs.duck(con, p)
        con.execute(f"COPY {table} TO '{p}' (FORMAT parquet)")
    else:
        os.makedirs(os.path.dirname(p), exist_ok=True)
        con.execute(f"COPY {table} TO '{p}.tmp' (FORMAT parquet)")
        os.replace(p + ".tmp", p)


def build_homes(root: str, con: "duckdb.DuckDBPyConnection", parts: "Parts") -> int:
    """index/_search/homes.parquet: per session, the machine, the .claude (or .codex) it was written in, relic-scan's
    user@host, its messages and first/last time (Nat, 2026-10-25: separate .claude of nat, of beta, of a project).
    Parts from before relic-scan wrote src_path give home NULL: unknown, never guessed."""
    from .fts import HOME_SQL, _columns
    from .parts import sql_list
    fs = [p for _, _, p in parts.files("text")]
    if not fs:
        return 0
    have = _columns(con, fs)
    home = HOME_SQL if "src_path" in have else "NULL::VARCHAR"
    agent = "src_agent" if "src_agent" in have else "NULL::VARCHAR"
    con.execute(f"""CREATE OR REPLACE TEMP TABLE _homes AS
                    SELECT sid, min(machine) AS machine, mode({home}) AS home, mode({agent}) AS agent, count(*) AS messages,
                           min(ts) AS first_ts, max(ts) AS last_ts
                    FROM (SELECT regexp_extract(filename, '/parts/([^/]+)/', 1) AS machine, *
                          FROM read_parquet({sql_list(fs)}, union_by_name = true, filename = true))
                    WHERE sid IS NOT NULL GROUP BY sid""")
    _write(con, "_homes", homes_path(root))
    n = con.execute("SELECT count(*) FROM _homes").fetchone()
    return int(n[0]) if n else 0


def titles(con: "duckdb.DuckDBPyConnection", parts: "Parts") -> dict[str, str]:
    """Rule 1: the host's own title (relic-scan PR #37: the newest Claude custom-title), when the meta carries it."""
    from .parts import sql_list
    fs = parts.meta()
    have = [f for f in fs if "title" in {r[0] for r in con.execute(f"DESCRIBE SELECT * FROM read_parquet('{f}')").fetchall()}]
    if not have:
        return {}
    return {s: t.strip() for s, t in con.execute(f"""SELECT sid, any_value(title) FROM read_parquet({sql_list(have)}, union_by_name = true)
                                                     WHERE title IS NOT NULL AND trim(title) <> '' GROUP BY sid""").fetchall()}


def build(root: str, con: "duckdb.DuckDBPyConnection", parts: "Parts") -> int:
    fs = [p for _, _, p in parts.files("text")]
    if not fs:
        return 0
    from .parts import sql_list
    rows = con.execute(f"""SELECT sid, arg_min(text, ts) AS first, min(ts) AS first_ts
                           FROM read_parquet({sql_list(fs)}, union_by_name = true)
                           WHERE role = 'user' AND chunk = 0 AND sid IS NOT NULL GROUP BY sid""").fetchall()
    tt = titles(con, parts)
    con.execute("CREATE OR REPLACE TEMP TABLE _names(sid VARCHAR, name VARCHAR, first_ts VARCHAR)")
    con.executemany("INSERT INTO _names VALUES (?, ?, ?)", [(s, tt.get(s) or name_of(t), f) for s, t, f in rows])
    _write(con, "_names", path(root))
    build_homes(root, con, parts)
    return len(rows)
