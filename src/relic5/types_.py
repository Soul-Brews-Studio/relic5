"""Shared types. JSON that crosses a boundary (an HTTP reply, a jsonl line, a manifest) is Json; the shapes passed
between modules are TypedDicts here, so mypy --strict (tests/test_types.py) checks every use of them."""
from typing import Any, TypedDict

Json = dict[str, Any]
"""A JSON object as json.load returns it: keys are strings, values are not checked further."""


class JobEvent(TypedDict, total=False):
    """One line of logs/jobs.jsonl (relic3 JobEvent): start, progress, done or error of one job."""
    job: str
    verb: str
    state: str
    at: str
    pid: int
    host: str
    message: str | None
    rc: int | None
    done: int | None
    total: int | None
    unit: str | None
    who: Json
    run: str


class MemoryRow(TypedDict):
    """One memory note as memory.py indexes it."""
    machine: str
    machines: list[str]
    msgkey: str
    chunk: int
    key: str
    month: str
    sid: str
    ts: str
    ts_th: str
    role: str
    engine: str
    cat: str
    title: str
    text: str
    path: str
    origin: str | None


class SealRecord(TypedDict):
    """One machine-month seal as the hub recorded it (seals.py); held = {stream: [bytes, mtime, rows]}."""
    sealed_keys: str
    sealed_rows: int | None
    sealed_at: str | None
    resealed: int
    held: dict[str, list[int]]
    recorded_at: str
