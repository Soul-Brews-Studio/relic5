"""importer.py: `relic5 import relic3` — old data into relic-scan's month schema, so relic-extract cuts it like everything
else and it is pushed as its own machine ("relic3-import"). The contract is relic4-scan's (2026-10-23):

  columns, in order: s, h (int64), idx (int64), engine, role, type, sid, ts, ts_th, text, kind, call_id, name, body,
    err (bool), red, machines (list<str>), sources (list<str>), model, msg_id, out_tokens (int64)
  month = the Bangkok month of ts; ts = UTC "YYYY-MM-DDTHH:MM:SS.mmmZ"; ts_th = the same instant "...+07:00"
  s = 'text' (user, assistant), 'tools' (calls and results: kind call/result, name, body)
  h = a stable 64-bit hash of the row's content (no source line to hash); machines = ["relic3-import"]
  sources = ["relic3:<bank>/<rel>:<lineno>", "relic3-uid:<uid>"]  (the uid lets an old relic3:// link be resolved)

Import by SESSION, not by fold: only relic3 sessions that no machine on the hub holds (GET /api/known-sids) are
written, so nothing can be duplicated whatever relic3's text normalisation was. `--all` writes every session (for the
fold measurement on an overlapping week).

relic3's live files are the ones its current manifest names (index/_manifest/current -> <run>.json "weeks"); older
generations in the same folders are ignored. Thinking was never collected by relic3 (D2), so there is none to import.
"""
import json, os, time

SCHEMA = ("s VARCHAR, h BIGINT, idx BIGINT, engine VARCHAR, role VARCHAR, type VARCHAR, sid VARCHAR, ts VARCHAR, ts_th VARCHAR, "
          "text VARCHAR, kind VARCHAR, call_id VARCHAR, name VARCHAR, body VARCHAR, err BOOLEAN, red VARCHAR, machines VARCHAR[], "
          "sources VARCHAR[], model VARCHAR, msg_id VARCHAR, out_tokens BIGINT")


def live_files(index_dir):
    """{"events": [...], "tools": [...]}: the parquet files of relic3's current generation."""
    run = open(os.path.join(index_dir, "_manifest", "current")).read().strip()
    m = json.load(open(os.path.join(index_dir, "_manifest", f"{run}.json")))
    out = {"events": [], "tools": []}
    for week, w in m["weeks"].items():
        year = week[:4]
        for f in w["files"]:
            for t in out:
                if f"_{t}__" in f:
                    p = os.path.join(index_dir, year, week, f)
                    if not os.path.exists(p):
                        p = os.path.join(index_dir, "_quarantine", f)
                    if os.path.exists(p):
                        out[t].append(p)
    return run, m["totals"], out


def _lst(fs):
    return "[" + ", ".join("'" + f.replace("'", "''") + "'" for f in fs) + "]"


TS = "strftime(ts AT TIME ZONE 'UTC', '%Y-%m-%dT%H:%M:%S.%gZ')"
TS_TH = "strftime((ts AT TIME ZONE 'UTC') + INTERVAL 7 HOUR, '%Y-%m-%dT%H:%M:%S.%g') || '+07:00'"
MONTH = "strftime((ts AT TIME ZONE 'UTC') + INTERVAL 7 HOUR, '%Y-%m')"


def select_sql(files, known_table=None):
    keep = f"AND session_uuid NOT IN (SELECT sid FROM {known_table})" if known_table else ""
    ev = f"""SELECT 'text' AS s, (hash(text_hash, uid) & 9223372036854775807)::BIGINT AS h, 0::BIGINT AS idx, coalesce(source, 'claude') AS engine,
               role, role AS type, session_uuid AS sid, {TS} AS ts, {TS_TH} AS ts_th, text,
               NULL::VARCHAR AS kind, NULL::VARCHAR AS call_id, NULL::VARCHAR AS name, NULL::VARCHAR AS body, NULL::BOOLEAN AS err,
               NULL::VARCHAR AS red, ['relic3-import'] AS machines,
               ['relic3:' || coalesce(bank, '') || '/' || coalesce(rel, '') || ':' || coalesce(lineno, 0), 'relic3-uid:' || uid] AS sources,
               NULL::VARCHAR AS model, msg_id, NULL::BIGINT AS out_tokens, {MONTH} AS month
             FROM read_parquet({_lst(files['events'])}, union_by_name = true)
             WHERE role IN ('user', 'assistant') AND ts IS NOT NULL AND text IS NOT NULL {keep}"""
    if not files["tools"]:
        return ev
    tl = f"""SELECT 'tools' AS s, (hash(text_hash, uid) & 9223372036854775807)::BIGINT AS h, coalesce(part, 0)::BIGINT AS idx, coalesce(source, 'claude') AS engine,
               '' AS role, role AS type, session_uuid AS sid, {TS} AS ts, {TS_TH} AS ts_th, NULL::VARCHAR AS text,
               CASE WHEN role = 'tool_result' THEN 'result' ELSE 'call' END AS kind, NULL::VARCHAR AS call_id,
               nullif(regexp_extract(text, '^\\[tool_use ([\\w.:-]+)\\]', 1), '') AS name, text AS body, false AS err,
               NULL::VARCHAR AS red, ['relic3-import'] AS machines,
               ['relic3:' || coalesce(bank, '') || '/' || coalesce(rel, '') || ':' || coalesce(lineno, 0), 'relic3-uid:' || uid] AS sources,
               NULL::VARCHAR AS model, msg_id, NULL::BIGINT AS out_tokens, {MONTH} AS month
             FROM read_parquet({_lst(files['tools'])}, union_by_name = true)
             WHERE role IN ('tool_use', 'tool_result') AND ts IS NOT NULL {keep}"""
    return ev + " UNION ALL " + tl


def convert(con, index_dir, out_dir, known=None, log=print, weeks=None):
    """Write <out_dir>/YYYY-MM.parquet (+ meta/sessions.parquet for relic-extract's cat/probe). -> rows per month."""
    run, totals, files = live_files(index_dir)
    if weeks:
        files = {k: [f for f in v if any(w in f for w in weeks)] for k, v in files.items()}
    log(f"relic3 run {run}: {len(files['events'])} events + {len(files['tools'])} tools files (of {totals['events']:,} events, {totals['tools']:,} tools)")
    known_table = None
    if known is not None:
        con.execute("CREATE OR REPLACE TEMP TABLE known(sid VARCHAR)")
        con.executemany("INSERT INTO known VALUES (?)", [(s,) for s in known])
        known_table = "known"
    os.makedirs(out_dir, exist_ok=True)
    t = time.time()
    con.execute(f"CREATE OR REPLACE TEMP TABLE imp AS {select_sql(files, known_table)}")
    rows = dict(con.execute("SELECT month, count(*) FROM imp GROUP BY 1 ORDER BY 1").fetchall())
    cols = [c.split()[0] for c in SCHEMA.split(", ")]
    for mon in rows:
        p = os.path.join(out_dir, f"{mon}.parquet")
        con.execute(f"COPY (SELECT {', '.join(cols)} FROM imp WHERE month = '{mon}' ORDER BY ts, sid, s, idx) TO '{p}.tmp' (FORMAT parquet, COMPRESSION zstd)")
        os.replace(p + ".tmp", p)
    os.makedirs(os.path.join(out_dir, "meta"), exist_ok=True)
    mp = os.path.join(out_dir, "meta", "sessions.parquet")
    con.execute(f"""COPY (SELECT sid, 'main' AS tier, NULL::VARCHAR AS parent_sid, any_value(engine) AS engine, NULL::VARCHAR AS proj,
                    'relic3-import' AS cat, false AS probe, min(ts) AS first_ts, max(ts) AS last_ts, count(*)::BIGINT AS n_rows,
                    list(DISTINCT month) AS months FROM imp GROUP BY sid) TO '{mp}.tmp' (FORMAT parquet, COMPRESSION zstd)""")
    os.replace(mp + ".tmp", mp)
    n_s = con.execute("SELECT count(DISTINCT sid) FROM imp").fetchone()[0]
    log(f"import: {sum(rows.values()):,} rows, {n_s:,} sessions, {len(rows)} months -> {out_dir} ({time.time() - t:.0f}s)")
    return rows


def msgkey_sql():
    """relic-extract's MSGKEY (agent-relic-v4 src/relic4/sql.py, byte-identical in relic-extract): no sid in it."""
    return ("CASE WHEN s = 'tools' THEN md5(to_json([s, ts, CAST(idx AS VARCHAR), kind, call_id, name, body, CAST(err AS VARCHAR)])) "
            "ELSE md5(to_json([s, role, ts, text])) END")
