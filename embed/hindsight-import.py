#!/usr/bin/env python3
"""hindsight-import.py: feed one relic5 source into Hindsight from m5, paced and resumable.

  python3 embed/hindsight-import.py memory|vault|git|thinking [--bank relic5] [--max-pending 40] [--batch 40]
  relic5 memory import --source memory      # the same, from the CLI

It runs embed/hindsight-source.py on the hub (ssh white, the hub venv's python), reads its JSON lines (newest first),
skips every document already queued (ledger ~/.cache/relic5/hindsight-<bank>-<source>.done), and posts async batches
to the hindsight-embed daemon while its queue stays under --max-pending operations, so a long run never floods the
database. One progress line a minute: queued / total, documents in the bank, blocks a minute, ETA. Stop it any time;
the next run picks up after the last queued batch. Stdlib only.
"""
import argparse, json, os, subprocess, sys, time, urllib.error, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
HUB = os.environ.get("RELIC5_HUB_SSH", "nat@white.follow-rankine.ts.net")
HS = os.environ.get("HINDSIGHT_URL", "http://127.0.0.1:8888").rstrip("/")


def call(method: str, path: str, body: object | None = None, timeout: float = 60) -> dict:
    req = urllib.request.Request(HS + path, json.dumps(body).encode() if body is not None else None,
                                 {"Content-Type": "application/json"}, method=method)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def stats(bank: str) -> dict:
    return call("GET", f"/v1/default/banks/{bank}/stats", timeout=30)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("source", choices=["memory", "vault", "git", "thinking"])
    ap.add_argument("--bank", default="relic5")
    ap.add_argument("--max-pending", type=int, default=40, help="hold back while the bank has this many open operations")
    ap.add_argument("--batch", type=int, default=40)
    a = ap.parse_args()

    ledger_path = os.path.expanduser(f"~/.cache/relic5/hindsight-{a.bank}-{a.source}.done")
    os.makedirs(os.path.dirname(ledger_path), exist_ok=True)
    done = set(open(ledger_path).read().split("\n")) if os.path.exists(ledger_path) else set()
    done.discard("")
    ledger = open(ledger_path, "a")

    print(f"{a.source}: reading the hub ({HUB}) …", flush=True)
    with open(os.path.join(HERE, "hindsight-source.py"), "rb") as src:
        p = subprocess.run(["ssh", "-o", "BatchMode=yes", HUB, f"~/relic5/app/.venv/bin/python - {a.source}"],
                           stdin=src, capture_output=True, check=True)
    items = [json.loads(l) for l in p.stdout.decode("utf-8").splitlines() if l.strip()]
    todo = [x for x in items if x["document_id"] not in done]
    blocks = sum(max(1, len(x["content"]) // 3000) for x in todo)
    print(f"{a.source}: {len(items):,} items on the hub, {len(items) - len(todo):,} already queued, {len(todo):,} to go "
          f"(~{blocks:,} blocks)", flush=True)

    t0, last_print, sent = time.time(), 0.0, 0
    docs0 = stats(a.bank).get("total_documents", 0)
    i = 0
    while i < len(todo):
        st = stats(a.bank)
        if st.get("pending_operations", 0) >= a.max_pending:
            time.sleep(5)
        else:
            batch = todo[i:i + a.batch]
            items_ = [{k: v for k, v in x.items() if v is not None} for x in batch]
            try:
                call("POST", f"/v1/default/banks/{a.bank}/memories", {"items": items_, "async": True}, timeout=120)
            except (urllib.error.URLError, OSError) as ex:
                print(f"{a.source}: post failed ({ex}); retrying in 30 s", flush=True)
                time.sleep(30)
                continue
            for x in batch:
                ledger.write(x["document_id"] + "\n")
            ledger.flush()
            sent += len(batch)
            i += len(batch)
        if time.time() - last_print >= 60 or i >= len(todo):
            last_print = time.time()
            st = stats(a.bank)
            mins = (time.time() - t0) / 60
            made = st.get("total_documents", 0) - docs0
            rate = made / mins if mins > 0.5 else 0
            left_docs = len(todo) - made
            eta = f"{left_docs / rate / 60:.1f} h" if rate > 0 else "measuring"
            print(f"{time.strftime('%H:%M')} {a.source}: queued {i:,}/{len(todo):,} · bank {st.get('total_documents', 0):,} docs, "
                  f"{st.get('total_nodes', 0):,} memories · open ops {st.get('pending_operations', 0)} · "
                  f"{rate:.0f} docs/min · ETA {eta}", flush=True)
    print(f"{a.source}: all {len(todo):,} queued; the bank finishes the queue on its own (relic5 memory status)", flush=True)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
