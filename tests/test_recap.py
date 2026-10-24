import duckdb

from conftest import COLS, row, write_parquet
from relic5 import names
from relic5.parts import Parts
from relic5.query import Relic5
from relic5.recap import handoff, recap

META = ["sid", "tier", "parent_sid", "proj", "cat", "engine", "first_ts", "last_ts", "n_rows", "base", "months", "text_rows", "text_msgs",
        "user_text", "assistant_text", "thinking", "tool_calls", "tool_results", "tool_errors"]
META_TYPES = {"n_rows": "BIGINT", "months": "VARCHAR[]", **{k: "BIGINT" for k in META[11:]}}


def test_recap_and_handoff(root):
    write_parquet(f"{root}/parts/m5/text/2026-07.parquet", COLS, [
        row("build the thing", "2026-07-01T10:00:00.000Z", sid="r1-x"),
        row("I propose plan A: a long explanation " * 5, "2026-07-01T10:05:00.000Z", sid="r1-x", role="assistant"),
        row("go", "2026-07-01T10:10:00.000Z", sid="r1-x"),
        row("done, all tests pass", "2026-07-01T12:10:00.000Z", sid="r1-x", role="assistant")])
    write_parquet(f"{root}/parts/m5/tools/2026-07.parquet", COLS, [
        dict(row('{"file_path": "/x/a.py", "old_string": "1"}', "2026-07-01T10:11:00.000Z", sid="r1-x", role=""), name="Edit"),
        dict(row('{"command": "pytest"}', "2026-07-01T10:12:00.000Z", sid="r1-x", role=""), name="Bash")])
    write_parquet(f"{root}/parts/m5/meta/sessions.parquet", META,
                  [{"sid": "r1-x", "tier": "main", "first_ts": "2026-07-01T10:00:00.000Z", "last_ts": "2026-07-01T12:10:00.000Z", "n_rows": 6, "base": "r1-x.jsonl"}],
                  types=META_TYPES)
    r = Relic5(root, duckdb.connect())
    names.build(root, duckdb.connect(), Parts(root))
    c = recap(r, "r1")
    assert [t["text"] for t in c["asked"]] == ["build the thing", "go"] and c["tools"] == {"Edit": 1, "Bash": 1}
    assert c["files_edited"] == {"/x/a.py": 1} and c["ended"]["text"] == "done, all tests pass" and c["name"] == "build the thing"
    assert recap(r, "r1", limit=1)["more"].startswith("relic5 recap r1-x")
    h = handoff(r, "r1")
    assert h["turns"] == 2 and h["span_s"] == 600 and h["longest_gap_s"] == 600
    body = h["text"].splitlines()
    assert body[2].startswith("[2026-07-01 10:00] me: build the thing") and "agent: I propose plan A" in h["text"] and body[-1].endswith("me: go")
    assert "agent:" not in handoff(r, "r1", user_only=True)["text"]


def test_a_prompt_stored_twice_is_one_turn(root):
    """Claude Code writes a prompt when it is typed (or queued mid-turn, wrapped) and again when it is submitted."""
    wrap = ("The user sent a new message while you were working:\nshow root tree\n\nThis is how Claude Code surfaces messages "
            "the user sends mid-turn — within the running turn. Address the message above as you continue this turn.")
    write_parquet(f"{root}/parts/m5/text/2026-07.parquet", COLS, [
        row("build the thing", "2026-07-01T10:00:00.000Z", sid="r2-x"),
        row("build the thing", "2026-07-01T10:00:00.000Z", sid="r2-x", msgkey="dup-1"),
        row("on it", "2026-07-01T10:00:30.000Z", sid="r2-x", role="assistant"),
        row(wrap, "2026-07-01T10:01:00.000Z", sid="r2-x"),
        row("show root tree", "2026-07-01T10:12:00.000Z", sid="r2-x"),                       # 11 min later: the submit
        row("[Image #1] look\n[Image: source: /tmp/x/1.png]", "2026-07-01T10:13:00.000Z", sid="r2-x"),
        row("[Image #1] look", "2026-07-01T10:13:20.000Z", sid="r2-x"),
        row("go", "2026-07-01T10:20:00.000Z", sid="r2-x"),
        row("go", "2026-07-01T11:20:00.000Z", sid="r2-x")])                                  # an hour later: said again
    write_parquet(f"{root}/parts/m5/meta/sessions.parquet", META, [{"sid": "r2-x", "tier": "main", "first_ts": "2026-07-01T10:00:00.000Z",
                  "last_ts": "2026-07-01T11:20:00.000Z", "n_rows": 9, "base": "r2-x.jsonl"}], types=META_TYPES)
    r = Relic5(root, duckdb.connect())
    asked = [t["text"] for t in recap(r, "r2", limit=0)["asked"]]
    assert len(asked) == 5 and asked[0] == "build the thing" and asked[1] == wrap and asked[3:] == ["go", "go"]
    assert handoff(r, "r2")["turns"] == 5
