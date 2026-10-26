# /// script
# requires-python = ">=3.11"
# dependencies = ["sentence-transformers>=3", "torch", "numpy"]
# ///
"""gb300-serve.py: embeddinggemma-300m on gb300's GPU (bf16) behind HTTP, the same vector space relic5 already mixes
with m5's ANE (relic5 worker.py: ANE shards and gb300 shards share unsloth--embeddinggemma-300m@806f5f90 after the
parity probe). Raw texts in, L2-normalised vectors out: the caller puts gemma's prompt in the text, as with the ANE
service ("task: search result | query: " / "title: none | text: ").

  uv run gb300-serve.py [--port 11437] [--host 127.0.0.1] [--batch 256] [--rerank BAAI/bge-reranker-v2-m3]

  GET  /health          {"status", "model", "vector_space", "dims", "device", "dtype", "stats"}
  POST /api/embed       {"model"?, "input": str | [str]}  -> {"model", "embeddings": [[...]]}          (Ollama, ANE service)
  POST /v1/embeddings   {"model"?, "input": str | [str]}  -> {"object": "list", "data": [{"embedding", "index"}], ...} (OpenAI)
  GET  /info            {"model_id"}                                  (TEI; the reranker, when --rerank is given)
  POST /rerank          {"query", "texts": [str]} -> [{"index", "score"}] best first (TEI, Hindsight's "tei" reranker)

Bound to 127.0.0.1: m5 reaches it through an ssh tunnel (embed/start.sh). Started by hand, never by a timer.
"""
import argparse, json, threading, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

MODEL = "unsloth/embeddinggemma-300m"
SPACE = "unsloth--embeddinggemma-300m@806f5f90"   # relic5 encode.py MODELS key: one name for the vector space
MAX_INPUTS = 4096
lock = threading.Lock()
stats = {"requests": 0, "texts": 0, "seconds": 0.0, "errors": 0}


def torch_sigmoid():
    import torch
    return torch.nn.Sigmoid()


def load(batch: int):
    import torch
    from sentence_transformers import SentenceTransformer
    m = SentenceTransformer(MODEL, device="cuda", model_kwargs={"torch_dtype": torch.bfloat16})
    m.max_seq_length = 2048
    return m


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=11437)
    ap.add_argument("--batch", type=int, default=256)
    ap.add_argument("--rerank", default="", help="a cross-encoder for /rerank, e.g. BAAI/bge-reranker-v2-m3 (multilingual)")
    a = ap.parse_args()
    model = load(a.batch)
    dims = model.get_embedding_dimension() if hasattr(model, "get_embedding_dimension") else model.get_sentence_embedding_dimension()
    ranker = None
    if a.rerank:
        import torch
        from sentence_transformers import CrossEncoder
        ranker = CrossEncoder(a.rerank, device="cuda", max_length=1024, model_kwargs={"torch_dtype": torch.bfloat16})
    rlock = threading.Lock()

    def rerank(query: str, texts: list[str]) -> list[dict]:
        t = time.time()
        with rlock:
            scores = ranker.predict([(query, x) for x in texts], batch_size=64, show_progress_bar=False, activation_fn=torch_sigmoid())
        stats["rerank_requests"] = stats.get("rerank_requests", 0) + 1
        stats["rerank_pairs"] = stats.get("rerank_pairs", 0) + len(texts)
        stats["rerank_seconds"] = stats.get("rerank_seconds", 0.0) + time.time() - t
        return sorted(({"index": i, "score": float(sc)} for i, sc in enumerate(scores)), key=lambda r: -r["score"])

    def embed(texts: list[str]) -> list[list[float]]:
        t = time.time()
        with lock:   # one GPU model; requests queue here
            v = model.encode(texts, batch_size=a.batch, normalize_embeddings=True, convert_to_numpy=True, show_progress_bar=False)
        stats["requests"] += 1
        stats["texts"] += len(texts)
        stats["seconds"] += time.time() - t
        return v.astype("float32").tolist()

    class H(BaseHTTPRequestHandler):
        def log_message(self, *_: object) -> None:
            pass

        def send(self, code: int, body: object) -> None:
            raw = json.dumps(body).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def do_GET(self) -> None:
            p = self.path.split("?")[0]
            if p == "/health":
                self.send(200, {"status": "ok", "model": MODEL, "vector_space": SPACE, "dims": dims, "device": "cuda",
                                "dtype": "bfloat16", "max_inputs": MAX_INPUTS, "reranker": a.rerank or None, "stats": stats})
            elif p == "/info" and ranker is not None:
                self.send(200, {"model_id": a.rerank, "model_type": {"reranker": {}}, "max_input_length": 1024})
            else:
                self.send(404, {"error": "not found"})

        def do_POST(self) -> None:
            path = self.path.split("?")[0]
            if path == "/rerank":
                if ranker is None:
                    return self.send(404, {"error": "no reranker (start with --rerank MODEL)"})
                try:
                    body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
                    q, texts = body.get("query"), body.get("texts")
                    if not isinstance(q, str) or not isinstance(texts, list) or not all(isinstance(t, str) for t in texts):
                        return self.send(400, {"error": "query must be a string and texts a list of strings"})
                    return self.send(200, rerank(q, texts) if texts else [])
                except Exception as ex:   # noqa: BLE001
                    stats["errors"] += 1
                    return self.send(500, {"error": str(ex)[:300]})
            if path not in ("/api/embed", "/v1/embeddings"):
                return self.send(404, {"error": "not found"})
            try:
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
                texts = body.get("input")
                texts = [texts] if isinstance(texts, str) else texts
                if not isinstance(texts, list) or not all(isinstance(t, str) for t in texts):
                    return self.send(400, {"error": "input must be a string or a list of strings"})
                if len(texts) > MAX_INPUTS:
                    return self.send(413, {"error": f"at most {MAX_INPUTS} inputs"})
                vecs = embed(texts) if texts else []
            except Exception as ex:   # noqa: BLE001 - report, keep serving
                stats["errors"] += 1
                return self.send(500, {"error": str(ex)[:300]})
            if path == "/api/embed":
                self.send(200, {"model": MODEL, "embeddings": vecs})
            else:
                n = sum(len(t) for t in texts)
                self.send(200, {"object": "list", "model": MODEL, "usage": {"prompt_tokens": n, "total_tokens": n},
                                "data": [{"object": "embedding", "index": i, "embedding": v} for i, v in enumerate(vecs)]})

    print(f"gb300-serve: {MODEL} bf16 cuda, {dims} dims" + (f", reranker {a.rerank}" if a.rerank else "") + f", http://{a.host}:{a.port}", flush=True)
    ThreadingHTTPServer((a.host, a.port), H).serve_forever()


if __name__ == "__main__":
    main()
