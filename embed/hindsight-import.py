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
import argparse, concurrent.futures, json, os, subprocess, sys, threading, time, urllib.error, urllib.request

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


STATUS = os.path.expanduser("~/.cache/relic5/hindsight-feeder.json")


def ensure_bank(bank: str, about: str) -> None:
    """create the bank on first use, with the embed-first strategy and observations on (a Discord server's bank is for
    digging insight out of it: facts, people, observations)"""
    try:
        call("GET", f"/v1/default/banks/{bank}/config", timeout=30)
        return
    except urllib.error.HTTPError as ex:
        if ex.code != 404:
            raise
    call("PUT", f"/v1/default/banks/{bank}", {"name": bank, "background": about}, timeout=60)
    call("PATCH", f"/v1/default/banks/{bank}/config", {"updates": {
        "retain_strategies": {"embed-first": {"retain_extraction_mode": "chunks"}},
        "enable_observations": True, "enable_auto_consolidation": True}}, timeout=60)
    print(f"bank {bank}: created ({about}); observations on", flush=True)

# relic-scan's palette, for the terminal only (the log tee keeps plain text)
PINK, CYAN, GREY, GREEN, AMBER, Z, B = ("\x1b[38;2;255;60;172m", "\x1b[38;2;0;214;255m", "\x1b[38;2;128;136;156m",
                                        "\x1b[38;2;80;220;140m", "\x1b[38;2;245;183;59m", "\x1b[0m", "\x1b[1m")


def bar(share: float, w: int = 24) -> str:
    cells = round(max(0.0, min(1.0, share)) * w * 8)
    s = "█" * (cells // 8) + (["", "▏", "▎", "▍", "▌", "▋", "▊", "▉"][cells % 8])
    return s.ljust(w)


def eta_text(e: float | None) -> str:
    if not e:
        return "measuring"
    return f"{e / 3600:.1f} h" if e >= 5400 else f"{e / 60:.0f} min" if e >= 90 else f"{e:.0f} s"


def box(title: str, lines: list[str]) -> str:
    w = max(len(l) for l in lines + [title + "  "])
    top = f"╭─ {title} " + "─" * (w - len(title) - 1) + "╮"
    return "\n".join([top] + [f"│ {l.ljust(w)} │" for l in lines] + ["╰" + "─" * (w + 2) + "╯"])


def status(**kw: object) -> None:
    """the feeder's progress for `relic5 memory top`: source, strategy, total, queued, percent, items/min, eta"""
    tmp = STATUS + ".tmp"
    with open(tmp, "w") as f:
        json.dump(kw | {"at": time.time()}, f)
    os.replace(tmp, STATUS)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("source", help="memory | vault | git | thinking | sessions (read on the hub), or discord:<guild_id> "
                    "(a maw atlas Discord backup on this machine, embed/discord-source.py; bank discord-<server> by default)")
    ap.add_argument("--strategy", default="", help="a bank retain strategy, e.g. embed-first (chunks only, no LLM): "
                    "posted synchronously, so it does not queue behind LLM retains; its own ledger")
    ap.add_argument("--bank", default="relic5")
    ap.add_argument("--max-pending", type=int, default=40, help="hold back while the bank has this many open operations")
    ap.add_argument("--max-inflight", type=int, default=600,
                    help="hold back while this many items sent here are not yet documents in the bank")
    ap.add_argument("--batch", type=int, default=40)
    ap.add_argument("--parallel", type=int, default=32, help="with --strategy: synchronous batches in flight at once "
                    "(Hindsight handles one synchronous batch an item at a time)")
    a = ap.parse_args()
    if a.source not in ("memory", "vault", "git", "thinking", "sessions") and not a.source.startswith("discord:"):
        ap.error(f"unknown source {a.source}")
    if a.source.startswith("discord:"):   # one bank per server unless --bank names one
        gid = a.source.split(":", 1)[1]
        r = subprocess.run([sys.executable, os.path.join(HERE, "discord-source.py"), "--list"], capture_output=True, text=True, check=True)
        row = next((json.loads(l) for l in r.stdout.splitlines() if json.loads(l)["guild"] == gid), None)
        if not row:
            sys.exit(f"{a.source}: no finished backup for that server (embed/discord-source.py --list)")
        if a.bank == "relic5":
            a.bank = row["bank"]
        ensure_bank(a.bank, f"Discord server {row['name'].replace('_', ' ')} (maw atlas backup, guild {gid})")

    ledger_path = os.path.expanduser(f"~/.cache/relic5/hindsight-{a.bank}-{a.source.replace(':', '-')}{'.' + a.strategy if a.strategy else ''}.done")
    if a.strategy and a.batch == 40:
        a.batch = 20   # small batches, many at once: a huge note (vault max 3.3 MB) holds up only its own batch
    os.makedirs(os.path.dirname(ledger_path), exist_ok=True)
    done = set(open(ledger_path).read().split("\n")) if os.path.exists(ledger_path) else set()
    done.discard("")
    ledger = open(ledger_path, "a")

    if os.path.exists("/dev/tty"):
        try:
            with open("/dev/tty", "w") as t_:
                t_.write(f"{GREY}{time.strftime('%F %T')} relic5 memory import · {a.source} · {a.strategy or 'full'} -> bank {a.bank}{Z}\n")
        except OSError:
            pass
    print(f"{a.source}: reading the hub ({HUB}) …", flush=True)
    # a running clock while it reads (Nat: "can show running time (1s 2s 3s 4s)"), on the terminal itself, so the
    # log that tee keeps gets one line, not a carriage return a second
    try:
        tty = open("/dev/tty", "w")
    except OSError:
        tty = None
    t_read = time.time()
    # the source runs on the hub into a file there, and the file comes over with rsync (compressed, resumable): one
    # long ssh pipe was cut short at 938 MB (sessions, 2026-10-26) and left half a JSON line
    safe = a.source.replace(":", "-")
    remote, local = f"/tmp/hindsight-{safe}.jsonl", os.path.expanduser(f"~/.cache/relic5/hindsight-{safe}.jsonl")
    done_read = threading.Event()

    def clock() -> None:
        while not done_read.wait(1):
            if tty:
                tty.write(f"\r  reading … {time.time() - t_read:.0f}s ")
                tty.flush()

    threading.Thread(target=clock, daemon=True).start()
    if a.source.startswith("discord:"):   # the Discord backups live on this machine: no hub, no copy
        with open(local, "wb") as out:
            r = subprocess.run([sys.executable, os.path.join(HERE, "discord-source.py"), a.source.split(":", 1)[1]], stdout=out, stderr=subprocess.PIPE)
    else:
        with open(os.path.join(HERE, "hindsight-source.py"), "rb") as src:
            r = subprocess.run(["ssh", "-o", "BatchMode=yes", HUB, f"~/relic5/app/.venv/bin/python - {a.source} > {remote}"],
                               stdin=src, capture_output=True)
    if r.returncode != 0:
        done_read.set()
        sys.exit(f"{a.source}: the hub read failed (rc {r.returncode}): {r.stderr.decode()[-300:]}")
    for attempt in range(5 if not a.source.startswith("discord:") else 0):
        r = subprocess.run(["rsync", "-z", "--partial", "--timeout=120", f"{HUB}:{remote}", local], capture_output=True)
        if r.returncode == 0:
            break
        time.sleep(5)
    done_read.set()
    if tty:
        tty.write("\r\x1b[2K")
        tty.flush()
    if r.returncode != 0:
        sys.exit(f"{a.source}: copying {remote} from the hub failed (rc {r.returncode}): {r.stderr.decode()[-300:]}")
    chunks = [open(local, "rb").read()]
    print(f"{a.source}: read in {time.time() - t_read:.0f}s ({os.path.getsize(local) / 1e6:,.0f} MB)", flush=True)
    items, bad = [], 0
    # split on "\n" only: str.splitlines() also breaks at U+2028, U+0085 and \x1c-\x1e, which json.dumps(ensure_ascii=False)
    # leaves raw inside strings (2026-10-26: 18 session blocks cut in two, the file itself had 0 bad lines)
    for l in b"".join(chunks).decode("utf-8", "replace").split("\n"):
        if not l.strip():
            continue
        try:
            items.append(json.loads(l))
        except ValueError:   # a line cut short (the hub's read was interrupted): skip it, say so, keep the rest
            bad += 1
    if bad:
        print(f"{a.source}: {bad:,} line(s) from the hub were not JSON (cut short?) and are skipped", flush=True)
    # never overwrite a document the bank already has (an earlier full LLM import of the same session would be
    # replaced by bare chunks): skip every id already in the bank, whatever ledger queued it
    have: set[str] = set()
    off = 0
    while True:
        page = call("GET", f"/v1/default/banks/{a.bank}/documents?limit=1000&offset={off}", timeout=120)
        ids = [d["id"] for d in page.get("items") or []]
        have.update(ids)
        off += len(ids)
        if not ids or off >= page.get("total", 0):
            break
    todo = [x for x in items if x["document_id"] not in done and x["document_id"] not in have]
    if have:
        print(f"{a.source}: {len(have):,} documents already in the bank are skipped", flush=True)
    blocks = sum(max(1, len(x["content"]) // 3000) for x in todo)
    print(f"{a.source}: {len(items):,} items on the hub, {len(items) - len(todo):,} already queued, {len(todo):,} to go "
          f"(~{blocks:,} blocks)", flush=True)

    t0, last_print, sent = time.time(), 0.0, 0
    speed_hist: list[tuple[float, int]] = []   # (time, items queued so far) for this run's own speed
    hist: list[tuple[float, int, int]] = []   # (time, open operations, documents) for the last 15 minutes
    docs0 = stats(a.bank).get("total_documents", 0)
    i = 0
    st = stats(a.bank)

    def own() -> tuple[float, float | None]:
        """items a minute this run queued over the last 5 minutes, and the ETA in seconds for the rest"""
        now = time.time()
        speed_hist.append((now, i))
        while len(speed_hist) > 2 and speed_hist[0][0] < now - 300:
            speed_hist.pop(0)
        dt = speed_hist[-1][0] - speed_hist[0][0]
        rate = (speed_hist[-1][1] - speed_hist[0][1]) / dt * 60 if dt > 5 else 0.0
        return rate, ((len(todo) - i) / rate * 60 if rate > 0 else None)

    def send(batch: list) -> bool:
        items_ = [{k: v for k, v in x.items() if v is not None} | ({"strategy": a.strategy} if a.strategy else {}) for x in batch]
        try:
            call("POST", f"/v1/default/banks/{a.bank}/memories", {"items": items_, "async": not a.strategy},
                 timeout=900 if a.strategy else 120)
            return True
        except (urllib.error.URLError, OSError) as ex:
            print(f"{a.source}: post failed ({ex}); will retry", flush=True)
            return False

    pool = None
    running: dict = {}
    retry: list = []
    nxt = 0

    while i < len(todo):
        rate_, eta_ = own()
        status(source=a.source, strategy=a.strategy or "full", total=len(items), todo=len(todo), queued=i,
               skipped=len(items) - len(todo), percent=round(100 * i / max(len(todo), 1), 1), items_per_min=round(rate_, 1),
               eta_s=round(eta_) if eta_ else None, started=t0, state="waiting" if (i == 0 and not a.strategy) else "sending")
        if not a.strategy or time.time() - last_print >= 60:
            st = stats(a.bank)
        # The bank's pending count lags an async post (its operations appear a moment later: on 2026-10-26 it read 1
        # while 9,495 items went in), so pace on what this run knows: items sent minus documents created since.
        inflight = sent - (st.get("total_documents", 0) - docs0)
        if not a.strategy and (st.get("pending_operations", 0) >= a.max_pending or inflight >= a.max_inflight):
            if tty:
                tty.write(f"\r  waiting … {time.time() - t0:.0f}s · open ops {st.get('pending_operations', 0):,} ")
                tty.flush()
            time.sleep(5)
        elif a.strategy:
            # a continuous pipeline: --parallel batches always in flight, a new one starts the moment one ends, so a
            # batch holding a huge note (vault max 3.3 MB) no longer stalls the rest (rounds waited for their slowest)
            if pool is None:
                pool = concurrent.futures.ThreadPoolExecutor(a.parallel)
            while len(running) < a.parallel and nxt < len(todo):
                batch = todo[nxt:nxt + a.batch]
                running[pool.submit(send, batch)] = batch
                nxt += len(batch)
            fin, _ = concurrent.futures.wait(running, timeout=5, return_when=concurrent.futures.FIRST_COMPLETED)
            for fu in fin:
                batch = running.pop(fu)
                if fu.result():
                    for x in batch:
                        ledger.write(x["document_id"] + "\n")
                    sent += len(batch)
                    i += len(batch)
                else:
                    retry.append(batch)
            ledger.flush()
            if retry and len(running) < a.parallel:   # failed batches go again, after a pause
                time.sleep(10)
                for batch in retry:
                    running[pool.submit(send, batch)] = batch
                retry = []
            if i < len(todo) and not running and nxt >= len(todo) and not retry:
                break
            rate_, eta_ = own()
            status(source=a.source, strategy=a.strategy, total=len(items), todo=len(todo), queued=i,
                   skipped=len(items) - len(todo), percent=round(100 * i / max(len(todo), 1), 1), items_per_min=round(rate_, 1),
                   eta_s=round(eta_) if eta_ else None, started=t0, state=f"sending · {len(running)} batches in flight")
            if tty:
                pct = i / max(len(todo), 1)
                tty.write(f"\r\x1b[2K  {PINK}{B}{a.source}{Z}{GREY}/{a.strategy}{Z} {CYAN}{bar(pct)}{Z} {B}{pct * 100:5.1f}%{Z} "
                          f"{GREY}{i:,}/{len(todo):,} ·{Z} {GREEN}{rate_:,.0f}/min{Z} {GREY}· ETA{Z} {AMBER}{eta_text(eta_)}{Z} "
                          f"{GREY}· {len(running)} in flight{Z} ")
                tty.flush()
        else:
            batch = todo[i:i + a.batch]
            if send(batch):
                for x in batch:
                    ledger.write(x["document_id"] + "\n")
                ledger.flush()
                sent += len(batch)
                i += len(batch)
            else:
                time.sleep(30)
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
            r_, e_ = own()
            pct = 100 * i / max(len(todo), 1)
            head = (f"{time.strftime('%H:%M')} {a.source}{'/' + a.strategy if a.strategy else ''}: {pct:.1f}% · queued {i:,}/{len(todo):,} · "
                    f"{r_:,.0f} items/min · ETA {(f'{e_ / 3600:.1f} h' if e_ and e_ > 5400 else f'{e_ / 60:.0f} min') if e_ else 'measuring'} · bank {st.get('total_documents', 0):,} docs, "
                    f"{st.get('total_nodes', 0):,} memories · open ops {ops:,}")
            if i == 0 and not a.strategy:   # nothing of this source sent yet: say what it waits for, not a rate it does not have
                wait = f"{ops_rate:.0f} ops closed/min, starts in ~{(ops - a.max_pending) / ops_rate:.0f} min" if ops_rate > 0 else "measuring"
                print(f"{head} · waiting for the queue to drop below {a.max_pending} ({wait})", flush=True)
            else:
                left = len(todo) - i + max(0, sent - (st.get("total_documents", 0) - docs0))
                eta = f"{left / doc_rate / 60:.1f} h" if doc_rate > 0 else "measuring"
                print(f"{head} · sent {sent:,} · bank {doc_rate:.0f} docs/min · ETA {eta}", flush=True)
    status(source=a.source, strategy=a.strategy or "full", total=len(items), todo=len(todo), queued=len(todo),
           skipped=len(items) - len(todo), percent=100.0, items_per_min=0, eta_s=0, started=t0, state="done")
    st_end = stats(a.bank)
    mins = (time.time() - t0) / 60
    summary = box("▓▒░ RELIC5·MEMORY IMPORT ░▒▓", [
        f"{a.source} · {a.strategy or 'full LLM extraction'} · bank {a.bank}",
        f"{len(todo):,} items sent · {len(items) - len(todo):,} skipped (already there) · {len(items):,} on the hub",
        f"{mins:.1f} min · {len(todo) / max(mins, 0.01):,.0f} items/min",
        f"bank now {st_end.get('total_documents', 0):,} documents · {st_end.get('total_nodes', 0):,} memories · open ops {st_end.get('pending_operations', 0):,}",
        "▸ relic5 memory recall …   ▸ relic5 memory top",
    ])
    if tty:
        tty.write("\r\x1b[2K")
        tty.write(CYAN + summary.replace("│ ", "│ " + Z, ).replace(" │", CYAN + " │") + Z + "\n")
        tty.flush()
    print(summary, flush=True)
    print(f"{a.source}: all {len(todo):,} queued; the bank finishes the queue on its own (relic5 memory status)", flush=True)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
