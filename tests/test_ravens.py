"""ravens.py: a day hour by hour, Huginn's and Munin's notes beside the model readings."""
import json, os

import duckdb
import pytest

from conftest import write_parquet
from relic5 import ravens
from relic5.query import Relic5

NOTE = ["key", "msgkey", "chunk", "ts", "cat", "vault", "path", "section", "title", "text"]


def note(path, text, cat="odin-oracle", vault="own", chunk=0, mk=None):
    return {"key": f"{path}{chunk}{vault}", "msgkey": mk or f"{vault}:{path}", "chunk": chunk, "ts": "2026-10-25T08:00:00.000Z",
            "cat": cat, "vault": vault, "path": path, "section": path.rsplit("/", 2)[0], "title": path.rsplit("/", 1)[-1], "text": text}


@pytest.fixture
def hub(root):
    long = "a" * 5600 + "B" * 400 + "c" * 50          # 6050 characters: chunk 0 = first 6000, chunk 1 = from 5600
    write_parquet(os.path.join(root, "parts/m5/vault/notes.parquet"), NOTE, [
        note("memory/huginn/2026-10-25/1500_works.md", "# Huginn 15:00\\nrelic5 last used"),
        note("memory/huginn/2026-10-25/1500_works.md", "mirror copy", vault="plain"),           # the own vault wins
        note("memory/huginn/2026-10-25/1400_works.md", long[:6000]),
        note("memory/huginn/2026-10-25/1400_works.md", long[5600:], chunk=1),
        note("memory/huginn/2026-10-25/DAILY_works.md", "the day"),
        note("memory/munin/2026-10-25/0913_memory.md", "where is relic"),
        note("memory/huginn/2026-10-24/2300_works.md", "yesterday"),
    ])
    os.makedirs(os.path.join(root, "readings"))
    with open(os.path.join(root, "readings/m5.jsonl"), "w") as f:
        for unit, model in (("2026-10-25 15:00-16:00 1h", "zai:glm-5.3"), ("2026-10-25 15:15-15:30 15m", "gb300:qwen3:14b deep"),
                            ("2026-10-25 day", "zai:glm-5.3"), ("2026-10-26 01:00-02:00 1h", "zai:glm-5.3")):
            f.write(json.dumps({"at": "2026-10-26T00:00:00+0700", "unit": unit, "model": model,
                                "answer": {"type": "build", "focus": f"focus {unit}", "work": ["w"], "en": "e", "th": "ท"}}) + "\n")
    return Relic5(root, duckdb.connect())


def test_a_day_hour_by_hour(hub):
    d = ravens.hours(hub, "2026-10-25")
    assert d["daily"]["text"] == "the day" and [m["path"] for m in d["munin"]] == ["memory/munin/2026-10-25/0913_memory.md"]
    assert [h["hour"] for h in d["hours"]] == ["15", "14"]
    h15 = d["hours"][0]
    assert h15["huginn"]["text"].startswith("# Huginn 15:00") and [r["grain"] for r in h15["readings"]] == ["1h", "15m"]
    assert d["hours"][1]["huginn"]["text"] == "a" * 5600 + "B" * 400 + "c" * 50         # chunks joined without the overlap
    assert [r["grain"] for r in d["day"]] == ["day"] and d["readings_files"] == ["m5.jsonl"]
    with pytest.raises(ValueError):
        ravens.hours(hub, "yesterday")


def test_the_day_picker(hub):
    days = {d["date"]: d for d in ravens.days(hub)["days"]}
    assert days["2026-10-25"] == {"date": "2026-10-25", "huginn": 2, "readings": 3}
    assert days["2026-10-24"]["huginn"] == 1 and days["2026-10-26"]["readings"] == 1


def test_brief_for_an_agent(hub):
    b = ravens.brief(hub, "2026-10-25")
    assert b["daily"] == "the day" and [h["hour"] for h in b["hours"]] == ["15", "14"]
    assert b["hours"][0]["huginn"].startswith("# Huginn 15:00") and [r["grain"] for r in b["hours"][0]["readings"]] == ["1h"]
    one = ravens.brief(hub, "2026-10-25", "15")
    assert one["hour"] == "15" and len(one["readings"]) == 2 and one["huginn"].startswith("# Huginn")
    with pytest.raises(ValueError):
        ravens.brief(hub, "2026-10-25", "09")
    assert ravens.lead("---\nx: 1\n---\n# T\n> one\n> two\nbody") == "one two"
