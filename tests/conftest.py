import hashlib, os

import duckdb
import pytest

COLS = ["key", "msgkey", "chunk", "month", "sid", "ts", "ts_th", "engine", "role", "type", "kind", "name", "cat", "text"]


def write_parquet(path, cols, rows, types=None):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    con = duckdb.connect()
    types = types or {}
    con.execute("CREATE TABLE t(" + ", ".join(f"{c} {types.get(c, 'BIGINT' if c == 'chunk' else 'VARCHAR')}" for c in cols) + ")")
    con.executemany(f"INSERT INTO t VALUES ({', '.join('?' * len(cols))})", [[r.get(c) for c in cols] for r in rows])
    con.execute(f"COPY t TO '{path}' (FORMAT parquet)")


def row(text, ts, sid="s1-aaaa", role="user", chunk=0, msgkey=None):
    mk = msgkey or hashlib.md5(f"{sid}{role}{ts}{text}".encode()).hexdigest()
    return {"key": hashlib.md5(text.encode()).hexdigest(), "msgkey": mk, "chunk": chunk, "month": ts[:7], "sid": sid,
            "ts": ts, "ts_th": ts, "engine": "claude", "role": role, "type": role, "cat": "neo", "text": text}


SHARED = row("hub shared by two machines", "2026-10-23T09:00:00.000Z")
META_COLS = ["base", "tier", "sid", "parent_sid", "engine", "proj", "cat", "first_ts", "last_ts", "n_rows", "months",
             "text_rows", "text_msgs", "user_text", "assistant_text", "thinking", "tool_calls", "tool_results", "tool_errors"]


def meta(sid, tier="main", parent=None, first="2026-10-23T09:00:00.000Z", last="2026-10-23T12:00:00.000Z", proj="-opt-Code-github-com-laris-co-neo-oracle"):
    return {"base": sid + ".jsonl", "tier": tier, "sid": sid, "parent_sid": parent, "engine": "claude", "proj": proj, "cat": "neo",
            "first_ts": first, "last_ts": last, "n_rows": 10, "months": ["2026-10"], **{k: 1 for k in META_COLS[11:]}}


@pytest.fixture
def root(tmp_path):
    long_mk = "f" * 32
    write_parquet(str(tmp_path / "parts/m5/text/2026-10.parquet"), COLS, [
        SHARED,
        row("deploy the hub on white", "2026-10-23T10:00:00.000Z"),
        row("ทดสอบภาษาไทย ค้นหาได้ไหม", "2026-10-23T11:00:00.000Z", role="assistant"),
        row("first chunk of a long one", "2026-10-23T11:30:00.000Z", msgkey=long_mk),
        row("second chunk of a long one", "2026-10-23T11:30:00.000Z", msgkey=long_mk, chunk=1),
        row("100% done_now", "2026-10-22T09:00:00.000Z", sid="s2-bbbb"),
    ])
    write_parquet(str(tmp_path / "parts/m5/tools/2026-10.parquet"), COLS, [row("rg hub src/", "2026-10-23T10:00:01.000Z", role="tool")])
    write_parquet(str(tmp_path / "parts/mba/text/2026-09.parquet"), COLS, [row("hub from the mba", "2026-09-01T00:00:00.000Z", sid="s3-cccc")])
    write_parquet(str(tmp_path / "parts/mba/text/2026-10.parquet"), COLS, [SHARED])
    write_parquet(str(tmp_path / "parts/m5/meta/sessions.parquet"), META_COLS, [
        meta("s1-aaaa"), meta("s2-bbbb", last="2026-10-22T10:00:00.000Z", proj="-opt-Code-github-com-Soul-Brews-Studio-relic5"),
        meta("agent-1", tier="subagent", parent="s1-aaaa")], types={"n_rows": "BIGINT", "months": "VARCHAR[]",
                                                                    **{k: "BIGINT" for k in META_COLS[11:]}})
    return str(tmp_path)


@pytest.fixture
def relic(root):
    from relic5.query import Relic5
    return Relic5(root, duckdb.connect())
