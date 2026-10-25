"""ravens.py: one day, hour by hour, as Odin's ravens and relic-extract's models saw it (Nat, 2026-10-26: "i want that
in our system how? ... can we display the odin 2 skills output?").

  huginn   odin-oracle's hourly flight (/huginn): ψ/memory/huginn/<date>/<HH>00_works.md, and DAILY_works.md
  munin    odin-oracle's memory searches (/munin): ψ/memory/munin/<date>/*.md
  readings what gb300 and z.ai made of the same day, its 3h, 1h and 15m windows (readings.py)

Huginn and Munin are ψ notes, so they arrive like every note: relic-scan lists the vault, relic-extract's
report/vaults.py writes parts/<machine>/vault/notes.parquet, relic5-push copies it here. Nothing is asked of a model.
"""
import os, re
from typing import Any

from .types_ import Json

OVER = 400   # relic-extract vaults.py cuts a note at 6000 characters with 400 of overlap: chunk n>0 repeats 400 of n-1
HOUR = re.compile(r"/(\d{2})(\d{2})_[^/]*\.md$")
DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def joined(parts: list[str]) -> str:
    """A note's chunks back into the note: the first whole, the rest without the overlap they repeat."""
    return "".join(p if i == 0 else p[OVER:] for i, p in enumerate(parts))


def _notes(relic: Any, likes: list[str]) -> list[Json]:
    from . import store as rfs
    files = sorted(rfs.glob(os.path.join(relic.parts.root, "parts", "*", "vault", "notes.parquet")))
    if not files:
        return []
    lst = ", ".join("'" + f.replace("'", "''") + "'" for f in files)
    where = " OR ".join("path LIKE ?" for _ in likes)
    rows: list[Json] = relic._rows(f"""
        WITH n AS (SELECT DISTINCT msgkey, chunk, path, cat, vault, ts, title, text
                   FROM read_parquet([{lst}], union_by_name = true) WHERE {where}),
             m AS (SELECT msgkey, any_value(path) AS path, any_value(cat) AS cat, any_value(vault) AS vault, max(ts) AS ts,
                          any_value(title) AS title, list(text ORDER BY chunk) AS parts FROM n GROUP BY msgkey)
        SELECT path, cat, vault, ts, title, parts FROM m
        QUALIFY row_number() OVER (PARTITION BY path ORDER BY (cat = 'odin-oracle') DESC, (vault = 'own') DESC, ts DESC) = 1
        ORDER BY path""", likes)
    for r in rows:
        r["text"] = joined(list(r.pop("parts") or []))
    return rows


def hours(relic: Any, date: str) -> Json:
    """Everything the hub has for one Bangkok day: Huginn's hourly flights and day roll-up, Munin's searches, and the
    model readings of that day, the hourly ones grouped under their hour."""
    from . import readings as R
    if not DATE.match(date):
        raise ValueError("date is YYYY-MM-DD")
    notes = _notes(relic, [f"memory/huginn/{date}/%", f"memory/munin/{date}/%"])
    flights: dict[str, Json] = {}
    daily, munin = None, []
    for n in notes:
        base = n["path"].rsplit("/", 1)[-1]
        note = {"path": n["path"], "cat": n["cat"], "ts": n["ts"], "title": n["title"], "text": n["text"]}
        if n["path"].startswith("memory/munin/"):
            munin.append(note)
        elif base.upper().startswith("DAILY"):
            daily = note
        elif m := HOUR.search(n["path"]):
            flights.setdefault(m[1], note)
    rs = R.readings(relic.parts.root, since=f"{date} 00:00", until=date, limit=100000)["rows"]
    day = [r for r in rs if r["grain"] == "day"]
    by_hour: dict[str, list[Json]] = {}
    for r in rs:
        if r["grain"] != "day":
            by_hour.setdefault(r["start"][11:13], []).append(r)
    hrs = sorted(set(flights) | set(by_hour), reverse=True)
    newest = max((n["ts"] for n in notes), default=None)
    return {"date": date, "daily": daily, "day": day, "munin": munin,
            "hours": [{"hour": h, "huginn": flights.get(h),
                       "readings": sorted(by_hour.get(h, []), key=lambda r: (r["grain"] != "1h", r["grain"] != "3h", r["start"], r["model"]))}
                      for h in hrs],
            "notes_newest": newest, "readings_files": [os.path.basename(p) for p in R.files(relic.parts.root)]}


def days(relic: Any, limit: int = 60) -> Json:
    """The days that have a Huginn flight or a reading, newest first, with counts: the day picker."""
    from . import readings as R
    from . import store as rfs
    counts: dict[str, Json] = {}

    def bump(d: str, k: str) -> None:
        counts.setdefault(d, {"date": d, "huginn": 0, "readings": 0})[k] += 1

    files = sorted(rfs.glob(os.path.join(relic.parts.root, "parts", "*", "vault", "notes.parquet")))
    if files:
        lst = ", ".join("'" + f.replace("'", "''") + "'" for f in files)
        for r in relic._rows(f"""SELECT DISTINCT path FROM read_parquet([{lst}], union_by_name = true)
                                 WHERE path LIKE 'memory/huginn/%' AND cat = 'odin-oracle'"""):
            d = r["path"].split("/")[2]
            if DATE.match(d) and HOUR.search(r["path"]):
                bump(d, "huginn")
    for r in R.readings(relic.parts.root, limit=10**7)["rows"]:
        bump(r["start"][:10], "readings")
    return {"days": sorted(counts.values(), key=lambda c: c["date"], reverse=True)[:limit]}
