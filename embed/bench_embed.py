# /// script
# requires-python = ">=3.11"
# dependencies = ["sentence-transformers>=5", "torch", "pyarrow", "numpy"]
# ///
"""bench_embed.py: one embedding benchmark, the same code and the same texts on every machine.

    just bench-embed            m5: ANE, GPU (MPS), ANE+GPU split (engine ane2), and sentence-transformers on MPS
    just bench-embed-gb300      gb300: sentence-transformers on CUDA, bfloat16 (as the stored vectors) and float32
    just bench-embed-compare    one table from both machines, plus parity of every engine's vectors against gb300 bf16

Model: embeddinggemma-300m with its document prompt, max_seq 2048, normalized (relic5 encode.py's settings).
Texts: a parquet with a `text` column (the chunks the hub was missing on 2026-10-29). Per engine it measures:
  load       seconds from nothing to the first vector (imports, weights, compile)
  batch      texts/s on all texts and on 9 copies of them (2 runs each, after a warm-up)
  query      single-text latency, warm, 20 queries (what a search pays)
  memory     peak resident memory of this process (and GPU memory on CUDA)
  power      on CUDA: mean GPU power while embedding (nvidia-smi), so J per 1,000 texts
It saves each engine's vectors for the 2,252 texts (.npy) so --compare can measure parity across machines.
Prints numbers only, never text.
"""
import argparse
import json
import os
import platform
import resource
import subprocess
import sys
import threading
import time
from pathlib import Path

import numpy as np

MODEL, KEY = "unsloth/embeddinggemma-300m", "unsloth--embeddinggemma-300m@806f5f90"


def log(*a):
    print(*a, flush=True)


def rss_mb():
    r = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return r / 2**20 if sys.platform == "darwin" else r / 1024     # macOS: bytes, Linux: KB


class GpuPower:
    """sample nvidia-smi power.draw every 0.2 s while running"""

    def __init__(self):
        self.samples, self.on = [], False

    def __enter__(self):
        self.on = True
        threading.Thread(target=self.loop, daemon=True).start()
        return self

    def loop(self):
        while self.on:
            try:
                out = subprocess.run(["nvidia-smi", "--query-gpu=power.draw", "--format=csv,noheader,nounits"],
                                     capture_output=True, text=True, timeout=5).stdout.split()
                self.samples.append(float(out[0]))
            except Exception:
                pass
            time.sleep(0.2)

    def __exit__(self, *a):
        self.on = False

    def mean(self):
        return round(float(np.mean(self.samples)), 1) if self.samples else None


def st_engine(device, dtype):
    """sentence-transformers, as relic5 encode.py / relic4 remote_embed.py call it"""
    def load():
        os.environ.setdefault("HF_HUB_OFFLINE", "1")
        import torch
        from sentence_transformers import SentenceTransformer
        m = SentenceTransformer(MODEL, device=device, model_kwargs={"torch_dtype": getattr(torch, dtype)})
        m.max_seq_length = 2048
        batch = 512 if device == "cuda" else 64
        sync = torch.cuda.synchronize if device == "cuda" else (torch.mps.synchronize if device == "mps" else lambda: None)

        def enc(texts):
            v = m.encode(texts, batch_size=batch, normalize_embeddings=True, convert_to_numpy=True,
                         show_progress_bar=False, prompt_name="document")
            sync()
            return v
        return enc
    return load


def ane2_engine(mode, src):
    def load():
        sys.path.insert(0, src)
        from relic5 import ane2
        return lambda texts: np.asarray(ane2.encode(texts, KEY, "document", mode=mode), dtype=np.float32)
    return load


def engines(a):
    if a.machine == "gb300":
        return {"gb300 CUDA bf16": st_engine("cuda", "bfloat16"), "gb300 CUDA fp32": st_engine("cuda", "float32")}
    return {"m5 ANE": ane2_engine("ane", a.ane2), "m5 GPU (MPS)": ane2_engine("gpu", a.ane2),
            "m5 ANE+GPU (0.7/0.3)": ane2_engine("split", a.ane2), "m5 MPS sentence-transformers": st_engine("mps", "float32")}


def run(a):
    import pyarrow.parquet as pq
    texts = pq.read_table(a.texts).column("text").to_pylist()
    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
    eng = engines(a)
    if a.only:
        eng = {k: v for k, v in eng.items() if k in a.only.split(",")}
    res = {"machine": a.machine, "host": platform.node(), "platform": platform.platform(), "texts": len(texts),
           "started": time.strftime("%Y-%m-%d %H:%M:%S"), "engines": []}
    try:
        import torch
        res["torch"] = torch.__version__
        res["cuda"] = torch.version.cuda
    except Exception:
        pass
    sizes = [("all", texts), ("x9", texts * 9)]
    steps = len(eng) * (1 + 2 * len(sizes) + 1)
    done, t_all = 0, time.time()

    def step(label):
        nonlocal done
        done += 1
        el = time.time() - t_all
        left = el / done * (steps - done)
        log(f"[{done}/{steps}] {100 * done / steps:.0f}% time {el / 60:.1f}/{(el + left) / 60:.1f} min, "
            f"{left / 60:.1f} min left, ETA {time.strftime('%H:%M', time.localtime(time.time() + left))} · {label}")

    for name, make in eng.items():
        r = {"engine": name}
        t = time.time(); enc = make(); v = enc(texts[:1]); r["load_s"] = round(time.time() - t, 1)
        enc(texts[:64])                                                   # warm-up: shapes, kernels
        step(f"{name} loaded in {r['load_s']} s")
        for label, tx in sizes:
            rates, watts = [], []
            for rep in range(2):
                with GpuPower() if a.machine == "gb300" else _Null() as p:
                    t = time.time(); vec = enc(tx); s = time.time() - t
                rates.append(round(len(tx) / s, 1))
                if a.machine == "gb300":
                    watts.append(p.mean())
                if label == "all" and rep == 0:
                    np.save(out / f"vec-{name.replace(' ', '_').replace('/', '-')}.npy", np.asarray(vec, dtype=np.float32))
                step(f"{name} {label} ({len(tx):,}) run {rep + 1}: {rates[-1]:,} texts/s")
            r[f"rate_{label}"] = rates
            if watts and watts[0]:
                r[f"gpu_watts_{label}"] = watts
                r[f"joules_per_1k_{label}"] = round(float(np.mean(watts)) / float(np.mean(rates)) * 1000, 1)
        lat = []
        for q in texts[100:120]:
            t = time.perf_counter(); enc([q[:200]]); lat.append((time.perf_counter() - t) * 1000)
        r["query_p50_ms"], r["query_max_ms"] = round(float(np.median(lat)), 1), round(max(lat), 1)
        r["peak_rss_mb"] = round(rss_mb())
        if a.machine == "gb300":
            import torch
            r["peak_gpu_mb"] = round(torch.cuda.max_memory_allocated() / 2**20)
        step(f"{name} query p50 {r['query_p50_ms']} ms")
        res["engines"].append(r)
        (out / f"{a.machine}.json").write_text(json.dumps(res, indent=1))
    log(f"results -> {out / (a.machine + '.json')}")


class _Null:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        pass


def compare(d, idle=None):
    """idle: the GPU's own idle draw (W) on gb300, measured separately; J/1k is then the energy ABOVE idle"""
    d = Path(d)
    rows = []
    for f in ("m5.json", "gb300.json"):
        if (d / f).exists():
            rows += json.loads((d / f).read_text())["engines"]
    def unit(v):   # bfloat16 output is normalized in bfloat16: its length is not exactly 1, so normalize again here
        v = np.asarray(v, dtype=np.float64)
        return v / np.linalg.norm(v, axis=1, keepdims=True)

    ref = unit(np.load(d / "vec-gb300_CUDA_bf16.npy"))
    print(f"{'engine':30s}{'load s':>7s}{'2,252/s':>9s}{'20,268/s':>10s}{'query ms':>9s}{'RSS MB':>8s}"
          f"{'J/1k':>7s}{'cos p05':>9s}{'cos min':>9s}")
    for r in rows:
        f = d / f"vec-{r['engine'].replace(' ', '_').replace('/', '-')}.npy"
        c = np.sort((unit(np.load(f)) * ref).sum(1)) if f.exists() else None
        p05 = f"{c[len(c) // 20]:.4f}" if c is not None else "-"
        mn = f"{c[0]:.4f}" if c is not None else "-"
        j = r.get("joules_per_1k_x9", "-")
        if idle and r.get("gpu_watts_x9"):
            j = round((float(np.mean(r["gpu_watts_x9"])) - idle) / float(np.mean(r["rate_x9"])) * 1000, 1)
        print(f"{r['engine']:30s}{r['load_s']:7.1f}{max(r['rate_all']):9,.1f}{max(r['rate_x9']):10,.1f}"
              f"{r['query_p50_ms']:9.1f}{r['peak_rss_mb']:8,d}{j!s:>7s}{p05:>9s}{mn:>9s}")
    print("rates: best of 2 runs · cos: each engine's vectors vs gb300 bf16 (the stored vectors' engine) on the same texts")
    print(f"J/1k: gb300 GPU energy per 1,000 texts on the 20,268 run" + (f", above its {idle:g} W idle" if idle else " (total draw)"))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--texts")
    ap.add_argument("--out", default="/tmp/bench-embed")
    ap.add_argument("--machine", choices=["m5", "gb300"])
    ap.add_argument("--ane2", default="src", help="m5: relic5 source dir for engine ane2")
    ap.add_argument("--only", default="")
    ap.add_argument("--compare")
    ap.add_argument("--idle-watts", type=float, help="--compare: gb300 GPU idle draw to subtract")
    a = ap.parse_args()
    compare(a.compare, a.idle_watts) if a.compare else run(a)
