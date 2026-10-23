"""gc.py: `relic5 gc`, what could be reclaimed on the hub. A DRY RUN ONLY, as relic3's gc ("--apply does not exist yet"):
it deletes nothing. Fleet rule: nothing is deleted without a backup, so an attic item is only "safe" when another copy
of it is named (relic3-import: relic3's own index on m5; an import is rebuilt from its source).

  generations   index/_search/<gen>/ not named by current.json (kept: the newest 3 by age, or still live)
  attic         ~/relic5/attic/<item>: moved there instead of deleted; which other copy exists
  logs          logs/*.jsonl sizes (queries, jobs, eval, sizes)
"""
import json, os

from .fts import current, search_dir
from .selfknow import _du

OTHER_COPY = {"relic3-import": "relic3's own index (m5 ~/.relic3-hub/index) + `relic5 import relic3`",
              "jsonl-truth-import": "~/jsonl-truth on m5 + `relic5 import jsonl-truth`"}


def report(root):
    sd = search_dir(root)
    live = {v.split("/")[0] for v in current(root).values()}
    gens = []
    for d in sorted(os.listdir(sd)) if os.path.isdir(sd) else []:
        p = os.path.join(sd, d)
        if os.path.isdir(p) and d[:8].isdigit():
            gens.append({"gen": d, "bytes": _du(p), "live": d in live, "mtime": int(os.path.getmtime(p))})
    attic = []
    ad = os.path.join(root, "attic")
    for d in sorted(os.listdir(ad)) if os.path.isdir(ad) else []:
        other = next((v for k, v in OTHER_COPY.items() if d.startswith(k)), None)
        attic.append({"item": d, "bytes": _du(os.path.join(ad, d)), "other_copy": other, "safe": other is not None})
    logs = {f: os.path.getsize(os.path.join(root, "logs", f)) for f in sorted(os.listdir(os.path.join(root, "logs")))} \
        if os.path.isdir(os.path.join(root, "logs")) else {}
    reclaim = sum(g["bytes"] for g in gens if not g["live"]) + sum(a["bytes"] for a in attic if a["safe"])
    return {"generations": gens, "attic": attic, "logs": logs, "reclaimable_bytes": reclaim, "dry_run": True}
