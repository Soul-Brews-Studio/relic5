import json, os

import duckdb

from relic5 import importer


def make_relic3(tmp_path):
    idx = tmp_path / "index"
    week = "2026W38-2026-09-14"
    d = idx / "2026" / week
    d.mkdir(parents=True)
    (idx / "_manifest").mkdir()
    con = duckdb.connect()
    rows = [("u1", "user", "hello hub", "2026-09-14T10:00:00.123Z", "keep-1"), ("u2", "assistant", "hi there", "2026-09-14T10:00:05Z", "keep-1"),
            ("u3", "user", "held session", "2026-09-14T11:00:00Z", "held-1"), ("u4", "note", "a note", "2026-09-14T11:00:00Z", "keep-1"),
            ("u5", "user", "late at night", "2026-09-30T17:30:00Z", "keep-1")]                 # Bangkok: 2026-10-01 00:30
    con.execute("CREATE TABLE e(uid VARCHAR, role VARCHAR, text VARCHAR, ts TIMESTAMPTZ, session_uuid VARCHAR, text_hash VARCHAR, bank VARCHAR, rel VARCHAR, lineno BIGINT, source VARCHAR, msg_id VARCHAR, part INTEGER)")
    con.executemany("INSERT INTO e VALUES (?, ?, ?, ?, ?, ?, 'projects', 'x/y.jsonl', 7, 'claude', NULL, 0)", [(u, r, t, ts, s, u + 'h') for u, r, t, ts, s in rows])
    f = f"{week}_events__r1.parquet"
    con.execute(f"COPY e TO '{d / f}' (FORMAT parquet)")
    con.execute("CREATE TABLE t AS SELECT 'u9' AS uid, 'tool_use' AS role, '[tool_use Bash] {\"command\": \"ls\"}' AS text, TIMESTAMPTZ '2026-09-14 10:00:06+00' AS ts, "
                "'keep-1' AS session_uuid, 'h9' AS text_hash, 'projects' AS bank, 'x/y.jsonl' AS rel, 8::BIGINT AS lineno, 'claude' AS source, NULL::VARCHAR AS msg_id, 0 AS part")
    tf = f"{week}_tools__r1.parquet"
    con.execute(f"COPY t TO '{d / tf}' (FORMAT parquet)")
    (idx / "_manifest" / "current").write_text("r1\n")
    (idx / "_manifest" / "r1.json").write_text(json.dumps({"weeks": {week: {"files": {f: {}, tf: {}}}}, "totals": {"events": 5, "tools": 1}}))
    return str(idx)


def test_convert_by_session_into_bangkok_months(tmp_path):
    idx, out = make_relic3(tmp_path), str(tmp_path / "out")
    rows = importer.convert(duckdb.connect(), idx, out, known={"held-1"}, log=lambda s: None)
    assert rows == {"2026-09": 3, "2026-10": 1}                    # held-1 skipped, the note is not prose for relic-extract
    con = duckdb.connect()
    r = con.execute(f"SELECT s, role, ts, ts_th, sources, machines, name, kind FROM '{out}/2026-09.parquet' ORDER BY ts, s").fetchall()
    assert r[0][:4] == ("text", "user", "2026-09-14T10:00:00.123Z", "2026-09-14T17:00:00.123+07:00")
    assert r[0][4] == ["relic3:projects/x/y.jsonl:7", "relic3-uid:u1"] and r[0][5] == ["relic3-import"]
    assert r[2][0] == "tools" and r[2][6] == "Bash" and r[2][7] == "call"
    cols = [c[0] for c in con.execute(f"DESCRIBE SELECT * FROM '{out}/2026-10.parquet'").fetchall()]
    assert cols == [c.split()[0] for c in importer.SCHEMA.split(", ")]
    assert os.path.exists(f"{out}/meta/sessions.parquet")
