"""encode.py: embed text on a client (a Mac: MPS; anything else: CPU). The hub never runs this.

The settings must be the vectors' own, or the cosine means nothing: for gemma-300m@806f5f90 they are relic4's
(agent-relic-v4 src/relic4/embed.py MODELS, PR #6 @b399119): doc_prompt "document", query_prompt "query",
max_seq 2048, L2-normalised. Query encoding is relic4's core.Relic.encode: SentenceTransformer, prompt_name "query" when
the model has it, normalize_embeddings=True. Needs the `embed` extra (sentence-transformers, torch); the model comes
from the local Hugging Face cache (HF_HUB_OFFLINE=1, as relic4).
"""
import os
from typing import TYPE_CHECKING, Iterable, TypedDict

if TYPE_CHECKING:
    from sentence_transformers import SentenceTransformer


class ModelSettings(TypedDict):
    name: str
    doc_prompt: str
    query_prompt: str
    max_seq: int


MODELS: dict[str, ModelSettings] = {"unsloth--embeddinggemma-300m@806f5f90": dict(name="unsloth/embeddinggemma-300m", doc_prompt="document",
                                                       query_prompt="query", max_seq=2048)}
_cache: dict[str, "SentenceTransformer"] = {}


def _model(model: str) -> "SentenceTransformer":
    if model not in MODELS:
        raise SystemExit(f"no local settings for {model} (have {', '.join(MODELS)})")
    if model not in _cache:
        os.environ.setdefault("HF_HUB_OFFLINE", "1")
        import torch
        from sentence_transformers import SentenceTransformer
        dev = "mps" if torch.backends.mps.is_available() else "cpu"
        m = SentenceTransformer(MODELS[model]["name"], device=dev)
        m.max_seq_length = MODELS[model]["max_seq"]
        _cache[model] = m
    return _cache[model]


ANE_URL = os.environ.get("RELIC5_ANE_URL", "http://127.0.0.1:11435")   # ANEEmbedBar (ane-oracle/tools/ane-embed-app)
ANE_MODEL = {"unsloth--embeddinggemma-300m@806f5f90": "embeddinggemma:ane-w8a16"}
PROMPT = {"query": "task: search result | query: ", "document": "title: none | text: "}   # gemma's own prompt strings


def encode_ane(texts: list[str], model: str, kind: str = "query", batch: int = 64) -> list[list[float]]:
    """The same model on the Neural Engine, over ANEEmbedBar's /api/embed. The prompt is sent in the text (the engine
    takes raw input); w8a16 weights, so whether these vectors may share model@hash is decided by `relic5 embed --probe
    --engine ane`, never assumed."""
    import json, math, urllib.request
    out: list[list[float]] = []
    for i in range(0, len(texts), batch):
        body = {"model": ANE_MODEL[model], "input": [PROMPT[kind] + t for t in texts[i:i + batch]]}
        req = urllib.request.Request(f"{ANE_URL}/api/embed", data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
        for v in json.load(urllib.request.urlopen(req, timeout=300))["embeddings"]:
            n = math.sqrt(sum(x * x for x in v)) or 1.0
            out.append([x / n for x in v])
    return out


def encode(texts: Iterable[str], model: str, kind: str = "query", engine: str | None = None) -> list[list[float]]:
    """-> list of unit vectors (lists of float). kind = query | document; engine = mps (sentence-transformers here,
    the default) | ane (ANEEmbedBar on this Mac) | ane2 (Neural Engine + GPU in-process, ane2.py). RELIC5_ENGINE sets
    the default."""
    engine = engine or os.environ.get("RELIC5_ENGINE", "mps")
    if engine == "ane2":
        from . import ane2
        return ane2.encode(list(texts), model, kind)
    if engine == "ane":
        return encode_ane(list(texts), model, kind)
    m = _model(model)
    p = MODELS[model]["query_prompt" if kind == "query" else "doc_prompt"]
    # prompt_name=None is encode's own default (its default prompt), the same as not passing it
    return [v.tolist() for v in m.encode(list(texts), normalize_embeddings=True, batch_size=64,
                                         prompt_name=p if p in (m.prompts or {}) else None)]
