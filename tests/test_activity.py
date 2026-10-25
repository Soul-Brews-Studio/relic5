"""activity.py: counts by time bucket and dimension, for charts."""
import pytest

from relic5.activity import activity


def test_counts_by_day_and_role(relic):
    a = activity(relic, by="day", group="role")
    names = {s["name"]: s for s in a["series"]}
    assert set(names) == {"user", "assistant"} and a["total"] == sum(s["total"] for s in a["series"])
    assert "2026-10-23" in a["buckets"] and names["assistant"]["counts"]["2026-10-23"] == 1
    shared = activity(relic, by="month")                     # the message two machines hold counts once
    assert shared["series"][0]["name"] == "all" and shared["total"] == 6
    assert activity(relic, by="hour_of_day", role="assistant")["buckets"] == ["11"]
    assert activity(relic, since="2026-10-23")["total"] == 4
    assert activity(relic, until="2026-09")["total"] == 1
    assert activity(relic, group="machine", top=1)["series"][-1]["name"] == "other"
    with pytest.raises(ValueError):
        activity(relic, by="year")


def test_other_streams(relic):
    t = activity(relic, stream="tools", group="tool")
    assert t["unit"] == "tool calls" and t["total"] == 1
    with pytest.raises(ValueError):
        activity(relic, group="tool")
    with pytest.raises(ValueError):
        activity(relic, stream="video")
    assert activity(relic, stream="git")["total"] == 0          # no commits pushed in the fixture


def test_weekday_hour_heatmap(relic):
    b = activity(relic, by="weekday_hour", role="assistant")["buckets"]
    assert b == ["5-11"]                       # 2026-10-23 is a Friday, the assistant row is at 11:00
