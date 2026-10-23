"""window.py: since / until / horizon, read the way relic3 reads them (agent-relic-v3 src/contracts/window.ts @9f0bdb5).

  YYYY-MM-DD   a UTC day: since = 00:00:00Z of it, until = through 23:59:59.999Z of it
  ISO time     as given (2026-10-23T10:00:00Z, or with an offset)
  Nd / Nh / Nm N days / hours / minutes before now (1m = one minute, as relic3)

horizon (7d | 15d | 1m | 3m | archive) is a window that starts N before now; archive = no start. Here 1m and 3m
of a horizon are 30 and 90 days. Every bound comes back as UTC ISO text with milliseconds and Z, the form of the
parts' ts column, so a bound compares as text.
"""
import re
from datetime import datetime, timedelta, timezone

HORIZONS = {"7d": 7, "15d": 15, "1m": 30, "3m": 90, "archive": None}


class WindowError(ValueError):
    pass


def iso(dt):
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def bound(v, end=False, now=None):
    """One since/until value -> UTC ISO text, or None when v is empty. Raises WindowError for unreadable text."""
    if v is None or v == "":
        return None
    now = now or datetime.now(timezone.utc)
    m = re.fullmatch(r"(\d+)([dhm])", v)
    if m:
        n, u = int(m.group(1)), m.group(2)
        return iso(now - timedelta(**{{"d": "days", "h": "hours", "m": "minutes"}[u]: n}))
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", v):
        try:
            d = datetime.strptime(v, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        except ValueError:
            raise WindowError(f"{v}: not a day")
        return iso(d + timedelta(days=1) - timedelta(milliseconds=1)) if end else iso(d)
    try:
        d = datetime.fromisoformat(v.replace("Z", "+00:00"))
    except ValueError:
        raise WindowError(f"{v}: expected YYYY-MM-DD (a UTC day), an ISO time, or Nd/Nh/Nm")
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return iso(d)


def window(since=None, until=None, horizon=None, now=None):
    """-> (since, until, horizon name). horizon and since/until each set the window: one or the other."""
    if horizon and (since or until):
        raise WindowError("horizon and since/until each set the window - pick one.")
    if horizon:
        if horizon not in HORIZONS:
            raise WindowError(f"horizon {horizon}: one of {' | '.join(HORIZONS)}")
        days = HORIZONS[horizon]
        now = now or datetime.now(timezone.utc)
        return (iso(now - timedelta(days=days)) if days else None), None, horizon
    return bound(since, False, now), bound(until, True, now), ("window" if since or until else "archive")
