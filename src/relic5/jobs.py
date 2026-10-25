"""jobs.py: what long verbs are doing, as relic3 does it (agent-relic-v3 src/contracts/status.ts JobEvent,
src/status/jobs.ts @9f0bdb5).

  <root>/logs/jobs.jsonl    one JobEvent per line, appended: {job, verb, state, at, done?, total?, unit?, message?, rc?,
                            pid, host, run?, who?}   state = start | progress | done | error

relic_status reads the last 512 KB and keeps the last event per job. A job is running when its last state is start or
progress and its pid is alive on this host, or (another host, no pid) when that event is under 10 minutes old.
`relic5 log` prints the same file as a table.
"""
import json, os, socket, sys, time
from collections.abc import Iterator
from contextlib import contextmanager

from .types_ import JobEvent, Json
from . import store as rfs

TAIL = 512 * 1024
FRESH = 600


def log_path(root: str) -> str:
    return os.path.join(rfs.root_of(root), "logs", "jobs.jsonl")


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def emit(root: str, ev: Json) -> None:
    rfs.append_line(log_path(root), json.dumps(ev, ensure_ascii=False))   # one write per line: appends never interleave


class Job:
    def __init__(self, root: str, verb: str, run: str | None = None) -> None:
        self.root, self.verb = root, verb
        self.id = f"{verb}-{time.strftime('%Y%m%d-%H%M%S')}-{os.getpid()}"
        self.base: JobEvent = {"job": self.id, "verb": verb, "pid": os.getpid(), "host": socket.gethostname()}
        if run:
            self.base["run"] = run

    def event(self, state: str, **kw: object) -> None:
        emit(self.root, {**self.base, "state": state, "at": _now(), **{k: v for k, v in kw.items() if v is not None}})

    def progress(self, done: int | None = None, total: int | None = None, unit: str | None = None, message: str | None = None) -> None:
        self.event("progress", done=done, total=total, unit=unit, message=message)


@contextmanager
def job(root: str, verb: str, run: str | None = None) -> Iterator[Job]:
    """with job(root, "index") as j: ... -> start, then done (rc 0) or error (rc 1 and the message)."""
    j = Job(root, verb, run)
    who = {"cwd": os.getcwd(), "argv": " ".join(sys.argv[1:])[:400]}
    for k, env in (("session", "CLAUDE_CODE_SESSION_ID"), ("pane", "HERDR_PANE_ID"), ("agent", "AI_AGENT")):
        if os.environ.get(env):
            who[k] = os.environ[env]
    j.event("start", who=who)
    try:
        yield j
    except BaseException as ex:
        j.event("error", rc=1, message=f"{type(ex).__name__}: {ex}"[:400])
        raise
    j.event("done", rc=0)


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


_last_done: dict[tuple[str, str], tuple[int, JobEvent | None]] = {}   # (log, verb) -> (log size when found, event)


def last_done(root: str, verb: str) -> JobEvent | None:
    """The newest finished event of one verb anywhere in the log, read backwards from the end in 512 KB steps.
    read() sees only the last 512 KB, and an index event every 10 minutes pushes a day-old nightly backup out of that
    (2026-10-25: a good 3.6 GB snapshot on m5, and Home said "no backup yet"). Cached until the log grows."""
    p = log_path(root)
    if rfs.is_s3(p):   # an S3 log is segments (store.append_line): read it whole, newest first, cached until it grows
        sig = rfs.log_signature(p)
        hit3 = _last_done.get((p, verb))
        if hit3 and hit3[0] == hash(sig):
            return hit3[1]
        want_s = f'"verb": "{verb}"'
        found_s = None
        for ln in reversed(rfs.read_lines(p)):
            if want_s in ln and '"state": "done"' in ln:
                try:
                    found_s = json.loads(ln)
                    break
                except ValueError:
                    continue
        _last_done[(p, verb)] = (hash(sig), found_s)
        return found_s
    try:
        size = rfs.getsize(p)
    except OSError:
        return None
    hit = _last_done.get((p, verb))
    if hit and hit[0] == size:
        return hit[1]
    want, found, end, carry = f'"verb": "{verb}"'.encode(), None, size, b""
    with open(p, "rb") as f:
        while end > 0 and found is None:
            start = max(0, end - TAIL)
            f.seek(start)
            buf = f.read(end - start) + carry
            lines = buf.split(b"\n")
            carry = lines[0] if start > 0 else b""        # a line cut by the step is finished by the next one
            for line in reversed(lines[1:] if start > 0 else lines):
                if want in line and b'"state": "done"' in line:
                    try:
                        found = json.loads(line)
                        break
                    except ValueError:
                        continue
            end = start
    _last_done[(p, verb)] = (size, found)
    return found


def read(root: str, now: float | None = None) -> tuple[list[JobEvent], list[JobEvent]]:
    """-> (last event per job, newest first; running ones)."""
    data = rfs.tail_lines(log_path(root), TAIL)
    if not data:
        return [], []
    last: dict[str, JobEvent] = {}
    for line in data:
        try:
            ev = json.loads(line)
            last[ev["job"]] = ev
        except (ValueError, KeyError, TypeError):
            continue   # the first line of a tail may be cut
    evs = sorted(last.values(), key=lambda e: e.get("at", ""), reverse=True)
    now = now or time.time()
    here = socket.gethostname()
    running = []
    for e in evs:
        if e.get("state") not in ("start", "progress"):
            continue
        if e.get("host") == here and e.get("pid"):
            ok = _alive(e["pid"])
        else:
            ok = now - time.mktime(time.strptime(e["at"], "%Y-%m-%dT%H:%M:%SZ")) + time.timezone < FRESH
        if ok:
            running.append(e)
    return evs, running
