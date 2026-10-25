"""mirror.py: the hub's data copied to a second home (a disk folder or an S3 prefix), checked, and switched to
(Nat, 2026-10-25: "ui config local / s3 / mirror / or switch?").

  copy(src, dst)     every file under the data folders of src that dst lacks or holds at another size, streamed
                     (pyarrow filesystems), never a delete: a mirror only grows, like the offsite copy
  verify(src, dst)   file by file: missing on dst, and size differences
  config             ~/.config/relic5/storage.json {"mirror": "<root>", "every_min": 60, "switch_to": "<root>"};
                     RELIC5_MIRROR overrides the mirror target
  keep_mirrored()    a thread in `relic5 serve`: a copy every every_min minutes, each a "mirror" job in logs/jobs.jsonl

Switching is a restart, never a hot swap: `relic5 serve` starts on storage.json's switch_to when it is set (and
says so in status), so the next start of the hub reads from the new home. The page sets it only after a verify
with nothing missing.
"""
import json, os, threading, time
from typing import Any

from . import store as rfs
from .types_ import Json

DIRS = ("parts", "vectors", "resolve", "logs", "attic", "artifacts", "recaps", "index")
CONFIG = os.path.expanduser(os.environ.get("RELIC5_STORAGE", "~/.config/relic5/storage.json"))
_LOCK = threading.Lock()
_STATE: Json = {"running": None}


def config() -> Json:
    try:
        c: Json = json.load(open(CONFIG))
    except (OSError, ValueError):
        c = {}
    if os.environ.get("RELIC5_MIRROR"):
        c["mirror"] = os.environ["RELIC5_MIRROR"]
    return c


def set_config(**kw: Any) -> Json:
    c = {k: v for k, v in config().items()}
    c.update({k: v for k, v in kw.items()})
    c = {k: v for k, v in c.items() if v not in (None, "")}
    os.makedirs(os.path.dirname(CONFIG), exist_ok=True)
    tmp = CONFIG + ".tmp"
    with open(tmp, "w") as f:
        json.dump(c, f, indent=1)
    os.chmod(tmp, 0o600)
    os.replace(tmp, CONFIG)
    return c


def _listing(root: str, dirs: tuple[str, ...]) -> dict[str, int]:
    out: dict[str, int] = {}
    for d in dirs:
        base = os.path.join(root, d)
        if not rfs.isdir(base):
            continue
        for p, n, _ in rfs.files(base):
            rel = p[len(root.rstrip("/")) + 1:]
            if rel.endswith(".tmp") or "/.lock" in rel or rel.split("/")[-1].startswith(".tmp-"):
                continue
            out[rel] = n
    return out


def _copy_one(src: str, dst: str) -> None:
    """One file, streamed: pyarrow copies between a disk and S3 without holding the file in memory."""
    import pyarrow.fs as pf
    def fs_of(p: str) -> tuple[Any, str]:
        return (rfs._fs(), rfs._k(p)) if rfs.is_s3(p) else (pf.LocalFileSystem(), p)
    sfs, sp = fs_of(src)
    dfs, dp = fs_of(dst)
    if not rfs.is_s3(dst):
        os.makedirs(os.path.dirname(dst), exist_ok=True)
    with sfs.open_input_stream(sp) as i, dfs.open_output_stream(dp) as o:
        while True:
            b = i.read(8 << 20)
            if not b:
                break
            o.write(b)


MOVING = ("logs/", "index/")   # always behind on a live hub (a line per request; a new index after every push)


def verify(src: str, dst: str, dirs: tuple[str, ...] = DIRS) -> Json:
    """File by file. ok = every file of the data itself (parts, vectors, resolve, artifacts, recaps, attic) is on dst
    at the same size. Logs and the index move while a hub runs, so they are counted as behind, not failed: logs only
    grow, and a hub rebuilds its index from the parts."""
    src, dst = rfs.root_of(src), rfs.root_of(dst)
    a, b = _listing(src, dirs), _listing(dst, dirs)
    missing = sorted(k for k in a if k not in b)
    differ = sorted(k for k in a if k in b and a[k] != b[k])
    bad = [k for k in missing + differ if not k.startswith(MOVING)]
    behind = [k for k in missing + differ if k.startswith(MOVING)]
    return {"src": src, "dst": dst, "files": len(a), "bytes": sum(a.values()), "on_dst": len(b),
            "missing": len([k for k in missing if not k.startswith(MOVING)]), "differ": len([k for k in differ if not k.startswith(MOVING)]),
            "behind": len(behind), "examples": bad[:10], "ok": not bad,
            "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}


def copy(src: str, dst: str, dirs: tuple[str, ...] = DIRS, log: Any = None) -> Json:
    """Copy what dst lacks or holds at another size. -> {files, bytes, skipped, seconds, errors}."""
    src, dst = rfs.root_of(src), rfs.root_of(dst)
    if src == dst:
        raise ValueError("source and mirror are the same place")
    t0 = time.time()
    a, b = _listing(src, dirs), _listing(dst, dirs)
    todo = sorted(k for k in a if b.get(k) != a[k])
    sent, errors = 0, []
    for i, rel in enumerate(todo):
        try:
            _copy_one(os.path.join(src, rel), os.path.join(dst, rel))
            sent += a[rel]
        except Exception as ex:   # one file failing leaves the rest to copy; the next run tries it again
            errors.append(f"{rel}: {type(ex).__name__}: {str(ex)[:120]}")
        if log and (i % 50 == 0 or i == len(todo) - 1):
            log(i + 1, len(todo), sent)
    return {"src": src, "dst": dst, "files": len(todo) - len(errors), "bytes": sent, "skipped": len(a) - len(todo),
            "seconds": round(time.time() - t0, 1), "errors": errors[:20]}


def run(root: str, dst: str | None = None) -> Json:
    """One mirror run as a job (jobs.jsonl verb "mirror"), the state kept for the Storage page."""
    from .jobs import job
    dst = dst or config().get("mirror")
    if not dst:
        raise ValueError("no mirror set: give a folder or s3://bucket/prefix")
    with _LOCK:
        if _STATE.get("running"):
            return {"running": _STATE["running"]}
        _STATE["running"] = {"dst": dst, "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "done": 0, "total": None}
    try:
        with job(root, "mirror") as j:
            def log(done: int, total: int, sent: int) -> None:
                _STATE["running"] |= {"done": done, "total": total}
                j.progress(done=done, total=total, unit="files", message=f"mirror to {dst}: {done}/{total} files, {sent:,} bytes")
            out = copy(root, dst, log=log)
            j.progress(message=f"mirror to {dst}: {out['files']} files, {out['bytes']:,} bytes, {out['skipped']} already there, {out['seconds']} s"
                       + (f", {len(out['errors'])} failed" if out["errors"] else ""))
        _STATE["last"] = out | {"at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
        return out
    finally:
        with _LOCK:
            _STATE["running"] = None


def state() -> Json:
    return dict(_STATE)


def keep_mirrored(root: str) -> threading.Thread:
    def loop() -> None:
        time.sleep(30)
        while True:
            c = config()
            if c.get("mirror"):
                try:
                    run(root, c["mirror"])
                except Exception as ex:
                    _STATE["last"] = {"error": f"{type(ex).__name__}: {ex}"[:300], "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
            time.sleep(max(5, int(c.get("every_min") or 60)) * 60)
    t = threading.Thread(target=loop, name="relic5-mirror", daemon=True)
    t.start()
    return t
