"""hindsight-cancel-ops.py BANK: cancel every pending and processing operation of a bank (a 409 is one already running to its end)."""
import json, sys, urllib.request
bank = sys.argv[1]
H = "http://127.0.0.1:8888/v1/default/banks/" + bank
n = 0
skip = set()
for _ in range(30):
    ops = []
    for s in ("pending", "processing"):
        ops += json.load(urllib.request.urlopen(f"{H}/operations?status={s}&limit=100", timeout=30)).get("operations") or []
    if not ops:
        break
    done = 0
    for o in ops:
        try:
            urllib.request.urlopen(urllib.request.Request(f"{H}/operations/{o['id']}", method="DELETE"), timeout=30)
            n += 1; done += 1
        except urllib.error.HTTPError as ex:
            skip.add(o["id"]) if ex.code == 409 else None
    if not done:
        break
print("cancelled", n, "operations in", bank, "·", len(skip), "could not be cancelled (409: already running to the end)")
