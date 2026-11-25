"""local.py: embedded mode. The CLI and `relic5 mcp` read this machine's store directly when no hub answers (issue #311).

`relic5 serve` holds the whole store warm (DuckDB buffers, open Lance tables, the maps, the page caches) for the web
pages and for other machines. A single machine's own searches do not need that: this module opens the store for
the call, answers through the very functions the hub uses (mcp.call_tool, routes.py), and lets go again.

When:
  RELIC5_LOCAL=1 (or --local)                      always embedded
  otherwise                                        the hub; embedded only when it cannot be reached (refused, timed
                                                   out, no token file) AND a store exists at the root
  neither                                          the hub's error, with the commands that fix it

Root: --root, else RELIC5_ROOT, else storage.json's root (the hub's own choice, mirror.py), else ~/relic5.

What it never does: write. No query log, no trace records, no index seeding, no warm threads. The tools that write the
hub's records (relic_tag, relic_found, relic_saved add/remove, relic_artifact_put, relic_hub_memory set) answer
"needs the hub". Results carry no trace {id, root, parent} for the same reason. Semantic search needs the hub (the
vector matrices are the hub's warm memory): embedded answers it by keyword and says so.

Reader safety against a concurrent `relic5 index`: DuckDB here is an in-memory connection reading parquet files
(no database file, so no lock to take or break); the index publishes a new Lance generation and then renames
current.json last, keeping the newest 3 generations, so a reader holds one whole generation for its call.
"""
import json, os, threading, time
from typing import Any

from .types_ import Json
from . import store as rfs

MEM = os.environ.get("RELIC5_LOCAL_MEM", "1GB")
"""DuckDB's memory_limit for an embedded reader: a cap on its buffer, not a reservation (the hub's default is 6GB)."""
THREADS = int(os.environ.get("RELIC5_LOCAL_THREADS", "4"))
IDLE_S = float(os.environ.get("RELIC5_LOCAL_IDLE", "60"))
"""`relic5 mcp`: close the store after this many seconds with no call, so an idle process is back near its baseline."""
DOOR = "local"

WRITES = {"relic_tag": "tags", "relic_found": "found notes", "relic_artifact_put": "artifacts"}
NEEDS_HUB = ("{what} are the hub's records and embedded mode never writes: start the hub (relic5 serve --root {root}) "
             "or point RELIC5_URL at one")


def forced() -> bool:
    return os.environ.get("RELIC5_LOCAL", "").strip().lower() in ("1", "true", "yes", "on")


def root() -> str:
    r = os.environ.get("RELIC5_ROOT")
    if not r:
        from . import mirror
        r = mirror.config().get("root") or "~/relic5"
    return os.path.expanduser(str(r))


def has_store(r: str | None = None) -> bool:
    """A store a reader can answer from: the published search index, or at least the parts."""
    r = r or root()
    try:
        return rfs.isfile(os.path.join(r, "index", "_search", "current.json")) or rfs.isdir(os.path.join(r, "parts"))
    except Exception:
        return False


def fix_hint(url: str) -> str:
    """The commands that fix "no hub" (fleet rule: every error prints the fixing command)."""
    return (f"  start the hub here:        relic5 serve --root {root()}\n"
            f"  or read a store directly:  export RELIC5_LOCAL=1   (with --root DIR or RELIC5_ROOT if it is not {root()})\n"
            f"  or use another hub:        export RELIC5_URL=http://<host>:8795   (now {url})")


class Reader:
    """One embedded store: opened on the first call, closed after IDLE_S without one (close_idle), or by close()."""

    def __init__(self, root_: str | None = None, mem: str = MEM, threads: int = THREADS) -> None:
        self.root, self.mem, self.threads = root_ or root(), mem, threads
        self._relic: Any = None
        self._con: Any = None
        self._last = 0.0
        self._lock = threading.RLock()

    def relic(self) -> Any:
        with self._lock:
            self._last = time.monotonic()
            if self._relic is None:
                import duckdb
                from .query import Relic5
                import tempfile
                # a spill goes to the system's temp folder, never the store nor the caller's cwd
                self._con = duckdb.connect(":memory:", config={"threads": self.threads, "memory_limit": self.mem,
                                                               "temp_directory": os.path.join(tempfile.gettempdir(), "relic5-local")})
                self._relic = Relic5(self.root, self._con)
            return self._relic

    @property
    def open(self) -> bool:
        return self._relic is not None

    def close(self) -> None:
        with self._lock:
            if self._relic is None:
                return
            self._relic = None
            try:
                self._con.close()
            except Exception:
                pass
            self._con = None
            import gc
            gc.collect()

    def close_idle(self, idle_s: float = IDLE_S) -> bool:
        with self._lock:
            if self._relic is not None and time.monotonic() - self._last >= idle_s:
                self.close()
                return True
        return False

    def keep_closing(self, idle_s: float = IDLE_S) -> threading.Thread:
        """A daemon thread that closes the store once it sits idle (for the long-lived `relic5 mcp`)."""
        def loop() -> None:
            while True:
                time.sleep(max(1.0, idle_s / 4))
                self.close_idle(idle_s)
        t = threading.Thread(target=loop, name="relic5-local-idle", daemon=True)
        t.start()
        return t

    # ---- answers ----
    def tool(self, name: str, args: object) -> tuple[bool, Any]:
        """mcp.call_tool, minus anything that writes; semantic answered by keyword (no embedder, no vector matrices)."""
        from . import mcp
        if name in WRITES or (name == "relic_saved" and isinstance(args, dict) and args.get("action") in ("add", "remove")) \
                or (name == "relic_hub_memory" and isinstance(args, dict) and args.get("set")):
            what = WRITES.get(name) or ("saved searches" if name == "relic_saved" else "the hub's DuckDB memory cap")
            return False, ("unavailable", NEEDS_HUB.format(what=what[0].upper() + what[1:], root=self.root))
        note = None
        if name == "relic_search" and isinstance(args, dict) and args.get("semantic"):
            args = {k: v for k, v in args.items() if k not in ("semantic", "model", "vector", "hybrid", "min_chars")}
            note = "embedded mode (no hub): semantic search needs relic5 serve, these are keyword hits"
        ok, r = mcp.call_tool(self.relic(), name, args, DOOR)
        self._last = time.monotonic()   # idle counts from the end of a call
        if ok and note and isinstance(r, dict):
            r = r | {"note": note + (f" · {r['note']}" if r.get("note") else "")}
        return ok, r

    def get(self, path: str, params: list[tuple[str, str]]) -> tuple[int, Json]:
        """GET <path>?<params> as the hub answers it: (status, body). The body goes through JSON as the hub's does, so
        a datetime is the same string either way."""
        from . import routes
        if path in routes.ROUTES:
            ok, r = self.tool(routes.ROUTES[path], routes.args_of(params))
            status, body = (200, r) if ok else (routes.STATUS_OF[r[0]], {"error": r[1]})
        elif path in routes.GET:
            status, body = _call_typed(routes.GET[path], self, params)
        else:
            status, body = 501, {"error": f"{path} is answered by the hub only (embedded mode serves the CLI's read "
                                          f"routes): start relic5 serve --root {self.root} or set RELIC5_URL"}
        return status, json.loads(json.dumps(body, ensure_ascii=False, default=str))


class Worker:
    """Reader in a child process, for the long-lived `relic5 mcp`: the child holds DuckDB, Lance and their memory pools,
    and is ended after IDLE_S without a call, so the parent goes back to its baseline (a closed in-process Reader
    keeps ~300 MB the allocators never give back, measured on a full store). Same tool() as Reader."""

    def __init__(self, root_: str | None = None) -> None:
        self.root = root_ or root()
        self._p: Any = None
        self._last = 0.0
        self._lock = threading.RLock()

    @property
    def open(self) -> bool:
        return self._p is not None and self._p.poll() is None

    def tool(self, name: str, args: object) -> tuple[bool, Any]:
        import subprocess, sys
        with self._lock:
            self._last = time.monotonic()
            for attempt in (1, 2):   # a child that died (killed, crashed) is started again once
                if not self.open:
                    self._p = subprocess.Popen([sys.executable, "-m", "relic5.cli", "local-worker"], stdin=subprocess.PIPE,
                                               stdout=subprocess.PIPE, text=True, env=dict(os.environ, RELIC5_ROOT=self.root))
                try:
                    self._p.stdin.write(json.dumps({"name": name, "args": args}, ensure_ascii=False) + "\n")
                    self._p.stdin.flush()
                    line = self._p.stdout.readline()
                    self._last = time.monotonic()   # idle counts from the end of a call: a slow cold call is not idle time
                    if line:
                        ok, r = json.loads(line)
                        return bool(ok), r
                except (BrokenPipeError, OSError, ValueError):
                    pass
                self.close()
            return False, ("failed", "the embedded reader stopped (see stderr)")

    def close(self) -> None:
        with self._lock:
            if self._p is not None:
                try:
                    self._p.kill()
                    self._p.wait(5)
                except Exception:
                    pass
                self._p = None

    def close_idle(self, idle_s: float = IDLE_S) -> bool:
        with self._lock:
            if self.open and time.monotonic() - self._last >= idle_s:
                self.close()
                return True
        return False

    def keep_closing(self, idle_s: float = IDLE_S) -> threading.Thread:
        """A daemon thread that ends the child once it sits idle."""
        def loop() -> None:
            while True:
                time.sleep(max(1.0, idle_s / 4))
                self.close_idle(idle_s)
        t = threading.Thread(target=loop, name="relic5-local-idle", daemon=True)
        t.start()
        return t


def worker_main() -> None:
    """`relic5-core local-worker`: one {"name", "args"} per line on stdin -> [ok, result] per line on stdout."""
    import sys
    rd = Reader()
    for line in sys.stdin:
        try:
            m = json.loads(line)
            ok, r = rd.tool(m["name"], m.get("args") or {})
        except Exception as ex:
            ok, r = False, ("failed", f"{type(ex).__name__}: {ex}")
        sys.stdout.write(json.dumps([ok, r], ensure_ascii=False, default=str) + "\n")
        sys.stdout.flush()


def _call_typed(fn: Any, reader: Reader, params: list[tuple[str, str]]) -> tuple[int, Json]:
    """Call a routes.py function with query-string values coerced to its parameter types, as FastAPI does (the last
    value wins; a missing required one or a bad int is a 422, FastAPI's status for both)."""
    import inspect
    sig = inspect.signature(fn)
    kw: dict[str, Any] = {}
    given = dict(params)
    for name, p in list(sig.parameters.items())[1:]:
        if name not in given:
            if p.default is inspect.Parameter.empty:
                return 422, {"error": f"missing query parameter {name!r}"}
            continue
        v = given[name]
        if p.annotation in (int, "int"):
            try:
                kw[name] = int(v)
            except ValueError:
                return 422, {"error": f"{name} must be an integer, not {v!r}"}
        else:
            kw[name] = v
    out: tuple[int, Json] = fn(reader.relic(), **kw)
    return out


def error_text(body: Json) -> str:
    """An error body as the hub's JSONResponse writes it (Starlette: compact separators, UTF-8)."""
    return json.dumps(body, ensure_ascii=False, separators=(",", ":"))
