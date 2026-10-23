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
from datetime import datetime, timedelta, timezone

MONTH_STREAMS = ("text", "thinking", "tools")
STREAMS = MONTH_STREAMS + ("vault",)
MACHINE = re.compile(r"^[a-z0-9-]+$")
MONTH = re.compile(r"^(\d{4}-\d{2}|undated)$")
BKK = timezone(timedelta(hours=7))


def this_month(now=None):
    return (now or datetime.now(timezone.utc)).astimezone(BKK).strftime("%Y-%m")


def sql_list(files):
    return "[" + ", ".join("'" + f.replace("'", "''") + "'" for f in files) + "]"


class Parts:
    def __init__(self, root):
        self.root = os.path.abspath(os.path.expanduser(root))
        self.dir = os.path.join(self.root, "parts")
        self.index_dir = os.path.join(self.root, "index")

    def machines(self):
        if not os.path.isdir(self.dir):
            return []
        return sorted(m for m in os.listdir(self.dir) if MACHINE.match(m) and os.path.isdir(os.path.join(self.dir, m)))

    def files(self, stream, month=None, machine=None):
        """[(machine, month, path)] of one stream; vault is one file, month None. Hidden and .part files never count."""
        out = []
        for m in ([machine] if machine else self.machines()):
            d = os.path.join(self.dir, m, stream)
            if not os.path.isdir(d):
                continue
            for f in sorted(os.listdir(d)):
                if f.startswith(".") or not f.endswith(".parquet"):
                    continue
                mon = f[:-8] if MONTH.match(f[:-8]) else None
                if stream in MONTH_STREAMS and mon is None:
                    continue
                if month and mon != month:
                    continue
                out.append((m, mon, os.path.join(d, f)))
        return out

    def months(self):
        return sorted({mon for s in MONTH_STREAMS for _, mon, _ in self.files(s)})

    def meta(self):
        return [p for m in self.machines() if os.path.isfile(p := os.path.join(self.dir, m, "meta", "sessions.parquet"))]

    def source(self, stream, month=None, machine=None, months=None):
        """SQL for every row of a stream with its machine, or None when nothing was pushed."""
        fs = [f for f in self.files(stream, month, machine) if months is None or f[1] in months]
        if not fs:
            return None
        return (f"(SELECT regexp_extract(filename, '/parts/([^/]+)/', 1) AS machine, * EXCLUDE (filename) "
                f"FROM read_parquet({sql_list([p for _, _, p in fs])}, union_by_name = true, filename = true))")

    # ---- manifest ----
    def manifest_path(self, month):
        return os.path.join(self.index_dir, month, "manifest.json")

    def build_manifest(self, con, month, now=None):
        """Count one month: per stream and machine, files and rows; and the rows after the fold."""
        man = {"month": month, "sealed": month != "undated" and month < this_month(now), "built": time.strftime("%FT%T%z"),
               "streams": {}}
        for s in MONTH_STREAMS:
            fs = self.files(s, month)
            if not fs:
                continue
            src = self.source(s, month)
            per = {m: {"rows": n, "newest_ts": ts} for m, n, ts in
                   con.execute(f"SELECT machine, count(*), max(ts) FROM {src} GROUP BY machine").fetchall()}
            for m, _, p in fs:
                st = os.stat(p)
                per.setdefault(m, {}).update(bytes=st.st_size, mtime=int(st.st_mtime))
            folded = con.execute(f"SELECT count(*) FROM (SELECT DISTINCT msgkey, chunk FROM {src})").fetchone()[0]
            man["streams"][s] = {"rows": folded, "machines": per}
        return man

    def index(self, con, months=None, log=print, now=None):
        """Rewrite the manifest of every month whose parts changed since its manifest (or the ones named)."""
        done = []
        for mon in months or self.months():
            p = self.manifest_path(mon)
            newest = max((os.path.getmtime(f) for s in MONTH_STREAMS for _, _, f in self.files(s, mon)), default=0)
            if months is None and os.path.exists(p) and os.path.getmtime(p) >= newest:
                continue
            t = time.time()
            man = self.build_manifest(con, mon, now)
            os.makedirs(os.path.dirname(p), exist_ok=True)
            tmp = p + ".tmp"
            with open(tmp, "w") as f:
                json.dump(man, f, indent=1)
            os.replace(tmp, p)
            done.append(mon)
            log(f"index {mon}: " + ", ".join(f"{s} {v['rows']}" for s, v in man["streams"].items()) + f" ({time.time() - t:.1f}s)")
        return done

    def manifests(self):
        out = {}
        for mon in self.months():
            p = self.manifest_path(mon)
            if os.path.exists(p):
                out[mon] = json.load(open(p))
        return out

    def stale(self):
        """Months whose parts are newer than their manifest (or have none): `relic5 index` has not seen them."""
        out = []
        for mon in self.months():
            p = self.manifest_path(mon)
            newest = max((os.path.getmtime(f) for s in MONTH_STREAMS for _, _, f in self.files(s, mon)), default=0)
            if not os.path.exists(p) or os.path.getmtime(p) < newest:
                out.append(mon)
        return out
