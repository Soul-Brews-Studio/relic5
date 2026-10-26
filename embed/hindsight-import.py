#!/usr/bin/env python3
"""hindsight-import.py: feed one relic5 source into Hindsight from m5, paced and resumable.

  python3 embed/hindsight-import.py memory|vault|git|thinking [--bank relic5] [--max-pending 40] [--batch 40]
  relic5 memory import --source memory      # the same, from the CLI

It runs embed/hindsight-source.py on the hub (ssh white, the hub venv's python), reads its JSON lines (newest first),
skips every document already queued (ledger ~/.cache/relic5/hindsight-<bank>-<source>.done), and posts async batches
to the hindsight-embed daemon while its queue stays under --max-pending operations, so a long run never floods the
database. One progress line a minute: queued / total, documents in the bank, blocks a minute, ETA. Stop it any time;
the next run picks up after the last queued batch. Pacing is on this run's own count (items sent minus documents
created), since the bank's pending count lags an async post. Stdlib only.
"""
import argparse, json, os, subprocess, sys, threading, time, urllib.error, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
HUB = os.environ.get("RELIC5_HUB_SSH", "nat@white.follow-rankine.ts.net")
HS = os.environ.get("HINDSIGHT_URL", "http://127.0.0.1:8888").rstrip("/")


def call(method: str, path: str, body: object | None = None, timeout: float = 60) -> dict:
    req = urllib.request.Request(HS + path, json.dumps(body).encode() if body is not None else None,
                                 {"Content-Type": "application/json"}, method=method)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def stats(bank: str) -> dict:
    """the bank's stats; waits out a daemon restart instead of ending the run"""
    while True:
        try:
            return call("GET", f"/v1/default/banks/{bank}/stats", timeout=30)
        except (urllib.error.URLError, OSError, ValueError) as ex:
            print(f"hindsight not answering ({ex}); retrying in 15 s", flush=True)
            time.sleep(15)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("source", choices=["memory", "vault", "git", "thinking"])
    ap.add_argument("--bank", default="relic5")
    ap.add_argument("--max-pending", type=int, default=40, help="hold back while the bank has this many open operations")
    ap.add_argument("--max-inflight", type=int, default=600,
                    help="hold back while this many items sent here are not yet documents in the bank")
    ap.add_argument("--batch", type=int, default=40)
    a = ap.parse_args()

    ledger_path = os.path.expanduser(f"~/.cache/relic5/hindsight-{a.bank}-{a.source}.done")
    os.makedirs(os.path.dirname(ledger_path), exist_ok=True)
    done = set(open(ledger_path).read().split("\n")) if os.path.exists(ledger_path) else set()
    done.discard("")
    ledger = open(ledger_path, "a")

    print(f"{a.source}: reading the hub ({HUB}) …", flush=True)
    # a running clock while it reads (Nat: "can show running time (1s 2s 3s 4s)"), on the terminal itself, so the
    # log that tee keeps gets one line, not a carriage return a second
    try:
        tty = open("/dev/tty", "w")
    except OSError:
        tty = None
    t_read = time.time()
    with open(os.path.join(HERE, "hindsight-source.py"), "rb") as src:
        proc = subprocess.Popen(["ssh", "-o", "BatchMode=yes", HUB, f"~/relic5/app/.venv/bin/python - {a.source}"],
                                stdin=src, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        chunks: list[bytes] = []
        reader = threading.Thread(target=lambda: chunks.append(proc.stdout.read()))
        reader.start()
        while reader.is_alive():
            if tty:
                tty.write(f"\r  reading … {time.time() - t_read:.0f}s ")
                tty.flush()
            reader.join(1)
        proc.wait()
    if tty:
        tty.write("\r\x1b[2K")
        tty.flush()
    if proc.returncode != 0:
        sys.exit(f"{a.source}: the hub read failed (rc {proc.returncode}): {proc.stderr.read().decode()[-300:]}")
    items = [json.loads(l) for l in b"".join(chunks).decode("utf-8").splitlines() if l.strip()]
    print(f"{a.source}: read in {time.time() - t_read:.0f}s", flush=True)
    todo = [x for x in items if x["document_id"] not in done]
    blocks = sum(max(1, len(x["content"]) // 3000) for x in todo)
    print(f"{a.source}: {len(items):,} items on the hub, {len(items) - len(todo):,} already queued, {len(todo):,} to go "
          f"(~{blocks:,} blocks)", flush=True)

    t0, last_print, sent = time.time(), 0.0, 0
    hist: list[tuple[float, int, int]] = []   # (time, open operations, documents) for the last 15 minutes
    docs0 = stats(a.bank).get("total_documents", 0)
    i = 0
    while i < len(todo):
        st = stats(a.bank)
        # The bank's pending count lags an async post (its operations appear a moment later: on 2026-10-26 it read 1
        # while 9,495 items went in), so pace on what this run knows: items sent minus documents created since.
        inflight = sent - (st.get("total_documents", 0) - docs0)
        if st.get("pending_operations", 0) >= a.max_pending or inflight >= a.max_inflight:
            if tty:
                tty.write(f"\r  waiting … {time.time() - t0:.0f}s · open ops {st.get('pending_operations', 0):,} ")
                tty.flush()
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
            if tty:   # clear the ticker before the minute line
                tty.write("\r\x1b[2K")
                tty.flush()
            st = stats(a.bank)
            ops = st.get("pending_operations", 0)
            hist.append((time.time(), ops, st.get("total_documents", 0)))
            while len(hist) > 1 and hist[0][0] < time.time() - 900:
                hist.pop(0)
            span = (hist[-1][0] - hist[0][0]) / 60 if len(hist) > 1 else 0
            ops_rate = (hist[0][1] - hist[-1][1]) / span if span > 0 else 0       # open operations closed a minute
            doc_rate = (hist[-1][2] - hist[0][2]) / span if span > 0 else 0       # documents the bank made a minute
            head = (f"{time.strftime('%H:%M')} {a.source}: queued {i:,}/{len(todo):,} · bank {st.get('total_documents', 0):,} docs, "
                    f"{st.get('total_nodes', 0):,} memories · open ops {ops:,}")
            if i == 0:   # nothing of this source sent yet: say what it waits for, not a rate it does not have
                wait = f"{ops_rate:.0f} ops closed/min, starts in ~{(ops - a.max_pending) / ops_rate:.0f} min" if ops_rate > 0 else "measuring"
                print(f"{head} · waiting for the queue to drop below {a.max_pending} ({wait})", flush=True)
            else:
                left = len(todo) - i + max(0, sent - (st.get("total_documents", 0) - docs0))
                eta = f"{left / doc_rate / 60:.1f} h" if doc_rate > 0 else "measuring"
                print(f"{head} · sent {sent:,} · bank {doc_rate:.0f} docs/min · ETA {eta}", flush=True)
    print(f"{a.source}: all {len(todo):,} queued; the bank finishes the queue on its own (relic5 memory status)", flush=True)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
