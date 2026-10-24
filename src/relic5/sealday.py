"""sealday.py: seal day. When a Bangkok month is over, every machine's relic-scan seals it (seals.py); the hub then
reconciles the month end to end and writes it down once, with a fingerprint.

For a month M, per live machine (not an *-import):
  sealing    the machine has not sealed M yet (its months.json still lists M open), or has sent no receipt for it:
             the hub waits, and names who it waits for
  blocked    the receipt and the hub's copy disagree: a part missing on the hub, a sha256 or size that differs (the
             push carries, per sealed month, each part's sha256 as the machine holds it: bin/relic5-push)
  ok         every part on the hub is byte-identical to the machine's
A machine with no rows in M (no entry in its months.json) has nothing to reconcile. When every live machine is ok,
the hub writes index/_seals/days/<M>.json: per machine its seal (sealed_keys, sealed_rows) and parts (sha256, rows),
the folded counts of M's manifest, a fingerprint over all of it, and when; and logs a "seal-day" job event.

After that the record is history. A later reseal (a late row: resealed > 0, a new sealed_keys) does not rewrite it:
it appends an amendment {at, machine, from, to, delta rows, fingerprint} and logs it. A month still sealing or
blocked three days after it ended is a relic_status warning.
"""
import hashlib, json, os, socket, time
from datetime import datetime, timedelta, timezone
from typing import Literal, TypedDict

from .parts import BKK, MONTH_STREAMS, Parts, this_month
from .seals import machine_seals
from .types_ import Json

GRACE_DAYS = 3


class PartReceipt(TypedDict):
    bytes: int
    sha256: str


class MachineSeal(TypedDict):
    sealed_keys: str
    sealed_rows: int | None
    parts: dict[str, PartReceipt]
    rows: dict[str, int]


class Amendment(TypedDict):
    at: str
    machine: str
    sealed_from: str
    sealed_to: str
    delta_rows: int
    fingerprint: str


class Day(TypedDict):
    month: str
    reconciled_at: str
    machines: dict[str, MachineSeal]
    folded: dict[str, int]
    fingerprint: str
    amendments: list[Amendment]


State = Literal["reconciled", "sealing", "blocked", "open"]


class MonthState(TypedDict):
    month: str
    state: State
    waiting: list[str]
    problems: list[str]
    fingerprint: str | None
    reconciled_at: str | None
    amendments: int
    recap: bool


def _days_dir(root: str) -> str:
    return os.path.join(root, "index", "_seals", "days")


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def receipts(parts: Parts, machine: str) -> dict[str, Json]:
    """{month: {sealed_keys, sealed_rows, parts: {stream: {bytes, sha256}}}} from the machine's last push."""
    p = os.path.join(parts.dir, machine, "meta", "receipts.json")
    try:
        months: dict[str, Json] = json.load(open(p)).get("months", {})
        return months
    except (OSError, ValueError):
        return {}


def _sha(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def _scan_months(parts: Parts, machine: str) -> set[str]:
    """Every month the machine's relic-scan knows (sealed or not)."""
    p = os.path.join(parts.dir, machine, "meta", "months.json")
    try:
        return {m["month"] for m in json.load(open(p)).get("months", [])}
    except (OSError, ValueError):
        return set()


def live_machines(parts: Parts) -> list[str]:
    """Machines that run a chain: every pushing machine except the one-time imports."""
    return [m for m in parts.machines() if not m.endswith("-import")]


def check(root: str, month: str) -> tuple[MonthState, dict[str, MachineSeal]]:
    """Reconcile one month as the hub holds it now (writes nothing)."""
    import pyarrow.parquet as pq
    parts = Parts(root)
    st: MonthState = {"month": month, "state": "open", "waiting": [], "problems": [], "fingerprint": None,
                      "reconciled_at": None, "amendments": 0, "recap": False}
    if month == "undated" or month >= this_month():
        return st, {}
    got: dict[str, MachineSeal] = {}
    for m in live_machines(parts):
        if month not in _scan_months(parts, m):
            continue                                            # no rows that month: nothing to reconcile
        seal = machine_seals(parts, m).get(month)
        rec = receipts(parts, m).get(month)
        if seal is None:
            st["waiting"].append(f"{m}: has not sealed {month}")
            continue
        if rec is None or rec.get("sealed_keys") != seal["sealed_keys"]:
            st["waiting"].append(f"{m}: no receipt for this seal yet (next push)")
            continue
        ms: MachineSeal = {"sealed_keys": seal["sealed_keys"], "sealed_rows": seal.get("sealed_rows"), "parts": {}, "rows": {}}
        for s, r in rec.get("parts", {}).items():
            fs = [f for _, _, f in parts.files(s, month, m)]
            if not fs:
                st["problems"].append(f"{m} {month} {s}: the machine has it, the hub does not")
                continue
            size = os.path.getsize(fs[0])
            if size != r["bytes"] or _sha(fs[0]) != r["sha256"]:
                st["problems"].append(f"{m} {month} {s}: the hub's copy differs from the machine's ({size:,} vs {r['bytes']:,} bytes)")
                continue
            ms["parts"][s] = {"bytes": r["bytes"], "sha256": r["sha256"]}
            ms["rows"][s] = pq.ParquetFile(fs[0]).metadata.num_rows
        got[m] = ms
    st["state"] = "blocked" if st["problems"] else "sealing" if st["waiting"] else "reconciled"
    return st, got


def _folded(root: str, month: str) -> dict[str, int]:
    p = Parts(root).manifest_path(month)
    if not os.path.exists(p):
        return {}
    streams: dict[str, Json] = json.load(open(p)).get("streams", {})
    return {s: int(v["rows"]) for s, v in streams.items() if s in MONTH_STREAMS}


def _fingerprint(machines: dict[str, MachineSeal], folded: dict[str, int]) -> str:
    body = json.dumps({"machines": machines, "folded": folded}, sort_keys=True)
    return hashlib.sha256(body.encode()).hexdigest()[:16]


def load(root: str, month: str) -> Day | None:
    p = os.path.join(_days_dir(root), f"{month}.json")
    if not os.path.exists(p):
        return None
    d: Day = json.load(open(p))
    return d


def _save(root: str, day: Day) -> None:
    os.makedirs(_days_dir(root), exist_ok=True)
    p = os.path.join(_days_dir(root), f"{day['month']}.json")
    with open(p + ".tmp", "w") as f:
        json.dump(day, f, indent=1)
    os.replace(p + ".tmp", p)


def _log(root: str, msg: str) -> None:
    from .jobs import emit
    emit(root, {"job": f"seal-day-{time.strftime('%Y%m%d-%H%M%S', time.gmtime())}-{os.getpid()}", "verb": "seal-day",
                "state": "done", "at": _now(), "pid": os.getpid(), "host": socket.gethostname(), "message": msg, "rc": 0})


def reconcile(root: str, month: str) -> MonthState:
    """Reconcile one month; write its seal-day record the first time it is whole, or an amendment after a reseal."""
    st, got = check(root, month)
    day = load(root, month)
    if day:
        st["fingerprint"], st["reconciled_at"], st["amendments"] = day["fingerprint"], day["reconciled_at"], len(day["amendments"])
    if st["state"] != "reconciled":
        if day and st["state"] == "sealing":
            st["state"] = "reconciled"                          # reconciled once; a machine resealing now is amending
        return st
    folded = _folded(root, month)
    fp = _fingerprint(got, folded)
    if day is None:
        day = {"month": month, "reconciled_at": _now(), "machines": got, "folded": folded, "fingerprint": fp, "amendments": []}
        _save(root, day)
        n = len(got)
        _log(root, f"{month} reconciled: {n} machine{'s' if n != 1 else ''}, {folded.get('text', 0):,} messages folded, fingerprint {fp}")
    elif fp != (day["amendments"][-1]["fingerprint"] if day["amendments"] else day["fingerprint"]):
        for m, ms in got.items():
            was = day["machines"].get(m)
            if was is None or was["sealed_keys"] != ms["sealed_keys"] or was["parts"] != ms["parts"]:
                prev_rows, prev_keys = (was["sealed_rows"] or 0, was["sealed_keys"]) if was else (0, "")
                delta = (ms["sealed_rows"] or 0) - prev_rows
                day["amendments"].append({"at": _now(), "machine": m, "sealed_from": prev_keys,
                                          "sealed_to": ms["sealed_keys"], "delta_rows": delta, "fingerprint": fp})
                _log(root, f"{month} amended: {m} resealed, {delta:+,} rows, fingerprint {fp}")
        day["machines"], day["folded"] = got, folded
        _save(root, day)
    st["fingerprint"], st["reconciled_at"], st["amendments"] = fp, day["reconciled_at"], len(day["amendments"])
    return st


def run(root: str) -> list[MonthState]:
    """Every closed month any machine knows, oldest first: reconcile what can be, report the rest."""
    parts = Parts(root)
    months = sorted({mo for m in live_machines(parts) for mo in _scan_months(parts, m)} | set(parts.months()))
    out = [reconcile(root, mo) for mo in months if mo != "undated"]
    os.makedirs(os.path.dirname(_days_dir(root)), exist_ok=True)
    p = os.path.join(os.path.dirname(_days_dir(root)), "months.json")
    with open(p + ".tmp", "w") as f:
        json.dump({"at": _now(), "months": out}, f, indent=1)
    os.replace(p + ".tmp", p)
    return out


def summary(root: str) -> list[MonthState]:
    p = os.path.join(root, "index", "_seals", "months.json")
    if not os.path.exists(p):
        return []
    months: list[MonthState] = json.load(open(p)).get("months", [])
    for m in months:   # written by bin/relic5-month-recap after the month reconciled (it may come later than the record)
        m["recap"] = os.path.isfile(recap_path(root, m["month"]))
    return months


def recap_path(root: str, month: str) -> str:
    return os.path.join(root, "recaps", f"{month}.md")


def overdue(states: list[MonthState], now: datetime | None = None) -> list[str]:
    """Warnings: closed months still sealing or blocked GRACE_DAYS after they ended (Bangkok). Months stuck for the
    same reason are one line ("13 months still sealing (2025-09 .. 2026-09): m5, mba have not sealed them"), so a
    machine that has not sealed anything yet does not bury every other warning."""
    now = now or datetime.now(timezone.utc)
    groups: dict[tuple[str, str], list[str]] = {}
    for s in states:
        if s["state"] not in ("sealing", "blocked"):
            continue
        y, mo = int(s["month"][:4]), int(s["month"][5:7])
        end = datetime(y + mo // 12, mo % 12 + 1, 1, tzinfo=BKK)
        if now - end > timedelta(days=GRACE_DAYS):
            why = "; ".join(w.replace(s["month"], "the month") for w in (s["problems"] or s["waiting"])[:3])
            groups.setdefault((s["state"], why), []).append(s["month"])
    out = []
    for (state, why), ms in groups.items():
        span = ms[0] if len(ms) == 1 else f"{len(ms)} months ({ms[0]} .. {ms[-1]})"
        out.append(f"seal day {span}: still {state} {GRACE_DAYS}+ days after it ended: {why}")
    return out
