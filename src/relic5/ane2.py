"""ane2.py: embeddinggemma-300m on this Mac's Neural Engine and GPU at once, in-process (engine "ane2").

The `ane` engine needs ANEEmbedBar listening on 11435; it stopped autostarting on 2026-10-26 and `relic5 embed` failed
with Connection refused. ane2 needs no app and no port: it loads ANEEmbedBar's compiled Core ML packages itself and runs
the GPU beside them. The method is facebook-oracle's (scripts/engines.py, 2026-10-28):

  1. Length buckets: texts sorted by token length and cut into the packages' (batch, seq) shapes. The Neural Engine
     runs fixed shapes; the GPU pads a batch only to its longest text.
  2. Neural Engine and GPU as TWO PROCESSES (a Core ML call holds the other Python threads). Batches are dealt by the
     golden-ratio sequence, so each share gets an even mix of lengths; the split follows the measured speeds.

Neural Engine half: ANEEmbedBar's packages (ane-oracle tools/ane-embed-app, ~/Library/Application Support/ANEEmbed/
embeddinggemma-w16): the token table lookup on the CPU (embed_scaled.f16), the 24 layers on the ANE in its own layout
(1x1 conv, per-head einsum; out: hidden [B, 768, 1, S]), then mean pooling and the two Dense layers here in float32.
A plain trace of the same model converted for the ANE was tried first (2026-10-29): correct on CPU/GPU (cos p05
0.99965 vs sentence-transformers) but p05 0.9886 on the ANE itself; these packages give 0.99928 on the same texts.
GPU half: the sentence-transformers stack in torch on MPS, float32 (net()).
Prompts are gemma's own (encode.PROMPT). Whether the vectors match the stored ones is `relic5 embed --probe --engine
ane2`, never assumed.
"""
import json
import os
import time
from concurrent.futures import ProcessPoolExecutor
from multiprocessing import get_context
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

if TYPE_CHECKING:
    import torch

PHI = 0.6180339887498949
HF = {"unsloth--embeddinggemma-300m@806f5f90": "unsloth/embeddinggemma-300m"}
ASSETS = Path(os.path.expanduser(os.environ.get("RELIC5_ANE2_ASSETS",
                                                "~/Library/Application Support/ANEEmbed/embeddinggemma-w16")))
NEG = -1e4   # additive mask
# The Neural Engine's share of the batches in split mode. Measured on m5 (2026-10-29, 2,252 real chunks, texts/s):
# GPU alone 83.7, ANE alone 99.1; split at 0.3 134.6, 0.5 101.0/137.3/191.9, 0.6 174.6/137.9,
# 0.7 151.6/151.9/151.1, 0.8 131.5/132.1. 0.7 is the best mean, and the steadiest.
ANE_SHARE = 0.7


def buckets() -> tuple[tuple[int, int], ...]:
    """(batch, seq) per package, from the manifest: packages/w16-<seq>x<batch>.mlpackage."""
    man = json.loads((ASSETS / "manifest.json").read_text())
    return tuple((int(Path(name).stem.split("x")[-1]), int(seq))
                 for seq, name in sorted(man["packages"].items(), key=lambda kv: int(kv[0])))


def net(model: str) -> "torch.nn.Module":
    """The sentence-transformers stack as one torch module: (input_ids, attention_mask) -> unit vectors [batch, 768].
    Gemma3 is bidirectional here; the masks are passed in ready-made (Gemma3TextModel accepts a dict): padding, and on
    the sliding layers |q - kv| >= sliding_window as well (transformers' bidirectional overlay, exclusive)."""
    import torch
    if model not in HF:
        raise SystemExit(f"ane2: no settings for {model} (have {', '.join(HF)})")
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    from sentence_transformers import SentenceTransformer
    st = SentenceTransformer(HF[model], device="cpu", model_kwargs={"attn_implementation": "sdpa"})
    gemma: Any = st[0].auto_model                     # Gemma3TextModel
    d1: Any = st[2].linear                            # Dense 768 -> 3072
    d2: Any = st[3].linear                            # Dense 3072 -> 768
    window = int(gemma.config.sliding_window)

    class Pooled(torch.nn.Module):
        def __init__(self) -> None:
            super().__init__()
            self.gemma, self.d1, self.d2 = gemma, d1, d2

        def forward(self, input_ids: torch.Tensor, attention_mask: torch.Tensor) -> torch.Tensor:
            s = input_ids.shape[1]
            keep = attention_mask.to(torch.float32)
            full = ((1.0 - keep) * NEG)[:, None, None, :]
            sliding = full
            if s > window:
                i = torch.arange(s, device=input_ids.device)
                sliding = full + ((i[:, None] - i[None, :]).abs() >= window).to(torch.float32)[None, None] * NEG
            pos = torch.arange(s, device=input_ids.device)[None].expand_as(input_ids)
            h = self.gemma(input_ids=input_ids, position_ids=pos,
                           attention_mask={"full_attention": full, "sliding_attention": sliding}).last_hidden_state
            w = keep.to(h.dtype)[..., None]
            v = self.d2(self.d1((h * w).sum(1) / w.sum(1).clamp(min=1.0)))
            return torch.nn.functional.normalize(v, dim=-1)

    return Pooled().eval()


def tokenizer(model: str) -> Any:
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    from transformers import AutoTokenizer
    tok = AutoTokenizer.from_pretrained(HF[model])
    tok.padding_side = "right"
    return tok


class Engine:
    """One engine: 'ane' (ANEEmbedBar's packages on the Neural Engine, fixed shapes) or 'gpu' (torch on MPS)."""

    def __init__(self, kind: str, model: str) -> None:
        import numpy as np
        self.kind, self.model, self.buckets = kind, model, buckets()
        self.tok = tokenizer(model)
        if kind == "gpu":
            self.net = net(model).to("mps")
            return
        import coremltools as ct
        man = json.loads((ASSETS / "manifest.json").read_text())
        if man["hf_model"] != HF[model]:
            raise SystemExit(f"ane2: {ASSETS} holds {man['hf_model']}, not {HF[model]}")
        self.ml = {s: ct.models.CompiledMLModel(str(ASSETS / "compiled" / f"{s}.mlmodelc"), ct.ComputeUnit.CPU_AND_NE)
                   for _, s in self.buckets}
        self.table = np.memmap(ASSETS / "embed_scaled.f16", dtype=np.float16, mode="r").reshape(man["vocab"], man["hidden"])
        self.d1 = np.fromfile(ASSETS / "dense1.f32", dtype=np.float32).reshape(man["dense1"])
        self.d2 = np.fromfile(ASSETS / "dense2.f32", dtype=np.float32).reshape(man["dense2"])

    def jobs(self, texts: list[str]) -> list[tuple[int, int, list[int]]]:
        """Bucketed jobs over all texts: [(batch, seq, [row indices])], shortest first."""
        top = self.buckets[-1][1]
        lens = [len(x) for x in self.tok(texts, truncation=True, max_length=top)["input_ids"]]
        groups: dict[tuple[int, int], list[int]] = {bs: [] for bs in self.buckets}
        for i in sorted(range(len(texts)), key=lambda i: lens[i]):
            groups[next((bs for bs in self.buckets if lens[i] <= bs[1]), self.buckets[-1])].append(i)
        return [(b, s, idx[k:k + b]) for (b, s), idx in groups.items() for k in range(0, len(idx), b)]

    def run(self, ids: Any, mask: Any) -> Any:
        import numpy as np
        if self.kind == "gpu":
            import torch
            with torch.no_grad():
                return self.net(torch.tensor(ids, device="mps").long(), torch.tensor(mask, device="mps").long()).float().cpu().numpy()
        out = self.ml[ids.shape[1]].predict({"embeds": self.table[ids], "mask": mask.astype(np.float16)})
        h = np.asarray(out["hidden"], dtype=np.float32)[:, :, 0, :]          # [B, 768, S]
        w = mask.astype(np.float32)[:, None, :]
        v = ((h * w).sum(2) / np.maximum(w.sum(2), 1.0)) @ self.d1 @ self.d2
        return v / np.maximum(np.linalg.norm(v, axis=1, keepdims=True), 1e-12)

    def encode(self, texts: list[str], share: tuple[float, float] = (0.0, 1.0),
               tick: Callable[[int], None] | None = None) -> tuple[list[int], list[list[float]]]:
        """Vectors for this engine's share of the batches: (row indices, unit vectors). texts carry their prompt."""
        import numpy as np
        lo, hi = share
        rows: list[int] = []
        out: list[list[float]] = []
        for n, (b, s, part) in enumerate(self.jobs(texts)):
            if not lo <= (n * PHI) % 1 < hi:
                continue
            batch = [texts[j] for j in part]
            if self.kind == "gpu":   # the GPU takes any shape: pad only to the longest text in the batch
                enc = self.tok(batch, padding="longest", truncation=True, max_length=s, return_tensors="np")
            else:                    # the Neural Engine needs the package's fixed (batch, seq)
                enc = self.tok(batch + [""] * (b - len(part)), padding="max_length", truncation=True, max_length=s,
                               return_tensors="np")
            v = self.run(enc["input_ids"].astype(np.int32), enc["attention_mask"].astype(np.int32))[:len(part)]
            rows += part
            out += v.tolist()
            if tick:
                tick(len(part))
        return rows, out


_engines: dict[str, Engine] = {}


def _share(kind: str, model: str, texts: list[str], share: tuple[float, float]) -> tuple[list[int], list[list[float]], float]:
    """One engine's share, in whichever process runs it (the engine is kept for the next call)."""
    if kind not in _engines:
        _engines[kind] = Engine(kind, model)
    t = time.time()
    rows, vecs = _engines[kind].encode(texts, share)
    return rows, vecs, time.time() - t


_pool: ProcessPoolExecutor | None = None


def encode(texts: list[str], model: str, kind: str = "document", mode: str | None = None,
           ane_share: float | None = None) -> list[list[float]]:
    """-> unit vectors in input order. mode: split (Neural Engine in a child process + GPU here, the default) | ane | gpu.
    ane_share: the Neural Engine's fraction of the batches in split mode (RELIC5_ANE2_SHARE, default ANE_SHARE)."""
    from .encode import PROMPT
    global _pool
    mode = mode or os.environ.get("RELIC5_ANE2_MODE", "split")
    texts = [PROMPT[kind] + t for t in texts]
    if mode in ("ane", "gpu"):
        rows, vecs, _ = _share(mode, model, texts, (0.0, 1.0))
    else:
        a = float(ane_share if ane_share is not None else os.environ.get("RELIC5_ANE2_SHARE", ANE_SHARE))
        if _pool is None:
            _pool = ProcessPoolExecutor(max_workers=1, mp_context=get_context("spawn"))
        far = _pool.submit(_share, "ane", model, texts, (0.0, a))
        rows, vecs, _ = _share("gpu", model, texts, (a, 1.0))
        r2, v2, _ = far.result()
        rows, vecs = rows + r2, vecs + v2
    out: list[list[float]] = [[] for _ in texts]
    for i, v in zip(rows, vecs):
        out[i] = v
    return out
