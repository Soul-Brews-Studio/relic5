"""store.py: the hub's files on a local disk or in an S3 bucket, behind one set of calls (Nat, 2026-10-25: "make it
fully perfect native support local or s3").

A path is a local path (/data/parts/m5/text/2026-10.parquet) or an S3 URL (s3://relic5-live/hub/parts/...). Every
call below takes either and does the same thing; os.path.join, basename and dirname work on both, since an S3 URL
is a POSIX-style path after its scheme. The engines read S3 natively: DuckDB through httpfs (duck()), LanceDB through
its object store (lance_options()).

  RELIC5_ROOT              /data, ~/relic5, or s3://bucket/prefix
  RELIC5_S3_ENDPOINT       default http://black.follow-rankine.ts.net:9200 (black's RustFS)
  RELIC5_S3_REGION         default black-ssd-rustfs
  RELIC5_S3_KEY            a 0600 file: line 1 the access key, line 2 the secret (default ~/.config/relic5/s3-live);
                           or AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY

S3 has no append. A log line (append_line) on S3 is one small object under <file>.d/, named by time so a listing
gives them in order; read_lines() reads the file (if any) and then every segment, and compact() rolls old segments
into one chunk object. RustFS shows a delete in a listing late, so a reader that meets a chunk and the segments it
replaced in one listing drops the repeated lines.

What a hub only caches (maps, the in-memory tables) lives in cache_dir(): under the root on a disk, and in a local
folder for an S3 root, since a cache is cheaper to rebuild than to fetch.
"""
import hashlib, io, json, os, socket, threading, time
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import duckdb
    import pyarrow.fs

_LOCK = threading.Lock()
_FS: "dict[str, pyarrow.fs.S3FileSystem]" = {}


def is_s3(p: str) -> bool:
    return str(p).startswith("s3://")


def root_of(root: str) -> str:
    """A root as the hub keeps it: an S3 URL without a trailing slash, or an absolute local path."""
    root = str(root)
    if is_s3(root):
        return root.rstrip("/")
    return os.path.abspath(os.path.expanduser(root))


def s3_config() -> dict[str, str]:
    key_file = os.path.expanduser(os.environ.get("RELIC5_S3_KEY", "~/.config/relic5/s3-live"))
    ak, sk = os.environ.get("AWS_ACCESS_KEY_ID", ""), os.environ.get("AWS_SECRET_ACCESS_KEY", "")
    if os.environ.get("RELIC5_S3_KEY") or not (ak and sk):
        try:
            lines = open(key_file).read().split()
            ak, sk = lines[0], lines[1]
        except (OSError, IndexError):
            pass
    ep = os.environ.get("RELIC5_S3_ENDPOINT", "http://black.follow-rankine.ts.net:9200")
    return {"access_key": ak, "secret_key": sk, "endpoint": ep, "region": os.environ.get("RELIC5_S3_REGION", "black-ssd-rustfs"),
            "scheme": ep.split("://")[0] if "://" in ep else "https", "host": ep.split("://")[-1].rstrip("/")}


def _fs() -> "pyarrow.fs.S3FileSystem":
    import pyarrow.fs as pf
    c = s3_config()
    k = c["host"] + c["access_key"]
    with _LOCK:
        if k not in _FS:
            if not c["access_key"]:
                raise RuntimeError("an S3 root needs a key: RELIC5_S3_KEY (a 0600 file, key and secret) or AWS_ACCESS_KEY_ID")
            _FS[k] = pf.S3FileSystem(access_key=c["access_key"], secret_key=c["secret_key"], endpoint_override=c["host"],
                                     scheme=c["scheme"], region=c["region"])
        return _FS[k]


def _k(p: str) -> str:
    return str(p)[5:].rstrip("/")


# ---- reading --------------------------------------------------------------------------------------------------

_SEEN: dict[str, tuple[float, Any]] = {}   # S3 path -> (when, FileInfo): a query checks the same few files each time
SEEN_TTL = 10.0


def _info(p: str) -> Any:
    now = time.time()
    hit = _SEEN.get(p)
    if hit and now - hit[0] < SEEN_TTL:
        return hit[1]
    i = _fs().get_file_info(_k(p))
    if len(_SEEN) > 4096:
        _SEEN.clear()
    _SEEN[p] = (now, i)
    return i


def _forget(p: str) -> None:
    _SEEN.pop(p, None)


def exists(p: str) -> bool:
    if not is_s3(p):
        return os.path.exists(p)
    return isfile(p) or isdir(p)


def isfile(p: str) -> bool:
    if not is_s3(p):
        return os.path.isfile(p)
    import pyarrow.fs as pf
    return bool(_info(p).type == pf.FileType.File)


def isdir(p: str) -> bool:
    """On S3 a folder is a prefix that holds something."""
    if not is_s3(p):
        return os.path.isdir(p)
    import pyarrow.fs as pf
    try:
        return len(_fs().get_file_info(pf.FileSelector(_k(p), recursive=False, allow_not_found=True))) > 0
    except OSError:
        return False


def listdir(p: str) -> list[str]:
    """Names one level under p (files and folders), like os.listdir; [] when p holds nothing."""
    if not is_s3(p):
        return os.listdir(p) if os.path.isdir(p) else []
    import pyarrow.fs as pf
    infos = _fs().get_file_info(pf.FileSelector(_k(p), recursive=False, allow_not_found=True))
    return sorted({os.path.basename(i.path.rstrip("/")) for i in infos})


def files(p: str) -> list[tuple[str, int, float]]:
    """Every file under p, recursively: (path, bytes, mtime). Listed one level at a time on S3: RustFS undercounts a
    deep listing of a whole bucket in one request (neo, 2026-10-24)."""
    out: list[tuple[str, int, float]] = []
    if not is_s3(p):
        for d, _, fs_ in os.walk(p):
            for f in fs_:
                q = os.path.join(d, f)
                try:
                    st = os.stat(q)
                except OSError:
                    continue
                out.append((q, st.st_size, st.st_mtime))
        return out
    import pyarrow.fs as pf
    todo = [_k(p)]
    while todo:
        cur = todo.pop()
        for i in _fs().get_file_info(pf.FileSelector(cur, recursive=False, allow_not_found=True)):
            if i.type == pf.FileType.Directory:
                todo.append(i.path)
            elif i.type == pf.FileType.File:
                out.append(("s3://" + i.path, int(i.size or 0), i.mtime.timestamp() if i.mtime else 0.0))
    return sorted(out)


def getsize(p: str) -> int:
    if not is_s3(p):
        return os.path.getsize(p)
    i = _info(p)
    if i.size is None:
        raise FileNotFoundError(p)
    return int(i.size)


def getmtime(p: str) -> float:
    if not is_s3(p):
        return os.path.getmtime(p)
    i = _info(p)
    if i.mtime is None:
        raise FileNotFoundError(p)
    return float(i.mtime.timestamp())


def read_bytes(p: str, start: int = 0, length: int | None = None) -> bytes:
    if not is_s3(p):
        with open(p, "rb") as f:
            f.seek(start)
            return f.read() if length is None else f.read(length)
    with _fs().open_input_file(_k(p)) as f:
        f.seek(start)
        return bytes(f.read() if length is None else f.read(length))


def read_text(p: str) -> str:
    return read_bytes(p).decode("utf-8", "replace")


def read_json(p: str) -> Any:
    return json.loads(read_bytes(p))


# ---- writing --------------------------------------------------------------------------------------------------

def makedirs(p: str) -> None:
    """A folder on a disk; nothing on S3, where a prefix exists once something is under it."""
    if not is_s3(p):
        os.makedirs(p, exist_ok=True)


def write_bytes(p: str, data: bytes, mode: int = 0o644) -> None:
    """Whole, never half: a temp file and a rename on a disk; one PUT on S3 (atomic there)."""
    if not is_s3(p):
        os.makedirs(os.path.dirname(p) or ".", exist_ok=True)
        tmp = f"{p}.tmp-{os.getpid()}-{threading.get_ident()}"
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, mode)
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        os.replace(tmp, p)
        return
    with _fs().open_output_stream(_k(p)) as f:
        f.write(data)
    _forget(p)


def write_text(p: str, text: str, mode: int = 0o644) -> None:
    write_bytes(p, text.encode("utf-8"), mode)


def write_json(p: str, value: Any, mode: int = 0o644, **kw: Any) -> None:
    write_text(p, json.dumps(value, ensure_ascii=False, **kw), mode)


def remove(p: str) -> None:
    if not is_s3(p):
        os.remove(p)
        return
    _fs().delete_file(_k(p))
    _forget(p)


def rmtree(p: str) -> None:
    if not is_s3(p):
        import shutil
        shutil.rmtree(p, ignore_errors=True)
        return
    for q, _, _ in files(p):
        try:
            _fs().delete_file(_k(q))
        except OSError:
            pass


def replace(src: str, dst: str) -> None:
    """os.replace; on S3 a copy and a delete (a reader may see both for a moment, never neither)."""
    if not is_s3(src) and not is_s3(dst):
        os.replace(src, dst)
        return
    write_bytes(dst, read_bytes(src))
    remove(src)


# ---- logs: appending ------------------------------------------------------------------------------------------

def append_line(p: str, line: str, mode: int = 0o600) -> None:
    """One line at the end of a log. A disk: O_APPEND, one write (appends from several writers never interleave).
    S3: one object <p>.d/<ns>-<host>-<pid>-<n>.jsonl."""
    data = (line.rstrip("\n") + "\n").encode()
    if not is_s3(p):
        os.makedirs(os.path.dirname(p) or ".", exist_ok=True)
        fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_APPEND, mode)
        try:
            os.write(fd, data)
        finally:
            os.close(fd)
        return
    name = f"{time.time_ns():020d}-{socket.gethostname().split('.')[0]}-{os.getpid()}-{threading.get_ident() % 100000}.jsonl"
    write_bytes(f"{p}.d/{name}", data)


def _segments(p: str) -> list[str]:
    return [os.path.join(f"{p}.d", n) for n in listdir(f"{p}.d") if n.endswith(".jsonl")]


def read_lines(p: str) -> list[str]:
    """Every line of a log, oldest first. On S3: the file itself (an old log moved up whole), then the segments and
    chunks in name order, a line met twice (a chunk and the segment it replaced, both still listed) kept once."""
    if not is_s3(p):
        try:
            return read_text(p).splitlines()
        except OSError:
            return []
    out: list[str] = []
    if isfile(p):
        out += read_text(p).splitlines()
    seen: set[str] = set()
    for s in _segments(p):
        try:
            text = read_text(s)
        except OSError:      # compacted away between the listing and the read: its lines are in a chunk
            continue
        for line in text.splitlines():
            if line and line not in seen:
                seen.add(line)
                out.append(line)
    return out


def follow(p: str, state: dict[str, Any]) -> tuple[list[str], bool]:
    """The lines added to a log since the last call with this state dict -> (new lines, restarted). A disk log by
    byte offset (a half-written last line waits; a shorter file means it was rewritten: restart); an S3 log by the
    objects not read yet, a line already met (a chunk that rolled up read segments) dropped."""
    if not is_s3(p):
        try:
            size = os.path.getsize(p)
        except OSError:
            return [], False
        off, restarted = int(state.get("off", 0)), False
        if size < off:
            off, restarted = 0, True
        if size == off:
            state["off"] = off
            return [], restarted
        chunk = read_bytes(p, off, size - off)
        end = chunk.rfind(b"\n") + 1
        state["off"] = off + end
        return chunk[:end].decode("utf-8", "replace").splitlines(), restarted
    objs: set[str] = state.setdefault("objs", set())
    seen: set[int] = state.setdefault("seen", set())
    out: list[str] = []
    names = ([p] if p not in objs and isfile(p) else []) + [x for x in _segments(p) if x not in objs]
    for o in names:
        try:
            text = read_text(o)
        except OSError:
            continue
        objs.add(o)
        for line in text.splitlines():
            h = hash(line)
            if line and h not in seen:
                seen.add(h)
                out.append(line)
    return out, False


def tail_lines(p: str, nbytes: int) -> list[str]:
    """The last lines of a log, about nbytes of them (jobs.read and selfknow read a tail)."""
    if not is_s3(p):
        try:
            size = os.path.getsize(p)
        except OSError:
            return []
        data = read_bytes(p, max(0, size - nbytes))
        lines = data.decode("utf-8", "replace").splitlines()
        return lines[1:] if size > nbytes else lines
    lines = read_lines(p)
    out, n = [], 0
    for line in reversed(lines):
        n += len(line) + 1
        if n > nbytes:
            break
        out.append(line)
    return out[::-1]


def log_signature(p: str) -> tuple[object, ...]:
    """Changes whenever a line is added: size and mtime on a disk, the segment names on S3."""
    if not is_s3(p):
        try:
            st = os.stat(p)
            return (st.st_size, st.st_mtime)
        except OSError:
            return (0, 0)
    segs = _segments(p)
    return (len(segs), segs[-1] if segs else "", isfile(p))


def compact(p: str, older_than: float = 120.0, keep_last: int = 0) -> int:
    """S3 only: roll the log's segments older than older_than seconds into one chunk object (named after the first
    segment, so it sorts in its place), then delete them. -> segments rolled. A disk log needs none."""
    if not is_s3(p):
        return 0
    cut = time.time_ns() - int(older_than * 1e9)
    segs = [s for s in _segments(p) if not os.path.basename(s).endswith("-c.jsonl")]
    old = [s for s in segs if int(os.path.basename(s).split("-")[0]) < cut]
    if keep_last:
        old = old[:-keep_last] if len(old) > keep_last else []
    if len(old) < 2:
        return 0
    lines: list[str] = []
    for s in old:
        try:
            lines += read_text(s).splitlines()
        except OSError:
            pass
    first = os.path.basename(old[0]).split("-")[0]
    write_text(f"{p}.d/{first}-{hashlib.sha1(old[-1].encode()).hexdigest()[:8]}-c.jsonl", "\n".join(lines) + "\n")
    for s in old:
        try:
            remove(s)
        except OSError:
            pass
    return len(old)


# ---- caches, engines ------------------------------------------------------------------------------------------

def cache_dir(root: str, *parts: str) -> str:
    """Where a hub keeps what it can rebuild: <root>/index/... on a disk; a local folder for an S3 root
    (RELIC5_CACHE, default ~/.cache/relic5/<the root's hash>)."""
    if not is_s3(root):
        d = os.path.join(root, *parts)
    else:
        base = os.environ.get("RELIC5_CACHE") or os.path.join(os.path.expanduser("~/.cache/relic5"), hashlib.sha1(root.encode()).hexdigest()[:12])
        d = os.path.join(base, *parts)
    os.makedirs(d, exist_ok=True)
    return d


def duck(con: "duckdb.DuckDBPyConnection", root: str | None = None) -> "duckdb.DuckDBPyConnection":
    """Let a DuckDB connection read s3:// paths (httpfs, a secret for the endpoint). Nothing for a local root."""
    if root is not None and not is_s3(root):
        return con
    c = s3_config()
    if not c["access_key"]:
        return con
    try:
        con.execute("LOAD httpfs")
    except Exception:
        con.execute("INSTALL httpfs")
        con.execute("LOAD httpfs")
    def q(v: str) -> str:
        return "'" + v.replace("'", "''") + "'"
    con.execute(f"CREATE OR REPLACE SECRET relic5_s3 (TYPE S3, KEY_ID {q(c['access_key'])}, SECRET {q(c['secret_key'])}, "
                f"ENDPOINT {q(c['host'])}, REGION {q(c['region'])}, URL_STYLE 'path', USE_SSL {'true' if c['scheme'] == 'https' else 'false'})")
    return con


def lance_options(p: str) -> dict[str, str] | None:
    """storage_options for lancedb.connect / lance on an s3:// path; None for a local one."""
    if not is_s3(p):
        return None
    c = s3_config()
    return {"aws_access_key_id": c["access_key"], "aws_secret_access_key": c["secret_key"], "aws_endpoint": c["endpoint"],
            "aws_region": c["region"], "allow_http": "true" if c["scheme"] == "http" else "false",
            "aws_virtual_hosted_style_request": "false"}


def lancedb_connect(p: str) -> Any:
    import lancedb
    opts = lance_options(p)
    return lancedb.connect(p, storage_options=opts) if opts else lancedb.connect(p)


def open_input(p: str) -> Any:
    """A readable binary file object (pyarrow.parquet.read_table and the like take it)."""
    if not is_s3(p):
        return open(p, "rb")
    return _fs().open_input_file(_k(p))


def bytes_io(p: str) -> io.BytesIO:
    return io.BytesIO(read_bytes(p))


# ---- patterns, trees, parquet ---------------------------------------------------------------------------------

def glob(pattern: str) -> list[str]:
    """Paths matching a pattern whose wildcards stay inside one path part each (parts/*/meta/vaults.json), on a disk
    or in a bucket."""
    import fnmatch
    if not is_s3(pattern):
        import glob as g
        return sorted(g.glob(pattern))
    head = pattern.split("*")[0].split("?")[0].split("[")[0]
    base = head.rsplit("/", 1)[0]
    depth = pattern.count("/")
    return sorted(p for p, _, _ in files(base) if p.count("/") == depth and fnmatch.fnmatchcase(p, pattern))


def walk(p: str) -> list[tuple[str, list[str], list[str]]]:
    """os.walk's (folder, [], files) for every folder under p that holds a file, folders in order."""
    if not is_s3(p):
        return [(d, sub, fs_) for d, sub, fs_ in os.walk(p)]
    by: dict[str, list[str]] = {}
    for q, _, _ in files(p):
        d, n = q.rsplit("/", 1)
        by.setdefault(d, []).append(n)
    return [(d, [], sorted(by[d])) for d in sorted(by)]


def read_parquet(p: str, columns: list[str] | None = None) -> Any:
    import pyarrow.parquet as pq
    if not is_s3(p):
        return pq.read_table(p, columns=columns)
    return pq.read_table(_k(p), columns=columns, filesystem=_fs())


def write_parquet(table: Any, p: str) -> None:
    """A parquet file, whole or not at all: a temp file and a rename on a disk, one upload on S3."""
    import pyarrow.parquet as pq
    if not is_s3(p):
        os.makedirs(os.path.dirname(p) or ".", exist_ok=True)
        pq.write_table(table, p + ".tmp")
        os.replace(p + ".tmp", p)
        return
    pq.write_table(table, _k(p), filesystem=_fs())
    _forget(p)
