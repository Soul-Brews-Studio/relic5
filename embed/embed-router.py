#!/usr/bin/env python3
"""embed-router.py: one embedding endpoint on m5 for anything that speaks OpenAI or Ollama (Hindsight, relic5), routed
the relic5 way (Nat, 2026-10-26: "if huge can we go gb300 first?"): a big batch goes to gb300's GPU first, a small one
to m5's Neural Engine first, and each falls back to the other. Both serve embeddinggemma-300m in one vector space:
parity measured 2026-10-26 on 259 m5 texts, cosine min 0.9976, p05 0.9983, median 0.9991 (docs/HINDSIGHT.md).

  python3 embed/embed-router.py [--port 11436] [--big 32]

  POST /v1/embeddings   {"model"?, "input": str | [str]}  OpenAI shape back
  POST /api/embed       {"model"?, "input": str | [str]}  Ollama shape back
  POST /rerank          {"query", "texts"} -> [{"index", "score"}]   TEI shape, gb300's cross-encoder (bge-reranker-v2-m3);
                        with gb300 down it answers the texts in their given order with score 0, so a recall still works
  GET  /info            the reranker's model_id (TEI)
  GET  /health          both engines, which one answered last, counts

Texts go through unchanged: the caller adds gemma's prompt ("task: search result | query: ", "title: none | text: ").
Every answer says which engine made it (header X-Embed-Engine). Stdlib only; started by hand (embed/start.sh).
"""
import argparse, json, threading, time, urllib.error, urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ANE = "http://127.0.0.1:11435"     # ANEEmbedBar (ane-oracle tools/ane-embed-app), Ollama /api/embed, 64 inputs a call
ANE_MODEL = "embeddinggemma:ane-w8a16"
GB300 = "http://127.0.0.1:11437"   # embed/gb300-serve.py through the ssh tunnel
MODEL = "embeddinggemma-300m"
stats: dict[str, dict[str, float]] = {"ane": {"requests": 0, "texts": 0, "errors": 0, "seconds": 0.0},
                                      "gb300": {"requests": 0, "texts": 0, "errors": 0, "seconds": 0.0}}
last = {"engine": None, "at": None}
lock = threading.Lock()


def post(url: str, body: dict, timeout: float) -> dict:
    req = urllib.request.Request(url, json.dumps(body).encode(), {"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def on_ane(texts: list[str]) -> list[list[float]]:
    out: list[list[float]] = []
    for i in range(0, len(texts), 64):
        out += post(f"{ANE}/api/embed", {"model": ANE_MODEL, "input": texts[i:i + 64]}, 120)["embeddings"]
    return out


def on_gb300(texts: list[str]) -> list[list[float]]:
    out: list[list[float]] = []
    for i in range(0, len(texts), 4096):
        out += post(f"{GB300}/api/embed", {"input": texts[i:i + 4096]}, 600)["embeddings"]
    return out


ENGINES = {"ane": on_ane, "gb300": on_gb300}


def embed(texts: list[str], big: int, prefer: str | None) -> tuple[str, list[list[float]]]:
    order = [prefer] if prefer in ENGINES else []
    order += [e for e in (["gb300", "ane"] if len(texts) >= big else ["ane", "gb300"]) if e not in order]
    err: Exception | None = None
    for e in order:
        t = time.time()
        try:
            v = ENGINES[e](texts)
        except (urllib.error.URLError, OSError, KeyError, ValueError) as ex:
            with lock:
                stats[e]["errors"] += 1
            err = ex
            continue
        with lock:
            s = stats[e]
            s["requests"] += 1
            s["texts"] += len(texts)
            s["seconds"] += time.time() - t
            last.update(engine=e, at=time.strftime("%FT%T%z"))
        return e, v
    raise RuntimeError(f"no engine answered: {err}")


def health(url: str) -> object:
    try:
        with urllib.request.urlopen(f"{url}/health", timeout=3) as r:
            h = json.load(r)
            return {"status": h.get("status"), "model": h.get("model"), "space": h.get("vector_space") or h.get("vector_space_identity")}
    except Exception as ex:   # noqa: BLE001
        return {"status": "down", "error": str(ex)[:120]}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=11436)
    ap.add_argument("--big", type=int, default=32, help="a batch of at least this many texts goes to gb300 first")
    a = ap.parse_args()

    class H(BaseHTTPRequestHandler):
        def log_message(self, *_: object) -> None:
            pass

        def send(self, code: int, body: object, engine: str | None = None) -> None:
            raw = json.dumps(body).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            if engine:
                self.send_header("X-Embed-Engine", engine)
            self.end_headers()
            self.wfile.write(raw)

        def do_GET(self) -> None:
            p = self.path.split("?")[0]
            if p == "/health":
                self.send(200, {"status": "ok", "model": MODEL, "big": a.big, "last": last, "stats": stats,
                                "engines": {"ane": health(ANE), "gb300": health(GB300)}})
            elif p == "/info":
                try:
                    with urllib.request.urlopen(f"{GB300}/info", timeout=5) as r:
                        self.send(200, json.load(r))
                except Exception:   # noqa: BLE001
                    self.send(200, {"model_id": "none (gb300 down: rerank keeps the given order)"})
            elif p in ("/v1/models", "/api/tags"):
                self.send(200, {"object": "list", "data": [{"id": MODEL, "object": "model"}], "models": [{"name": MODEL, "model": MODEL}]})
            else:
                self.send(404, {"error": "not found"})

        def do_POST(self) -> None:
            p = self.path.split("?")[0]
            if p == "/rerank":
                raw = self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}"
                try:
                    body = json.loads(raw)
                    texts = body.get("texts") or []
                except ValueError:
                    return self.send(400, {"error": "body is not JSON"})
                t = time.time()
                try:
                    out = post(f"{GB300}/rerank", {"query": body.get("query", ""), "texts": texts}, 120)
                    with lock:
                        stats.setdefault("rerank", {"requests": 0, "pairs": 0, "fallbacks": 0, "seconds": 0.0})
                        stats["rerank"]["requests"] += 1
                        stats["rerank"]["pairs"] += len(texts)
                        stats["rerank"]["seconds"] += time.time() - t
                    return self.send(200, out, "gb300")
                except (urllib.error.URLError, OSError, ValueError):
                    with lock:
                        stats.setdefault("rerank", {"requests": 0, "pairs": 0, "fallbacks": 0, "seconds": 0.0})
                        stats["rerank"]["fallbacks"] += 1
                    return self.send(200, [{"index": i, "score": 0.0} for i in range(len(texts))], "none")
            if p not in ("/v1/embeddings", "/api/embed", "/embeddings"):
                return self.send(404, {"error": "not found"})
            try:
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
            except ValueError:
                return self.send(400, {"error": "body is not JSON"})
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

    print(f"embed-router: http://{a.host}:{a.port}  (>= {a.big} texts: gb300 first, else ane first)", flush=True)
    ThreadingHTTPServer((a.host, a.port), H).serve_forever()


if __name__ == "__main__":
    main()
