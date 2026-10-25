"""readings.py: relic-extract's model readings of each window, served by the hub."""
import json, os

import pytest

from relic5 import readings as R


def write(root, lines):
    os.makedirs(os.path.join(root, "readings"), exist_ok=True)
    with open(os.path.join(root, "readings", "m5.jsonl"), "w") as f:
        for d in lines:
            f.write((d if isinstance(d, str) else json.dumps(d, ensure_ascii=False)) + "\n")


def ans(focus, **k):
    return {"type": "build", "focus": focus, "distraction": "none", "work": ["w"], "agents": "a", "pattern": "p", "en": focus, "th": "ไทย", **k}


def test_units_and_models():
    assert R.window("2025-09-19 21:00-24:00 3h") == ("3h", "2025-09-19 21:00", "2025-09-19 24:00")
    assert R.window("2025-10-24 day") == ("day", "2025-10-24 00:00", "2025-10-24 24:00")
    assert R.window("2025-09-21") == ("day", "2025-09-21 00:00", "2025-09-21 24:00")
    assert R.window("2025-09-19 15-1h") == ("1h", "2025-09-19 15:00", "2025-09-19 16:00")
    assert R.window("2025-09-19 15") == ("3h", "2025-09-19 15:00", "2025-09-19 18:00")
    assert R.window("nonsense") is None
    assert R.model_of("zai:glm-5.3 deep") == ("zai:glm-5.3", True) and R.model_of("qwen3:14b") == ("gb300:qwen3:14b", False)


def test_readings_filter_and_newest_answer(root):
    write(root, [
        {"at": "2026-10-23T10:00:00+0700", "unit": "2026-10-20 10:00-10:15 15m", "model": "zai:glm-5.3 deep", "answer": ans("old focus")},
        {"at": "2026-10-24T10:00:00+0700", "unit": "2026-10-20 10:00-10:15 15m", "model": "zai:glm-5.3 deep",
         "answer": ans("relic hub build", friction="slow index", lesson="cache it")},
        {"at": "2026-10-24T10:00:00+0700", "unit": "2026-10-20 10:00-10:15 15m", "model": "gb300:qwen3:14b deep", "answer": ans("hub work")},
        {"at": "2026-10-24T10:00:00+0700", "unit": "2026-10-21 day", "model": "zai:glm-5.3", "answer": ans("a day of books")},
        "not json", {"unit": "2026-10-22 day", "model": "zai:glm-5.3", "answer": {"type": "x"}}])   # no focus: skipped
    r = R.readings(root)
    assert r["total"] == 3 and r["rows"][0]["grain"] == "day" and r["files"] == ["m5.jsonl"]
    z = R.readings(root, model="zai", grain="15m")["rows"]
    assert len(z) == 1 and z[0]["focus"] == "relic hub build" and z[0]["lesson"] == "cache it" and z[0]["machine"] == "m5"
    assert R.readings(root, q="hub")["total"] == 2 and R.readings(root, q="hub cache")["total"] == 1
    assert R.readings(root, since="2026-10-21")["total"] == 1 and R.readings(root, until="2026-10-20")["total"] == 2
    p = R.readings(root, limit=2)
    assert len(p["rows"]) == 2 and p["next_offset"] == 2
    with pytest.raises(ValueError):
        R.readings(root, grain="week")


def test_no_readings_says_where_they_come_from(root):
    assert R.readings(root)["total"] == 0 and "rsync" in R.readings(root)["note"]
