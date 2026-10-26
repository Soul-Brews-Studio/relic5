import pytest

from conftest import SHARED
from relic5.query import NotFound, UsageError


def uids(r):
    return [h["uid"] for h in r["hits"]]


def test_fold_across_machines(relic):
    hits = relic.search("shared")["hits"]
    assert len(hits) == 1 and hits[0]["uid"] == SHARED["msgkey"] and hits[0]["machines"] == ["m5", "mba"]
    assert hits[0]["link"] == f"relic5://2026-10/{SHARED['msgkey']}" and hits[0]["partition"] == "2026-10"


def test_every_word_must_occur(relic):
    assert len(relic.search("hub")["hits"]) == 3
    assert [h["text_snippet"] for h in relic.search("hub white")["hits"]] == ["…deploy the hub on white…"]


def test_thai_substring(relic):
    hits = relic.search("ภาษาไทย")["hits"]
    assert len(hits) == 1 and "ภาษาไทย" in hits[0]["text_snippet"]


def test_like_wildcards_are_literal(relic):
    assert len(relic.search("100%")["hits"]) == 1
    assert relic.search("do_e")["hits"] == []
    assert len(relic.search("done_now")["hits"]) == 1


def test_chunk_uid(relic):
    assert uids(relic.search("second chunk")) == ["f" * 32 + ":1"]


def test_filters_and_window(relic):
    assert len(relic.search("hub", since="2026-10-01")["hits"]) == 2
    assert len(relic.search("hub", until="2026-09-30")["hits"]) == 1
    assert relic.search("ไทย", role="user")["hits"] == []
    assert len(relic.search("hub", session="s3")["hits"]) == 1
    assert uids(relic.search("done", repo="github.com/Soul-Brews-Studio/relic5")) != []
    assert relic.search("hub", repo="github.com/Soul-Brews-Studio/relic5")["hits"] == []
    with pytest.raises(UsageError):
        relic.search("hub", horizon="7d", since="2026-01-01")
    with pytest.raises(UsageError):
        relic.search("hub", since="zzz")


def test_with_tools(relic):
    assert {h["layer"] for h in relic.search("hub", with_="tools")["hits"]} == {"text", "tools"}
    with pytest.raises(UsageError):
        relic.search("hub", with_="raw")


def test_cursor_pages(relic):
    a = relic.search("hub", limit=2)
    assert len(a["hits"]) == 2 and a["next_cursor"]
    b = relic.search("hub", limit=2, cursor=a["next_cursor"])
    assert len(b["hits"]) == 1 and b["next_cursor"] is None
    assert not set(uids(a)) & set(uids(b))
    with pytest.raises(UsageError):
        relic.search("white", cursor=a["next_cursor"])


def test_show_and_neighbours(relic):
    hit = relic.search("deploy")["hits"][0]
    for ident in (hit["uid"], hit["link"]):
        r = relic.show(ident, before=1, after=5)
        assert r["target"]["text"] == "deploy the hub on white"
        assert [x["text"][:6] for x in r["before"]] == ["hub sh"]
        assert [x["text"][:6] for x in r["after"]] == ["ทดสอบภ", "first "]   # one row per message, not per chunk


def test_show_long_message_has_its_chunks(relic):
    r = relic.show("f" * 32 + ":1")
    assert [p["chunk"] for p in r["parts"]] == [0, 1] and r["target"]["chunk"] == 1


def test_show_by_session_and_seq(relic):
    assert relic.show("s1-aaaa", seq=1)["target"]["text"] == "deploy the hub on white"
    with pytest.raises(NotFound):
        relic.show("s1-aaaa", seq=99)


def test_show_relic3_ids_say_so(relic):
    for ident in ("relic3://defaults/claude/x", "de0dd91ee0e89b617c31f36fa6809a84be7ebdf2"):
        with pytest.raises(UsageError, match="relic3 id"):
            relic.show(ident)
    with pytest.raises(NotFound):
        relic.show("0" * 32)


def test_sessions(relic):
    r = relic.sessions()
    assert r["total"] == 2 and [s["uuid"] for s in r["sessions"]] == ["s1-aaaa", "s2-bbbb"]
    assert r["sessions"][0]["children"] == 1   # the subagent is folded into its parent
    a = r["all"]   # every session once, the subagent too: what "transcript events" on the glance page counts
    assert a["sessions"] == 3 and a["subagents"] == 1 and a["events"] == r["events"] + a["subagent_events"]
    assert [s["uuid"] for s in relic.sessions(repo="github.com/Soul-Brews-Studio/relic5")["sessions"]] == ["s2-bbbb"]
    assert relic.sessions(since="2026-10-23")["total"] == 1


def test_sessions_by_repo(relic):
    """Counts per repo for the same window and filters: what a month recap's "By project" needs (2026-10-24)."""
    r = relic.sessions(by_repo=True, limit=0)
    assert {x["repo"]: x["sessions"] for x in r["repos"]} == {"-opt-Code-github-com-laris-co-neo-oracle": 1,
                                                              "-opt-Code-github-com-Soul-Brews-Studio-relic5": 1}
    assert sum(x["sessions"] for x in r["repos"]) == r["total"]
    assert [x["repo"] for x in relic.sessions(by_repo=True, since="2026-10-23")["repos"]] == ["-opt-Code-github-com-laris-co-neo-oracle"]
    assert "repos" not in relic.sessions()
    assert len(relic.sessions(by_repo=True)["repos"]) <= 201                # top 200 plus one "(other N repos)" row


def test_sessions_pick_the_same_copy_every_time(root):
    """A sid held twice on one machine (two homes): always the most complete copy, so counts never move."""
    import os
    import duckdb
    from conftest import META_COLS, meta, write_parquet
    from relic5.query import Relic5
    p = os.path.join(root, "parts/m5/meta/sessions.parquet")
    rows = [meta("s1-aaaa"), meta("s2-bbbb", last="2026-10-22T10:00:00.000Z", proj="-opt-Code-github-com-Soul-Brews-Studio-relic5"),
            meta("agent-1", tier="subagent", parent="s1-aaaa"),
            meta("s9-dup", first="2026-09-29T00:00:00.000Z", last="2026-09-30T00:00:00.000Z"),   # an old copy, September only
            meta("s9-dup", first="2026-09-29T00:00:00.000Z", last="2026-10-23T00:00:00.000Z")]   # the full one, into October
    write_parquet(p, META_COLS, rows, types={"n_rows": "BIGINT", "months": "VARCHAR[]", **{k: "BIGINT" for k in META_COLS[11:]}})
    for _ in range(5):
        assert Relic5(root, duckdb.connect()).sessions(since="2026-10-01")["total"] == 3     # s1, s2 and s9's full copy


def test_session(relic):
    s = relic.session("s1")
    assert s["uuid"] == "s1-aaaa" and [k["uuid"] for k in s["subagents"]] == ["agent-1"]
    with pytest.raises(NotFound):
        relic.session("zz")


def test_tail_newest_first(relic):
    r = relic.tail(n=3)
    ts = [x["ts"] for x in r["rows"]]
    assert ts == sorted(ts, reverse=True) and r["newest"] == ts[0]
    assert all(x["sid"].startswith("s1") for x in relic.tail(session="s1")["rows"])
    assert [x["machines"] for x in relic.tail(n=50) if False] == []
    shared = [x for x in relic.tail(n=50)["rows"] if x["msgkey"] == SHARED["msgkey"]]
    assert len(shared) == 1 and shared[0]["machines"] == ["m5", "mba"]
    whole = {x["msgkey"]: x["text"] for x in relic.tail(n=50, full=True)["rows"]}
    first = {x["msgkey"]: x["text"] for x in relic.tail(n=50)["rows"]}
    assert whole.keys() == first.keys() and all(whole[k].startswith(first[k][:50]) for k in whole)
