from datetime import datetime, timezone

import pytest

from relic5.window import WindowError, bound, window

NOW = datetime(2026, 10, 23, 12, 0, tzinfo=timezone.utc)


def test_bounds():
    assert bound("2026-10-23") == "2026-10-23T00:00:00.000Z"
    assert bound("2026-10-23", end=True) == "2026-10-23T23:59:59.999Z"
    assert bound("2h", now=NOW) == "2026-10-23T10:00:00.000Z"
    assert bound("1m", now=NOW) == "2026-10-23T11:59:00.000Z"
    assert bound("2026-10-23T17:00:00+07:00") == "2026-10-23T10:00:00.000Z"
    with pytest.raises(WindowError):
        bound("yesterday")


def test_horizon():
    assert window(horizon="7d", now=NOW)[0] == "2026-10-16T12:00:00.000Z"
    assert window(horizon="archive") == (None, None, "archive")
    with pytest.raises(WindowError):
        window(since="1d", horizon="7d")
