"""encode.py: embed text on a client (a Mac: MPS; anything else: CPU). The hub never runs this.

The settings must be the vectors' own, or the cosine means nothing: for gemma-300m@806f5f90 they are relic4's
(agent-relic-v4 src/relic4/embed.py MODELS, PR #6 @b399119): doc_prompt "document", query_prompt "query",
max_seq 2048, L2-normalised. Query encoding is relic4's core.Relic.encode: SentenceTransformer, prompt_name "query" when
the model has it, normalize_embeddings=True. Needs the `embed` extra (sentence-transformers, torch); the model comes
from the local Hugging Face cache (HF_HUB_OFFLINE=1, as relic4).
"""
import os

MODELS = {"unsloth--embeddinggemma-300m@806f5f90": dict(name="unsloth/embeddinggemma-300m", doc_prompt="document",
                                                       query_prompt="query", max_seq=2048)}
_cache = {}


def _model(model):
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


def encode(texts, model, kind="query"):
    """-> list of unit vectors (lists of float). kind = query | document."""
    m = _model(model)
    p = MODELS[model][f"{'query' if kind == 'query' else 'doc'}_prompt"]
    kw = {"prompt_name": p} if p in (m.prompts or {}) else {}
    return [v.tolist() for v in m.encode(list(texts), normalize_embeddings=True, batch_size=64, **kw)]
