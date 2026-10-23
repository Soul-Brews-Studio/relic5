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
    assert [s["uuid"] for s in relic.sessions(repo="github.com/Soul-Brews-Studio/relic5")["sessions"]] == ["s2-bbbb"]
    assert relic.sessions(since="2026-10-23")["total"] == 1


def test_session(relic):
    s = relic.session("s1")
    assert s["uuid"] == "s1-aaaa" and [k["uuid"] for k in s["subagents"]] == ["agent-1"]
    with pytest.raises(NotFound):
        relic.session("zz")
