"""discord.py: Discord backups as the "discord" layer: fold, index, search alone, show, and never through the public door."""
import gzip, json, os

import duckdb
import pytest

from relic5 import discord, fts, mcp
from relic5.parts import Parts
from relic5.query import Relic5, UsageError
from relic5.status import status

G = "1501947834453459095"


def msg(i, text, ts="2026-06-01T01:21:34.226Z", thread=None, bot=False, files=()):
    return {"id": str(i), "guild": G, "guild_name": "Mini lab", "channel": "c1", "channel_name": "General",
            "thread": thread, "thread_name": "deploy talk" if thread else None, "author": "nazt", "bot": bot,
            "ts": ts, "text": text, "files": list(files)}


def put(root, machine, *ms):
    p = os.path.join(root, "parts", machine, "discord", f"{G}.jsonl.gz")
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with gzip.open(p, "wt", encoding="utf-8") as f:
        f.write("".join(json.dumps(m) + "\n" for m in ms) + "not json\n")


def test_rows(tmp_path):
    root = str(tmp_path)
    put(root, "m5", msg(1, "the kilua deploy is done", files=["shot.png"]), msg(2, "ok", ts="2026-06-01T02:00:00.000Z", thread="t9", bot=True))
    put(root, "white", msg(1, "the kilua deploy is done", files=["shot.png"]))      # the same message pushed twice
    rows = discord.rows(root)
    assert [r["message_id"] for r in rows] == ["1", "2"]
    one, two = rows
    assert one["machines"] == ["m5", "white"] and one["sid"] == f"discord:{G}:c1" and one["title"] == "#General"
    assert one["text"] == "nazt: the kilua deploy is done [files: shot.png]" and one["role"] == "discord" and one["cat"] == "Mini lab"
    assert one["ts_th"] == "2026-06-01T08:21:34.000+07:00" and one["month"] == "2026-06"
    assert two["role"] == "discord-bot" and two["sid"] == f"discord:{G}:t9" and two["title"] == "#General › deploy talk"


def test_indexed_searched_alone_and_kept_from_the_public_door(root, monkeypatch):
    monkeypatch.setenv("RELIC5_NOW", "2026-10-26T03:00:00Z")
    con = duckdb.connect()
    Parts(root).index(con, log=lambda s: None)
    fts.build(root, con, log=lambda s: None)
    put(root, "m5", msg(1, "the kilua deploy is done"))
    assert fts.build(root, con, log=lambda s: None) == ["discord_history"]
    assert fts.build(root, con, log=lambda s: None) == []
    r = Relic5(root, duckdb.connect())
    hits = r.search("kilua deploy", with_="discord")["hits"]
    assert len(hits) == 1 and hits[0]["layer"] == "discord" and hits[0]["role"] == "discord"
    assert not [h for h in r.search("kilua")["hits"] if h["layer"] == "discord"]               # never mixed with talk
    assert not [h for h in r.search("kilua", with_="all")["hits"] if h["layer"] == "discord"]  # not even with all
    shown = r.show(hits[0]["link"])
    assert shown["layer"] == "discord" and "Mini lab #General" in shown["notes"][0]
    assert status(root)["discord"]["messages"] == 1
    tok = discord.PUBLIC.set(True)
    try:
        with pytest.raises(UsageError, match="public MCP"):
            r.search("kilua", with_="discord")
        with pytest.raises(UsageError, match="public MCP"):
            r.show(hits[0]["link"])
        assert status(root)["discord"] is None
        tools = mcp.handle(r, {"jsonrpc": "2.0", "id": 1, "method": "tools/list"})["result"]["tools"]
        w = next(t for t in tools if t["name"] == "relic_search")["inputSchema"]["properties"]["with"]
        assert "discord" not in w["enum"] and "discord" not in w["description"]
    finally:
        discord.PUBLIC.reset(tok)
    tools = mcp.handle(r, {"jsonrpc": "2.0", "id": 1, "method": "tools/list"})["result"]["tools"]
    assert "discord" in next(t for t in tools if t["name"] == "relic_search")["inputSchema"]["properties"]["with"]["enum"]
