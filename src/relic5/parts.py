"""parts.py: what every machine pushed, by month, and the per-month manifest.

  <root>/parts/<machine>/<stream>/YYYY-MM.parquet   stream = text | thinking | tools  (relic-extract, one file a month)
  <root>/parts/<machine>/vault/notes.parquet        the oracles' ψ notes (relic-extract report/vaults.py; experimental)
  <root>/parts/<machine>/meta/sessions.parquet      relic-scan's session table (repo, tier, parent, first/last ts)
  <root>/index/YYYY-MM/manifest.json                written by `relic5 index`: files, rows before and after the fold

The month is relic3's week, made a month: one partition per Bangkok month (YYYY-MM, the month relic-scan and
relic-extract write). Months before the current Bangkok month are sealed; the current one is open. A manifest is
written to a temp name and renamed, so a reader never sees half of one.

The fold: the same message pushed by two machines is one row. Rows fold on (msgkey, chunk); the first machine by
name gives the row, and `machines` lists every machine that sent it.
"""
import json, os, re, time
from collections.abc import Callable, Collection

from . import store as rfs
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

from .types_ import Json

if TYPE_CHECKING:   # for annotations only: importing parts.py does not load duckdb
    import duckdb

MONTH_STREAMS = ("text", "thinking", "tools")
STREAMS = MONTH_STREAMS + ("vault",)
MACHINE = re.compile(r"^[a-z0-9-]+$")
MONTH = re.compile(r"^(\d{4}-\d{2}|undated)$")
BKK = timezone(timedelta(hours=7))

PartFile = tuple[str, str | None, str]
"""(machine, month, path) of one part file; month None for the vault."""
FileSig = dict[str, dict[str, list[int]]]
"""{stream: {machine: [bytes, mtime]}} of one month."""


def this_month(now: datetime | None = None) -> str:
    from .window import utcnow
    return (now or utcnow()).astimezone(BKK).strftime("%Y-%m")


def sql_list(files: list[str]) -> str:
    return "[" + ", ".join("'" + f.replace("'", "''") + "'" for f in files) + "]"


class Parts:
    """The parts on a disk or in an S3 bucket (store.py). One listing of parts/ answers machines(), files() and every
    size and mtime, kept a few seconds (on S3 each listing is a round trip; a disk listing is cheap but the same)."""
    TTL = {"s3": 15.0, "disk": 0.0}

    def __init__(self, root: str) -> None:
        self.root = rfs.root_of(root)
        self.dir = os.path.join(self.root, "parts")
        self.index_dir = os.path.join(self.root, "index")
        self._snap: tuple[float, dict[str, tuple[int, float]]] = (0.0, {})

    def stat_all(self, fresh: bool = False) -> dict[str, tuple[int, float]]:
        """{path: (bytes, mtime)} of every file under parts/ (one listing, cached TTL seconds)."""
        ttl = self.TTL["s3" if rfs.is_s3(self.root) else "disk"]
        if fresh or time.time() - self._snap[0] > ttl:
            self._snap = (time.time(), {p: (n, m) for p, n, m in rfs.files(self.dir)} if rfs.isdir(self.dir) else {})
        return self._snap[1]

    def stat(self, p: str) -> tuple[int, float]:
        got = self.stat_all().get(p)
        return got if got is not None else (rfs.getsize(p), rfs.getmtime(p))

    def machines(self) -> list[str]:
        base = self.dir.rstrip("/") + "/"
        return sorted({p[len(base):].split("/")[0] for p in self.stat_all() if p.startswith(base) and MACHINE.match(p[len(base):].split("/")[0])})

    def files(self, stream: str, month: str | None = None, machine: str | None = None) -> list[PartFile]:
        """[(machine, month, path)] of one stream; vault is one file, month None. Hidden and .part files never count."""
        out: list[PartFile] = []
        base = self.dir.rstrip("/") + "/"
        for p in sorted(self.stat_all()):
            rel = p[len(base):].split("/")
            if len(rel) != 3 or rel[1] != stream or not MACHINE.match(rel[0]) or (machine and rel[0] != machine):
                continue
            f = rel[2]
            if f.startswith(".") or not f.endswith(".parquet"):
                continue
            mon = f[:-8] if MONTH.match(f[:-8]) else None
            if stream in MONTH_STREAMS and mon is None:
                continue
            if month and mon != month:
                continue
            out.append((rel[0], mon, p))
        return out

    def months(self) -> list[str]:
        return sorted({mon for s in MONTH_STREAMS for _, mon, _ in self.files(s) if mon is not None})   # never None for a month stream

    def meta(self) -> list[str]:
        have = self.stat_all()
        return [p for m in self.machines() if (p := os.path.join(self.dir, m, "meta", "sessions.parquet")) in have]

    def source(self, stream: str, month: str | None = None, machine: str | None = None,
               months: Collection[str] | None = None) -> str | None:
        """SQL for every row of a stream with its machine, or None when nothing was pushed."""
        got = [f for f in self.files(stream, month, machine) if months is None or f[1] in months]
        if not got:
            return None
        return (f"(SELECT regexp_extract(filename, '/parts/([^/]+)/', 1) AS machine, * EXCLUDE (filename) "
                f"FROM read_parquet({sql_list([p for _, _, p in got])}, union_by_name = true, filename = true))")

    # ---- manifest ----
    def manifest_path(self, month: str) -> str:
        return os.path.join(self.index_dir, month, "manifest.json")

    def build_manifest(self, con: "duckdb.DuckDBPyConnection", month: str, now: datetime | None = None) -> Json:
        """Count one month: per stream and machine, files and rows; and the rows after the fold."""
        man: Json = {"month": month, "sealed": month != "undated" and month < this_month(now), "built": time.strftime("%FT%T%z"),
               "streams": {}}
        for s in MONTH_STREAMS:
            files_ = self.files(s, month)
            if not files_:
                continue
            src = self.source(s, month)
            per: dict[str, Json] = {m: {"rows": n, "newest_ts": ts} for m, n, ts in
                   con.execute(f"SELECT machine, count(*), max(ts) FROM {src} GROUP BY machine").fetchall()}
            for m, _, p in files_:
                size, mtime = self.stat(p)
                per.setdefault(m, {}).update(bytes=size, mtime=int(mtime))
            row = con.execute(f"SELECT count(*) FROM (SELECT DISTINCT msgkey, chunk FROM {src})").fetchone()
            assert row is not None   # count(*) always answers one row
            folded = row[0]
            man["streams"][s] = {"rows": folded, "machines": per}
        return man

    def file_sig(self, mon: str) -> FileSig:
        """{stream: {machine: [bytes, mtime]}} of one month as it is on disk now."""
        out: FileSig = {}
        for s in MONTH_STREAMS:
            for m, _, f in self.files(s, mon):
                size, mtime = self.stat(f)
                out.setdefault(s, {})[m] = [size, int(mtime)]
        return out

    def recorded_sig(self, mon: str) -> FileSig | None:
        """The same, as the month's manifest recorded it (None when there is no manifest)."""
        p = self.manifest_path(mon)
        try:
            st = rfs.read_json(p)["streams"]
        except (OSError, ValueError, KeyError):
            return None
        return {s: {m: [v.get("bytes"), v.get("mtime")] for m, v in st[s]["machines"].items() if "bytes" in v} for s in st if st[s]["machines"]}

    def changed(self, mon: str) -> bool:
        """A month is stale when any part was added, removed or changed (size or mtime) since its manifest. Not by
        clock order: rsync -a keeps the SENDING machine's mtimes, so a part pushed late can be older than the manifest
        (relic4-scan docs/LEARNED.md:52: compare each file's own size and mtime, never the index's clock)."""
        return self.recorded_sig(mon) != self.file_sig(mon)

    def index(self, con: "duckdb.DuckDBPyConnection", months: list[str] | None = None, log: Callable[[str], object] = print,
              now: datetime | None = None) -> list[str]:
        """Rewrite the manifest of every month whose parts changed since its manifest (or the ones named)."""
        self.stat_all(fresh=True)
        done: list[str] = []
        for mon in months or self.months():
            p = self.manifest_path(mon)
            if months is None and not self.changed(mon):
                continue
            t = time.time()
            man = self.build_manifest(con, mon, now)
            rfs.write_json(p, man, indent=1)
            done.append(mon)
            log(f"index {mon}: " + ", ".join(f"{s} {v['rows']}" for s, v in man["streams"].items()) + f" ({time.time() - t:.1f}s)")
        return done

    def manifests(self) -> dict[str, Json]:
        out: dict[str, Json] = {}
        for mon in self.months():
            try:
                out[mon] = rfs.read_json(self.manifest_path(mon))
            except (OSError, ValueError):
                pass
        return out

    def stale(self) -> list[str]:
        """Months whose parts differ from what their manifest recorded (or have none): `relic5 index` has not seen them."""
        self.stat_all(fresh=True)
        return [mon for mon in self.months() if self.changed(mon)]
