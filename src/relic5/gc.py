"""gc.py: `relic5 gc`, what could be reclaimed on the hub. A DRY RUN ONLY, as relic3's gc ("--apply does not exist yet"):
it deletes nothing. Fleet rule: nothing is deleted without a backup, so an attic item is only "safe" when another copy
of it is named (relic3-import: relic3's own index on m5; an import is rebuilt from its source).

  generations   index/_search/<gen>/ not named by current.json (kept: the newest 3 by age, or still live)
  attic         ~/relic5/attic/<item>: moved there instead of deleted; which other copy exists
  logs          logs/*.jsonl sizes (queries, jobs, eval, sizes)
"""
import json, os, subprocess
from typing import TypedDict

from .fts import current, search_dir
from .selfknow import _du
from .types_ import Json

# Big neighbours on the hub's disk that are NOT relic5's: reported so the disk warning says where the space is, never
# touched (relic4-scan, 2026-10-24). Paths are relative to the hub user's home.
NOT_OURS = {".relic3-gens": "relic3's index generations (hub/indexer.sh, still publishing)"}

OTHER_COPY = {"relic3-import": "relic3's own index (m5 ~/.relic3-hub/index) + `relic5 import relic3`",
              "jsonl-truth-import": "~/jsonl-truth on m5 + `relic5 import jsonl-truth`"}


class Generation(TypedDict):
    gen: str
    bytes: int
    live: bool
    mtime: int


class AtticItem(TypedDict):
    item: str
    bytes: int
    other_copy: str | None
    safe: bool


class NotOurs(TypedDict):
    what: str
    about: str
    bytes: int | None


def report(root: str) -> Json:
    sd = search_dir(root)
    live = {v.split("/")[0] for v in current(root).values()}
    gens: list[Generation] = []
    for d in sorted(os.listdir(sd)) if os.path.isdir(sd) else []:
        p = os.path.join(sd, d)
        if os.path.isdir(p) and d[:8].isdigit():
            gens.append({"gen": d, "bytes": _du(p), "live": d in live, "mtime": int(os.path.getmtime(p))})
    attic: list[AtticItem] = []
    ad = os.path.join(root, "attic")
    for d in sorted(os.listdir(ad)) if os.path.isdir(ad) else []:
        other = next((v for k, v in OTHER_COPY.items() if d.startswith(k)), None)
        attic.append({"item": d, "bytes": _du(os.path.join(ad, d)), "other_copy": other, "safe": other is not None})
    logs = {f: os.path.getsize(os.path.join(root, "logs", f)) for f in sorted(os.listdir(os.path.join(root, "logs")))} \
        if os.path.isdir(os.path.join(root, "logs")) else {}
    reclaim = sum(g["bytes"] for g in gens if not g["live"]) + sum(a["bytes"] for a in attic if a["safe"])
    return {"generations": gens, "attic": attic, "logs": logs, "reclaimable_bytes": reclaim, "dry_run": True,
            "not_ours": not_ours()}


def not_ours(home: str | None = None) -> list[NotOurs]:
    """Sizes of what else fills the disk: relic3's generations, Docker's reclaimable space. For Nat to decide."""
    home = home or os.path.expanduser("~")
    out: list[NotOurs] = []
    for rel, what in NOT_OURS.items():
        p = os.path.join(home, rel)
        if os.path.isdir(p):
            out.append({"what": f"~/{rel}", "about": what, "bytes": _du(p)})
    try:
        r = subprocess.run(["docker", "system", "df", "--format", "{{json .}}"], capture_output=True, text=True, timeout=60)
        for line in r.stdout.splitlines():
            d = json.loads(line)
            out.append({"what": f"docker {d.get('Type')}", "about": f"size {d.get('Size')}, reclaimable {d.get('Reclaimable')}", "bytes": None})
    except (OSError, ValueError, subprocess.TimeoutExpired):
        pass
    return out + builders()


def builders() -> list[NotOurs]:
    """Build cache per buildx builder. The current one (marked * by `docker buildx ls`) is where `docker compose build`
    lands, relic5's `just up` included; on white that is "mybuilder", shared with other builds (2026-10-24)."""
    out: list[NotOurs] = []
    try:
        ls = subprocess.run(["docker", "buildx", "ls"], capture_output=True, text=True, timeout=30).stdout
        names = [(ln.split()[0].rstrip("*"), ln.split()[0].endswith("*")) for ln in ls.splitlines()[1:]
                 if ln.strip() and not ln.startswith((" ", "\t")) and not ln.lstrip().startswith("\\_")]
        for name, cur in names:
            du = subprocess.run(["docker", "buildx", "du", "--builder", name], capture_output=True, text=True, timeout=60).stdout
            total = next((ln.split(":", 1)[1].strip() for ln in du.splitlines() if ln.startswith("Total:")), "unknown")
            about = f"build cache {total}" + (" · current builder: relic5's compose builds land here" if cur else "")
            out.append({"what": f"buildx builder {name}", "about": about, "bytes": None})
    except (OSError, subprocess.TimeoutExpired):
        pass
    return out
