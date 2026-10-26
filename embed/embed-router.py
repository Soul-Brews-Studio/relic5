#!/usr/bin/env python3
"""embed-router.py: the dispatcher on m5 between Hindsight (and anything that speaks OpenAI or Ollama) and the workers
that do the work: embedding, LLM calls, reranking. Workers live in a registry file and can be added or removed while it
runs (Nat, 2026-10-26: "do we have like work dispatcher or how we add more workers?").

  python3 embed/embed-router.py [--port 11436] [--big 32] [--workers ~/.config/relic5/workers.json]
  relic5 memory workers list | add … | rm …        # the same registry from the CLI (docs/HINDSIGHT.md)

  POST /v1/embeddings | /api/embed   {"input": str | [str]}   OpenAI / Ollama shape back, header X-Embed-Engine
  POST /v1/chat/completions          the LLM: each call to the worker with the most free slots, retried on another
  POST /rerank                       {"query", "texts"} -> [{"index", "score"}] (TEI); no reranker up: given order, 0
  GET  /info                         the reranker's model_id (TEI)
  GET  /health                       every worker: up or down, busy, calls, texts, errors, speed
  GET  /workers                      the registry;  POST /workers {kind, name, url, …} adds or replaces one;
  DELETE /workers?kind=K&name=N      removes one. Changes are written to the file; edits to the file are picked up.

Embedding (every embed worker must serve the same vector space: embeddinggemma-300m, parity gb300 bf16 vs ANE w8a16
cos p05 0.9983, docs/HINDSIGHT.md): a batch under --big texts goes whole to the worker with the fewest requests in
flight; a bigger one is split over all of them by measured speed and run at once. A failed part is redone elsewhere.
Texts go through unchanged: the caller adds gemma's prompt. Stdlib only; started by hand (embed/start.sh).
"""
import argparse, collections, json, os, threading, time, urllib.error, urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

MODEL = "embeddinggemma-300m"
DEFAULT = {   # written to the registry file the first time; afterwards the file is the truth
    "embed": [
        {"name": "ane", "url": "http://127.0.0.1:11435", "api": "ollama", "model": "embeddinggemma:ane-w8a16", "batch": 64,
         "note": "m5 Neural Engine, ANEEmbedBar"},
        {"name": "gb300", "url": "http://127.0.0.1:11437", "api": "ollama", "model": None, "batch": 4096,
         "note": "gb300 GPU bf16, embed/gb300-serve.py through the tunnel"},
    ],
    "llm": [
        {"name": "gb300", "url": "http://127.0.0.1:11510/v1/chat/completions", "model": "qwen3.8-27b", "slots": 24,
         "extra": {"chat_template_kwargs": {"enable_thinking": False}}, "note": "vLLM on gb300 through the tunnel"},
        {"name": "m5", "url": "http://127.0.0.1:11434/v1/chat/completions", "model": "qwen3.6", "slots": 4, "extra": {},
         "note": "Ollama on m5's GPU"},
    ],
    "rerank": [{"name": "gb300", "url": "http://127.0.0.1:11437", "note": "bge-reranker-v2-m3 on gb300"}],
}
KINDS = ("embed", "llm", "rerank")

lock = threading.Condition()
reg: dict[str, list[dict]] = {}
reg_file = ""
reg_mtime = 0.0
run: dict[str, dict] = {}   # "kind:name" -> counters, kept across reloads
last = {"engine": None, "at": None}


def counters(kind: str, name: str) -> dict:
    return run.setdefault(f"{kind}:{name}", {"inflight": 0, "requests": 0, "texts": 0, "tokens": 0, "errors": 0, "seconds": 0.0,
                                             "rate": 400.0 if name == "gb300" else 70.0, "since": time.time(),
                                             "window": collections.deque(), "open": [], "rest_until": 0.0})


def done(c: dict, start: float, texts: int = 0, tokens: int = 0) -> None:
    """record one finished request (call with the lock held): totals, and the last 10 minutes for utilization"""
    now = time.time()
    c["requests"] += 1
    c["texts"] += texts
    c["tokens"] += tokens
    c["seconds"] += now - start
    c["window"].append((start, now, texts, tokens))
    while c["window"] and c["window"][0][1] < now - 600:
        c["window"].popleft()


def usage(c: dict, capacity: int, span: float = 60.0) -> dict:
    """busy share of the last `span` seconds (time in requests / (span x slots), counting the ones still running as
    busy) and the work done in it"""
    now = time.time()
    busy = sum(max(0.0, min(e, now) - max(s, now - span)) for s, e, _, _ in c["window"] if e > now - span)
    busy += sum(now - max(s, now - span) for s in c["open"])   # the ones still running count as busy so far
    w = [x for x in c["window"] if x[1] > now - span]
    return {"util": round(min(1.0, busy / (span * max(capacity, 1))), 3), "requests_1m": len(w),
            "texts_1m": sum(x[2] for x in w), "tokens_1m": sum(x[3] for x in w)}


def load(force: bool = False) -> None:
    """(re)read the registry file when it changed; create it from DEFAULT the first time"""
    global reg, reg_mtime
    if not os.path.exists(reg_file):
        save(DEFAULT)
    m = os.path.getmtime(reg_file)
    if not force and m == reg_mtime:
        return
    with open(reg_file) as f:
        new = json.load(f)
    with lock:
        reg = {k: list(new.get(k) or []) for k in KINDS}
        reg_mtime = m
        lock.notify_all()


def save(data: dict) -> None:
    global reg_mtime
    os.makedirs(os.path.dirname(reg_file), exist_ok=True)
    tmp = reg_file + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, indent=1)
    os.replace(tmp, reg_file)
    reg_mtime = 0.0


def post(url: str, body: dict, timeout: float) -> dict:
    req = urllib.request.Request(url, json.dumps(body).encode(), {"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


ERRS = (urllib.error.URLError, OSError, KeyError, ValueError, TypeError)


# ── embedding ──────────────────────────────────────────────────────────────────────────────────────────────────────
def embed_on(w: dict, texts: list[str]) -> list[list[float]]:
    c = counters("embed", w["name"])
    t = time.time()
    with lock:
        c["inflight"] += 1
        c["open"].append(t)
    try:
        out: list[list[float]] = []
        n = int(w.get("batch") or 64)
        for i in range(0, len(texts), n):
            part = texts[i:i + n]
            if w.get("api") == "openai":
                body = {"input": part} | ({"model": w["model"]} if w.get("model") else {})
                out += [d["embedding"] for d in post(w["url"].rstrip("/") + "/v1/embeddings", body, 600)["data"]]
            else:
                body = {"input": part} | ({"model": w["model"]} if w.get("model") else {})
                out += post(w["url"].rstrip("/") + "/api/embed", body, 600)["embeddings"]
    except ERRS:
        with lock:
            c["errors"] += 1
            c["rest_until"] = time.time() + 30   # sit out 30 s (gb300 2026-10-26: CUDA OOM, a shared full GPU)
        raise
    finally:
        with lock:
            c["inflight"] -= 1
            c["open"].remove(t)
    dt = time.time() - t
    with lock:
        done(c, t, texts=len(texts))
        if len(texts) >= 8 and dt > 0:
            c["rate"] = 0.7 * c["rate"] + 0.3 * (len(texts) / dt)
        last.update(engine=w["name"], at=time.strftime("%FT%T%z"))
    return out


def embed(texts: list[str], big: int, prefer: str | None) -> tuple[str, list[list[float]]]:
    with lock:
        allw = list(reg.get("embed") or [])
        ws = [w for w in allw if counters("embed", w["name"])["rest_until"] <= time.time()] or allw   # resting ones only if none is left
    if not ws:
        raise RuntimeError("no embed worker in the registry")
    if len(texts) < big or len(ws) == 1 or prefer:
        with lock:   # whole, to the least busy (ties: the order in the registry); then the others
            order = sorted(ws, key=lambda w: (w["name"] != prefer, counters("embed", w["name"])["inflight"]))
        err: Exception | None = None
        for w in order:
            try:
                return w["name"], embed_on(w, texts)
            except ERRS as ex:
                err = ex
        raise RuntimeError(f"no embed worker answered: {err}")
    with lock:   # split by measured speed, every worker at once
        rates = [max(counters("embed", w["name"])["rate"], 1.0) for w in ws]
    total, n, cuts = sum(rates), len(texts), [0]
    for r in rates[:-1]:
        cuts.append(min(n, cuts[-1] + max(1, round(n * r / total))))
    cuts.append(n)
    parts = [(w, cuts[i], cuts[i + 1]) for i, w in enumerate(ws) if cuts[i + 1] > cuts[i]]
    out: dict[int, list[list[float]]] = {}
    errs: dict[int, Exception] = {}

    def go(k: int, w: dict, a: int, b: int) -> None:
        try:
            out[k] = embed_on(w, texts[a:b])
        except ERRS as ex:
            errs[k] = ex

    th = [threading.Thread(target=go, args=(k, w, a, b)) for k, (w, a, b) in enumerate(parts)]
    for t in th:
        t.start()
    for t in th:
        t.join()
    ok = [parts[k][0] for k in out]
    for k in list(errs):   # redo a failed part on a worker that answered
        w, a, b = parts[k]
        if not ok:
            raise RuntimeError(f"no embed worker answered: {errs[k]}")
        out[k] = embed_on(ok[0], texts[a:b])
    vecs: list[list[float]] = []
    for k in range(len(parts)):
        vecs += out[k]
    return "+".join(w["name"] for w, _, _ in parts) if not errs else "fallback", vecs


# ── LLM ────────────────────────────────────────────────────────────────────────────────────────────────────────────
def llm(body: dict) -> tuple[str, bytes]:
    """one chat completion on the worker with the most free slots; waits for a slot; retries on another"""
    tried: set[str] = set()
    err: Exception | None = None
    while True:
        with lock:
            while True:
                ws = [w for w in reg.get("llm") or [] if w["name"] not in tried]
                if not ws:
                    raise RuntimeError(f"no LLM worker answered: {err}")
                free = [(counters("llm", w["name"])["inflight"] / max(int(w.get("slots") or 1), 1), i, w) for i, w in enumerate(ws)
                        if counters("llm", w["name"])["inflight"] < int(w.get("slots") or 1)]
                if free:
                    w = min(free, key=lambda x: (x[0], x[1]))[2]
                    counters("llm", w["name"])["inflight"] += 1
                    break
                lock.wait(1)
        c = counters("llm", w["name"])
        t = time.time()
        with lock:
            c["open"].append(t)
        req = {k: v for k, v in body.items() if k not in ("chat_template_kwargs", "stream")} | {"model": w["model"]} | (w.get("extra") or {})
        try:
            r = urllib.request.urlopen(urllib.request.Request(w["url"], json.dumps(req).encode(), {"Content-Type": "application/json"}),
                                       timeout=900)
            raw = r.read()
            try:
                tok = int((json.loads(raw).get("usage") or {}).get("completion_tokens") or 0)
            except ValueError:
                tok = 0
            with lock:
                done(c, t, tokens=tok)
            return w["name"], raw
        except ERRS as ex:
            with lock:
                c["errors"] += 1
            tried.add(w["name"])
            err = ex
        finally:
            with lock:
                c["inflight"] -= 1
                c["open"].remove(t)
                lock.notify_all()


# ── rerank ─────────────────────────────────────────────────────────────────────────────────────────────────────────
def rerank(body: dict) -> tuple[str, object]:
    texts = body.get("texts") or []
    with lock:
        ws = list(reg.get("rerank") or [])
    for w in ws:
        c = counters("rerank", w["name"])
        t = time.time()
        try:
            out = post(w["url"].rstrip("/") + "/rerank", {"query": body.get("query", ""), "texts": texts}, 120)
            with lock:
                done(c, t, texts=len(texts))
            return w["name"], out
        except ERRS:
            with lock:
                c["errors"] += 1
    return "none", [{"index": i, "score": 0.0} for i in range(len(texts))]


def up(url: str) -> object:
    for path in ("/health", "/api/tags", "/v1/models"):
        try:
            with urllib.request.urlopen(url.split("/v1/")[0].rstrip("/") + path, timeout=3) as r:
                h = json.load(r)
                return {"status": "ok", "model": h.get("model") if isinstance(h, dict) else None}
        except Exception:   # noqa: BLE001
            continue
    return {"status": "down"}


def health(big: int) -> dict:
    load()
    with lock:
        snap = {k: [dict(w) for w in reg.get(k) or []] for k in KINDS}
    def row(k: str, w: dict) -> dict:
        c = counters(k, w["name"])
        with lock:
            u = usage(c, int(w.get("slots") or 1) if k == "llm" else 1)
            tot = {x: (round(v, 1) if isinstance(v, float) else v) for x, v in c.items() if x not in ("window", "since", "open", "rest_until")}
            tot["resting_s"] = max(0, round(c["rest_until"] - time.time()))
        return w | {"up": up(w["url"])["status"]} | tot | u | {"avg_s": round(c["seconds"] / max(c["requests"], 1), 1),
                                                              "uptime_s": round(time.time() - c["since"])}

    workers = {k: [row(k, w) for w in ws] for k, ws in snap.items()}
    # the shapes the monitors already read: stats[name] for embedding, llm[name], engines[name]
    stats = {w["name"]: {x: w[x] for x in ("requests", "texts", "errors", "seconds")} for w in workers["embed"]}
    llm_ = {w["name"]: {"model": w["model"], "slots": w.get("slots"), "inflight": w["inflight"], "calls": w["requests"],
                        "errors": w["errors"], "seconds": w["seconds"]} for w in workers["llm"]}
    return {"status": "ok", "model": MODEL, "big": big, "registry": reg_file, "last": last, "stats": stats, "llm": llm_,
            "inflight": {w["name"]: w["inflight"] for w in workers["embed"]},
            "rate": {w["name"]: w["rate"] for w in workers["embed"]},
            "engines": {w["name"]: {"status": w["up"], "model": w.get("model")} for w in workers["embed"]},
            "workers": workers}


def main() -> None:
    global reg_file
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=11436)
    ap.add_argument("--big", type=int, default=32, help="a batch of at least this many texts is split over all embed workers")
    ap.add_argument("--workers", default=os.path.expanduser("~/.config/relic5/workers.json"))
    a = ap.parse_args()
    reg_file = a.workers
    load(force=True)

    class H(BaseHTTPRequestHandler):
        def log_message(self, *_: object) -> None:
            pass

        def send(self, code: int, body: object, engine: str | None = None, header: str = "X-Embed-Engine") -> None:
            raw = body if isinstance(body, bytes) else json.dumps(body).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            if engine:
                self.send_header(header, engine)
            self.end_headers()
            self.wfile.write(raw)

        def body(self) -> dict:
            return json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")

        def do_GET(self) -> None:
            p = self.path.split("?")[0]
            if p == "/health":
                self.send(200, health(a.big))
            elif p == "/workers":
                load()
                with lock:
                    self.send(200, {"registry": reg_file, **reg})
            elif p == "/info":
                with lock:
                    ws = list(reg.get("rerank") or [])
                for w in ws:
                    try:
                        with urllib.request.urlopen(w["url"].rstrip("/") + "/info", timeout=5) as r:
                            return self.send(200, json.load(r))
                    except Exception:   # noqa: BLE001
                        continue
                self.send(200, {"model_id": "none (no reranker up: rerank keeps the given order)"})
            elif p in ("/v1/models", "/api/tags"):
                self.send(200, {"object": "list", "data": [{"id": MODEL, "object": "model"}], "models": [{"name": MODEL, "model": MODEL}]})
            else:
                self.send(404, {"error": "not found"})

        def do_DELETE(self) -> None:
            from urllib.parse import parse_qs, urlparse
            q = parse_qs(urlparse(self.path).query)
            if urlparse(self.path).path != "/workers" or "kind" not in q or "name" not in q:
                return self.send(400, {"error": "DELETE /workers?kind=embed|llm|rerank&name=N"})
            kind, name = q["kind"][0], q["name"][0]
            load()
            with lock:
                data = {k: [w for w in reg.get(k) or [] if not (k == kind and w["name"] == name)] for k in KINDS}
                gone = len(reg.get(kind) or []) - len(data[kind])
            save(data)
            load(force=True)
            self.send(200 if gone else 404, {"removed": gone, "kind": kind, "name": name})

        def do_POST(self) -> None:
            p = self.path.split("?")[0]
            load()
            try:
                body = self.body()
            except ValueError:
                return self.send(400, {"error": "body is not JSON"})
            if p == "/workers":
                kind, w = body.pop("kind", None), body
                if kind not in KINDS or not w.get("name") or not w.get("url") or (kind == "llm" and not w.get("model")):
                    return self.send(400, {"error": "need kind (embed|llm|rerank), name, url; llm also model (and slots)"})
                if kind == "embed":   # a new embed worker must serve the same vector space: check it answers first
                    try:
                        v = embed_on(w | {"batch": 1}, ["title: none | text: relic5 parity check"])
                        if len(v[0]) != 768:
                            return self.send(400, {"error": f"{w['name']} answers {len(v[0])} dims, not 768"})
                    except ERRS as ex:
                        return self.send(400, {"error": f"{w['name']} did not embed: {ex}"[:300]})
                with lock:
                    data = {k: [x for x in reg.get(k) or [] if not (k == kind and x["name"] == w["name"])] for k in KINDS}
                data[kind].append(w)
                save(data)
                load(force=True)
                return self.send(200, {"added": kind, "worker": w})
            if p == "/v1/chat/completions":
                try:
                    name, raw = llm(body)
                except RuntimeError as ex:
                    return self.send(503, {"error": str(ex)[:300]})
                return self.send(200, raw, name, "X-LLM-Backend")
            if p == "/rerank":
                name, out = rerank(body)
                return self.send(200, out, name)
            if p not in ("/v1/embeddings", "/api/embed", "/embeddings"):
                return self.send(404, {"error": "not found"})
            texts = body.get("input")
            texts = [texts] if isinstance(texts, str) else texts
            if not isinstance(texts, list) or not all(isinstance(t, str) for t in texts):
                return self.send(400, {"error": "input must be a string or a list of strings"})
            try:
                engine, vecs = embed(texts, a.big, self.headers.get("X-Embed-Prefer")) if texts else ("none", [])
            except RuntimeError as ex:
                return self.send(503, {"error": str(ex)[:300]})
            if p == "/api/embed":
                return self.send(200, {"model": MODEL, "embeddings": vecs}, engine)
            n = sum(len(t) for t in texts)
            self.send(200, {"object": "list", "model": MODEL, "usage": {"prompt_tokens": n, "total_tokens": n},
                            "data": [{"object": "embedding", "index": i, "embedding": v} for i, v in enumerate(vecs)]}, engine)

    class Server(ThreadingHTTPServer):
        request_queue_size = 256   # the default 5 refused connections under Hindsight's 32 workers plus a test burst
        daemon_threads = True

    print(f"embed-router: http://{a.host}:{a.port} · workers {reg_file} · split at >= {a.big} texts", flush=True)
    Server((a.host, a.port), H).serve_forever()


if __name__ == "__main__":
    main()
