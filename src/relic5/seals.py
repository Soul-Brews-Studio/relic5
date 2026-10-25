"""seals.py: relic-scan's month seals, carried to the hub and kept honest there.

relic-scan seals a Bangkok month once it is over (relic4-scan, 2026-10-24): meta/months.json gets, per closed month,
sealed_at, sealed_rows, sealed_keys (a hash over the month file's rows) and resealed (bumped when a late row reopens
and reseals it). relic5-push sends months.json, so the hub sees every machine's seals at parts/<m>/meta/months.json.

The hub cannot recompute sealed_keys: it holds relic-extract's parts (cleaned, chunked), not the raw month file. So it
records, the first time it sees a seal, what it holds for that machine and month (each part file's size and mtime,
and its row count per stream) next to the seal, in index/_seals/seals.json, and from then on:

  reseal     sealed_keys changes (resealed > 0): the new seal is recorded and a "seal" job event says
             "month X resealed on m5, +N rows"; the month's manifest and tables rebuild as for any changed part
  re-cut     parts change under an unchanged seal (relic-extract cleaned differently): recorded, logged
  verify     every sealed month's parts still exist, have the recorded rows (parquet metadata, no scan), and the
             machine still reports the same sealed_keys; `relic5 seals --verify` exits 1 when one does not.
"""
import json, os, socket, time
from typing import Callable, TypedDict

from .parts import MONTH_STREAMS, Parts
from .types_ import Json, SealRecord
from . import store as rfs

Record = dict[str, dict[str, SealRecord]]
"""index/_seals/seals.json: {machine: {month: SealRecord}}."""


class Verify(TypedDict):
    """index/_seals/verify.json."""
    at: str
    checked: int
    problems: list[str]


class MachineSeals(TypedDict):
    sealed: int
    newest_sealed_at: str | None
    resealed: int
    months: list[str]


class Summary(TypedDict):
    machines: dict[str, MachineSeals]
    verify: Verify | None


def _dir(root: str) -> str:
    return os.path.join(root, "index", "_seals")


def machine_seals(parts: Parts, machine: str) -> dict[str, Json]:
    """{month: entry} of the sealed months a machine reported (empty when its relic-scan predates seals)."""
    p = os.path.join(parts.dir, machine, "meta", "months.json")
    try:
        months = rfs.read_json(p).get("months", [])
    except (OSError, ValueError):
        return {}
    return {m["month"]: m for m in months if m.get("sealed") and m.get("sealed_keys")}


def held(parts: Parts, machine: str, month: str) -> dict[str, list[int]]:
    """What the hub holds for one machine-month: {stream: [bytes, mtime, rows]}."""
    import pyarrow.parquet as pq
    out: dict[str, list[int]] = {}
    for s in MONTH_STREAMS:
        for _, _, f in parts.files(s, month, machine):
            size, mtime = parts.stat(f)
            with rfs.open_input(f) as fh:
                out[s] = [size, int(mtime), pq.ParquetFile(fh).metadata.num_rows]
    return out


def load(root: str) -> Record:
    p = os.path.join(_dir(root), "seals.json")
    rec: Record = rfs.read_json(p) if rfs.exists(p) else {}
    return rec


def retire(root: str, machine: str, why: str, succeeded_by: str) -> int:
    """A machine whose parts went to the attic: its seal records move to index/_seals/retired.json (kept, with when,
    why and what succeeded it: docs/RETIRED.md, the trinity rule), so verify stops reporting its parts missing, and a
    "retire" job event says so. Returns the number of months moved. A retired machine that pushes again simply gets
    new records."""
    from .jobs import emit
    if not succeeded_by.strip():
        raise ValueError("retire needs what succeeded it (docs/RETIRED.md): a machine, or 'nothing: <reason>'")
    rec = load(root)
    months = rec.pop(machine, None)
    if months is None:
        return 0
    p = os.path.join(_dir(root), "retired.json")
    old: dict[str, Json] = rfs.read_json(p) if rfs.exists(p) else {}
    at = time.gmtime()
    old[f"{machine}@{time.strftime('%Y%m%dT%H%M%SZ', at)}"] = {"why": why, "succeeded_by": succeeded_by, "months": months}
    _save(root, "retired.json", old)
    _save(root, "seals.json", rec)
    emit(root, {"job": f"retire-{machine}-{time.strftime('%Y%m%d-%H%M%S', at)}", "verb": "retire", "state": "done",
                "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", at), "pid": os.getpid(), "host": socket.gethostname(),
                "message": f"{machine} retired: {len(months)} sealed months kept in retired.json; succeeded by {succeeded_by}", "rc": 0})
    verify(root)
    return len(months)


def _save(root: str, name: str, obj: Record | Verify | dict[str, Json]) -> None:
    rfs.write_json(os.path.join(_dir(root), name), obj, indent=1)


def update(root: str, log: Callable[[str], object] = print) -> tuple[list[str], Verify]:
    """Record new seals, notice reseals and re-cuts, then verify. Returns (events, verify result)."""
    from .jobs import emit
    parts, rec = Parts(root), load(root)
    events: list[str] = []
    for m in parts.machines():
        for month, e in machine_seals(parts, m).items():
            now = held(parts, m, month)
            prev = rec.get(m, {}).get(month)
            entry: SealRecord = {"sealed_keys": e["sealed_keys"], "sealed_rows": e.get("sealed_rows"), "sealed_at": e.get("sealed_at"),
                                 "resealed": e.get("resealed", 0), "held": now, "recorded_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
            if prev is None:
                rec.setdefault(m, {})[month] = entry
                continue
            if prev["sealed_keys"] != e["sealed_keys"]:
                d = (e.get("sealed_rows") or 0) - (prev.get("sealed_rows") or 0)
                events.append(f"month {month} resealed on {m}, {d:+,} rows (resealed {e.get('resealed', 0)})")
                rec[m][month] = entry
            elif prev["held"] != now:
                events.append(f"month {month} on {m}: parts re-cut under an unchanged seal")
                rec[m][month] = entry | {"recorded_at": prev["recorded_at"]}
    _save(root, "seals.json", rec)
    for msg in events:
        log(msg)
        emit(root, {"job": f"seal-{time.strftime('%Y%m%d-%H%M%S', time.gmtime())}-{os.getpid()}", "verb": "seal", "state": "done",
                    "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "pid": os.getpid(), "host": socket.gethostname(),
                    "message": msg, "rc": 0})
    return events, verify(root)


def verify(root: str) -> Verify:
    """Check every recorded seal against the hub as it is now; writes index/_seals/verify.json."""
    import pyarrow.parquet as pq
    parts, rec, checked = Parts(root), load(root), 0
    problems: list[str] = []
    for m, months in rec.items():
        live = machine_seals(parts, m)
        for month, r in months.items():
            checked += 1
            if month in live and live[month]["sealed_keys"] != r["sealed_keys"]:
                problems.append(f"{m} {month}: the machine reports a new seal the hub has not indexed yet")
            for s, (size, mtime, rows) in r["held"].items():
                fs = [f for _, _, f in parts.files(s, month, m)]
                if not fs:
                    problems.append(f"{m} {month} {s}: part missing")
                    continue
                n = pq.ParquetFile(fs[0]).metadata.num_rows
                if n != rows:
                    problems.append(f"{m} {month} {s}: {n:,} rows, sealed with {rows:,}")
    out: Verify = {"at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "checked": checked, "problems": problems}
    _save(root, "verify.json", out)
    return out


def summary(root: str) -> Summary:
    """For relic_status: per machine, sealed months, newest seal, reseals; the last verify."""
    rec = load(root)
    per: dict[str, MachineSeals] = {}
    for m, months in rec.items():
        per[m] = {"sealed": len(months), "newest_sealed_at": max((r.get("sealed_at") or "" for r in months.values()), default=None),
                  "resealed": sum(1 for r in months.values() if r.get("resealed")), "months": sorted(months)}
    p = os.path.join(_dir(root), "verify.json")
    return {"machines": per, "verify": rfs.read_json(p) if rfs.exists(p) else None}
