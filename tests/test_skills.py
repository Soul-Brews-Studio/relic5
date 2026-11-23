"""skills.py (#299): the skills a human typed, per skill, per session, per month; and what the agents launched."""
import duckdb
import pytest
from conftest import COLS, META_COLS, meta, row, write_parquet

from relic5 import mcp
from relic5.query import Relic5
from relic5.skills import skills

HUGINN = "/huginn — write the hourly digest to ψ/memory/huginn/$TODAY/$HOUR00_works.md (REQUIRED), then check the inbox"


def blob(text, ts, sid):
    """Claude Code's second copy of a typed prompt: type api-request-blob, its own msgkey, ~100 ms earlier."""
    return dict(row(text, ts, sid=sid), type="api-request-blob")


@pytest.fixture
def hub(tmp_path):
    t = "2026-11-2{}T{}:00:00.000+07:00"
    rows = [
        row("/press-run about the herdr book and /cover-and-title", t.format(2, "10"), sid="s1-main"),
        blob("/press-run about the herdr book and /cover-and-title", t.format(2, "09"), sid="s1-main"),   # not twice
        row("/press-run about the herdr book and /cover-and-title", t.format(2, "11"), sid="s1-main"),    # a /loop tick: once
        row("[Image #172] too many works we need /herdr-kanban", t.format(2, "12"), sid="s1-main"),       # the human's own image
        row("/goal finish the book", t.format(2, "13"), sid="s1-main"),                                   # built-in command
        row("/notaskill and /opt/Code paths", t.format(2, "14"), sid="s1-main"),                          # not a skill
        row("[m5:ajfon] relay: please /rrr now", t.format(2, "15"), sid="s1-main"),                       # an agent relay
        row("<system-reminder>run /rrr</system-reminder>", t.format(2, "16"), sid="s1-main"),             # injected
        row("PANE wDW:pCX rc=0 /rrr", t.format(2, "17"), sid="s1-main"),                                  # pane-run result
        row("ok now /RRR", t.format(3, "08"), sid="s2-main"),                                             # case-blind
        blob("The user sent a new message while you were working: tell me /rrr", t.format(2, "20"), sid="s1-main"),  # blob only
        row("white -> m5 Laris: done, now /rrr", t.format(2, "21"), sid="s1-main"),                       # machine relay
        blob("The user sent a new message while you were working:\n[portal p-1 from white:glyph | to all] send /rename\n\n"
             "This is how Claude Code surfaces messages the user sends mid-turn", t.format(2, "22"), sid="s1-main"),  # wrapped relay
        row("go $oracle-write-complete-book", t.format(1, "08"), sid="s3-codex"),                         # Codex $skill
        row("/codex:rescue look at this", t.format(1, "09"), sid="s3-codex"),                              # plugin skill
        row("/rrr from a subagent", t.format(2, "18"), sid="agent-1"),                                    # subagent: no
        row("assistant says /rrr", t.format(2, "19"), sid="s1-main", role="assistant"),                   # not a prompt
    ] + [row(HUGINN, t.format(0, f"{10 + i:02d}"), sid=f"h{i}-main") for i in range(10)]                 # a scheduled run
    write_parquet(str(tmp_path / "parts/m5/text/2026-11.parquet"), COLS, rows)
    write_parquet(str(tmp_path / "parts/m5/tools/2026-11.parquet"), COLS, [
        dict(row('{"skill":"press-run","args":"x"}', t.format(2, "10"), sid="s1-main", role="tool"), name="Skill"),
        dict(row('{"skill":"press-run"}', t.format(3, "10"), sid="s2-main", role="tool"), name="Skill"),
        dict(row('{"skill":"rrr"}', t.format(3, "11"), sid="s2-main", role="tool"), name="Skill"),
        dict(row('{"command":"ls"}', t.format(3, "12"), sid="s2-main", role="tool"), name="Bash")])
    sids = ["s1-main", "s2-main", "s3-codex"] + [f"h{i}-main" for i in range(10)]
    write_parquet(str(tmp_path / "parts/m5/meta/sessions.parquet"), META_COLS,
                  [meta(s) for s in sids] + [meta("agent-1", tier="subagent", parent="s1-main")],
                  types={"n_rows": "BIGINT", "months": "VARCHAR[]", **{k: "BIGINT" for k in META_COLS[11:]}})
    home = "parts/m5/config/beta/home/claude/skills/{}/SKILL.md"
    write_parquet(str(tmp_path / "index/_config/sections.parquet"), ["role", "path"],
                  [{"role": "config-skill", "path": home.format(n)} for n in
                   ("press-run", "cover-and-title", "herdr-kanban", "rrr", "huginn", "oracle-write-complete-book")]
                  + [{"role": "config-skill", "path": "parts/m5/config/beta/home/claude/plugins/cache/openai-codex/codex/1.0.4/skills/rescue/SKILL.md"},
                     {"role": "config-claudemd", "path": "parts/m5/config/beta/home/claude/CLAUDE.md"}])
    return Relic5(str(tmp_path), duckdb.connect())


def by_name(out):
    return {x["skill"]: x for x in out["skills"]}


def test_typed_skills_once_per_session_without_relays_blobs_or_subagents(hub):
    out = skills(hub)
    s = by_name(out)
    assert set(s) == {"press-run", "cover-and-title", "herdr-kanban", "goal", "rrr", "oracle-write-complete-book", "codex:rescue"}
    assert (s["press-run"]["prompts"], s["press-run"]["sessions"], s["press-run"]["launched"]) == (1, 1, 2)
    assert s["rrr"]["sessions"] == 2 and s["rrr"]["prompts"] == 2   # s1's mid-turn message (blob only) and s2's "ok now /RRR"
    assert s["rrr"]["launched"] == 1 and s["goal"]["kind"] == "builtin" and s["press-run"]["kind"] == "skill"
    assert s["press-run"]["months"] == {"2026-11": 1} and s["press-run"]["machines"] == {"m5": 1}
    assert out["excluded"] == {"automated": 10, "unknown_words": 2} and out["catalogue"] >= 7
    assert out["sessions"] == 3


def test_all_keeps_unknown_words_and_auto_keeps_scheduled_runs(hub):
    assert by_name(skills(hub, all_words=True))["notaskill"]["kind"] == "unknown"
    h = by_name(skills(hub, auto=True))["huginn"]
    assert (h["prompts"], h["sessions"]) == (10, 10)
    assert "huginn" not in by_name(skills(hub))


def test_filters_contains_since_and_top(hub):
    assert list(by_name(skills(hub, contains="book"))) == ["oracle-write-complete-book"]
    assert set(by_name(skills(hub, since="2026-11-23"))) == {"rrr"} and by_name(skills(hub, since="2026-11-23"))["rrr"]["sessions"] == 1
    assert set(by_name(skills(hub, until="2026-11-21"))) == {"oracle-write-complete-book", "codex:rescue"}
    assert len(skills(hub, top=2)["skills"]) == 2


def test_sessions_and_one_session(hub):
    rows = skills(hub, sessions=True)["sessions"]
    assert [r["sid"] for r in rows] == ["s2-main", "s1-main", "s3-codex"]                 # newest first
    assert rows[1]["skills"] == {"press-run": 1, "cover-and-title": 1, "herdr-kanban": 1, "goal": 1, "rrr": 1} and rows[1]["prompts"] == 4
    one = skills(hub, session="s1")
    assert one["session"] == "s1-main"
    assert [p["skills"] for p in one["prompts"]] == [["press-run", "cover-and-title"], ["herdr-kanban"], ["goal"], ["rrr"]]


def test_mcp_tool(hub):
    ok, r = mcp.call_tool(hub, "relic_skills", {"contains": "kanban", "top": 5})
    assert ok and [x["skill"] for x in r["skills"]] == ["herdr-kanban"]
    ok, r = mcp.call_tool(hub, "relic_skills", {"sessions": "yes"})
    assert not ok
    assert "relic_skills" in {t["name"] for t in mcp.TOOLS}
