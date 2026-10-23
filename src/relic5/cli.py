"""relic5 command line.

  relic5 token add <machine>      on the hub: make a token for one machine, print it once (file 0600)
  relic5 token list               on the hub: machines that hold a token (never the tokens)
  relic5 index [--root ~/relic5] [--force] [YYYY-MM ...]   on the hub: month manifests, then the BM25 tables that changed
  relic5 eval [tests/eval/semantic.json] [--semantic]   recall@10 of a query file against the hub
  relic5 log [-n 30]              on the hub: the last event of each job (logs/jobs.jsonl, relic3's JobEvent)
  relic5 serve [--root ~/relic5] [--host 127.0.0.1,100.103.52.67] [--port 8795]
  relic5 search <words> [--with tools] [--limit 20] [--since 7d] [--repo R] [--json]     any machine, over tailscale
  relic5 status [--json]

Client settings: RELIC5_URL (default http://white.follow-rankine.ts.net:8795), RELIC5_TOKEN_FILE
(default ~/.config/relic5/token, 0600, the one line `relic5 token add` printed on the hub).
Hub settings: RELIC5_ROOT (default ~/relic5), RELIC5_TOKENS (default ~/.config/relic5/tokens: `<machine> <token>` lines).
"""
import json, os, re, secrets, sys, time, urllib.parse, urllib.request

ROOT = os.environ.get("RELIC5_ROOT", "~/relic5")
TOKENS = os.environ.get("RELIC5_TOKENS", "~/.config/relic5/tokens")
URL = os.environ.get("RELIC5_URL", "http://white.follow-rankine.ts.net:8795")
TOKEN_FILE = os.environ.get("RELIC5_TOKEN_FILE", "~/.config/relic5/token")
PORT = 8795   # 8787, 8791 and 8792 are taken on white (2026-10-23)


def _opt(args, name, default=None):
    if name in args:
        i = args.index(name)
        v = args[i + 1]
        del args[i:i + 2]
        return v
    return default


def read_tokens(path=TOKENS):
    p = os.path.expanduser(path)
    if not os.path.exists(p):
        return {}
    out = {}
    for line in open(p):
        parts = line.split()
        if len(parts) == 2 and not line.startswith("#"):
            out[parts[0]] = parts[1]
    return out


def add_token(machine, path=TOKENS):
    if not re.match(r"^[a-z0-9-]+$", machine):
        raise SystemExit(f"bad machine name: {machine!r}")
    p = os.path.expanduser(path)
    os.makedirs(os.path.dirname(p), mode=0o700, exist_ok=True)
    have = read_tokens(path)
    if machine in have:
        raise SystemExit(f"{machine} already has a token (remove its line from {p} to replace it)")
    tok = secrets.token_urlsafe(32)
    fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    os.write(fd, f"{machine} {tok}\n".encode())
    os.close(fd)
    os.chmod(p, 0o600)
    return tok


def serve(args):
    import socket
    import uvicorn
    from .api import make_app
    root = os.path.expanduser(_opt(args, "--root", ROOT))
    hosts = _opt(args, "--host", "127.0.0.1").split(",")
    port = int(_opt(args, "--port", str(PORT)))
    app = make_app(root, read_tokens())
    socks = []
    for h in hosts:   # one process on every address (relic4 cli.py, PR #5 @febfdb7)
        sk = socket.socket(socket.AF_INET6 if ":" in h else socket.AF_INET)
        sk.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sk.bind((h, port))
        socks.append(sk)
    print("relic5 serve: " + " · ".join(f"http://{h}:{port}" for h in hosts) + f"  root {root}  (token on every request)", flush=True)
    uvicorn.Server(uvicorn.Config(app, log_level="warning", proxy_headers=False)).run(sockets=socks)


def call(path, params):
    tok = open(os.path.expanduser(TOKEN_FILE)).read().strip()
    url = URL.rstrip("/") + path + ("?" + urllib.parse.urlencode(params) if params else "")
    req = urllib.request.Request(url, headers={"Authorization": "Bearer " + tok})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)


def _line(h, width=110):
    txt = " ".join((h.get("text_snippet") or h.get("text") or "").split())[:width]
    who = ",".join(h.get("machines") or [])
    return f"{(h.get('ts') or '')[:16]}  {who:<7} {h.get('role') or '':<9} {(h.get('session_uuid') or '')[:8]}  {txt}"


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    if not args or args[0] in ("-h", "--help"):
        print(__doc__)
        return
    cmd, rest = args[0], args[1:]
    as_json = "--json" in rest
    rest = [a for a in rest if a != "--json"]
    if cmd == "token" and rest[:1] == ["add"] and len(rest) == 2:
        print(add_token(rest[1]))
    elif cmd == "token" and rest[:1] == ["list"]:
        print("\n".join(read_tokens()) or "(no tokens)")
    elif cmd == "index":
        import duckdb
        from .parts import Parts
        root = os.path.expanduser(_opt(rest, "--root", ROOT))
        from . import fts
        force = "--force" in rest
        rest = [a for a in rest if a != "--force"]
        from .jobs import job
        con = duckdb.connect()
        with job(root, "index") as j:
            done = Parts(root).index(con, months=rest or None)
            j.progress(done=len(done), unit="months", message="manifests: " + (",".join(done) or "none changed"))
            tabs = fts.build(root, con, force=force, log=lambda m: (print(m), j.progress(message=m)))
            j.progress(done=len(tabs), unit="tables", message="fts: " + (",".join(tabs) or "none changed"))
            from . import vec as V
            marks = {m: V.watermarks(root, con, m) for m in V.models(root)}
            p = os.path.join(fts.search_dir(root), "vectors.json")
            with open(p + ".tmp", "w") as f:
                json.dump({"at": time.strftime("%FT%T%z"), "models": marks}, f, indent=1)
            os.replace(p + ".tmp", p)
            for m, w in marks.items():
                print(f"vectors {m}: " + ", ".join(f"{k} pending {v['pending']:,} at {v['at']}" for k, v in sorted(w.items())))
    elif cmd == "eval":
        from .evaluate import main as ev
        ev(rest)
    elif cmd == "log":
        from .jobs import read
        root = os.path.expanduser(_opt(rest, "--root", ROOT))
        evs, _ = read(root)
        for e in reversed(evs[:int(_opt(rest, "-n", "30"))]):
            print(f"{e['at']}  {e['verb']:<7} {e['state']:<8} rc={e.get('rc', '')!s:<2} {e.get('host', '')[:12]:<12} {(e.get('message') or '')[:90]}")
    elif cmd == "serve":
        serve(rest)
    elif cmd == "search":
        p = {k: v for k in ("with", "limit", "role", "since", "until", "repo", "session", "horizon") if (v := _opt(rest, "--" + k))}
        r = call("/api/search", {"q": " ".join(rest), **p})
        if as_json:
            print(json.dumps(r, ensure_ascii=False, indent=1))
        else:
            for h in r["hits"]:
                print(_line(h))
            print(f"{len(r['hits'])} hits" + (" (more: next_cursor)" if r.get("next_cursor") else ""))
    elif cmd == "status":
        r = call("/api/status", {})
        print(json.dumps(r, ensure_ascii=False, indent=1))
    else:
        sys.exit(f"unknown command '{cmd}'\n  relic5 --help")


if __name__ == "__main__":
    main()
