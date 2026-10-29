"""ane2's bookkeeping, without a model: buckets from the manifest, length bucketing, and the golden-ratio split that
deals each batch to exactly one engine (the vectors themselves are checked by `relic5 embed --probe --engine ane2`)."""
import json
from typing import Any

import numpy as np

from relic5 import ane2


class WordTok:
    """A stand-in tokenizer: one token per word, cut at max_length."""

    def __call__(self, texts: list[str], truncation: bool = True, max_length: int = 0, **kw: Any) -> Any:
        ids = [[1] * min(len(t.split()), max_length) for t in texts]
        if "return_tensors" not in kw:
            return {"input_ids": ids}
        width = max_length if kw.get("padding") == "max_length" else max(map(len, ids))
        rows = [x + [0] * (width - len(x)) for x in ids]
        return {"input_ids": np.array(rows), "attention_mask": (np.array(rows) > 0).astype(int)}


def engine(monkeypatch: Any, tmp_path: Any) -> ane2.Engine:
    man = {"packages": {"32": "packages/w16-32x64.mlpackage", "64": "packages/w16-64x32.mlpackage",
                        "2048": "packages/w16-2048x1.mlpackage"}}
    (tmp_path / "manifest.json").write_text(json.dumps(man))
    monkeypatch.setattr(ane2, "ASSETS", tmp_path)
    e = ane2.Engine.__new__(ane2.Engine)
    e.kind, e.model, e.buckets, e.tok = "ane", "m", ane2.buckets(), WordTok()
    return e


def test_buckets_come_from_the_manifest(monkeypatch: Any, tmp_path: Any) -> None:
    assert engine(monkeypatch, tmp_path).buckets == ((64, 32), (32, 64), (1, 2048))


def test_jobs_put_each_text_in_the_smallest_bucket_that_holds_it(monkeypatch: Any, tmp_path: Any) -> None:
    e = engine(monkeypatch, tmp_path)
    texts = ["w " * 10, "w " * 40, "w " * 3000, "w " * 5]
    jobs = e.jobs(texts)
    seq = {i: s for _, s, part in jobs for i in part}
    assert seq == {0: 32, 1: 64, 2: 2048, 3: 32}
    assert [i for _, s, part in jobs if s == 32 for i in part] == [3, 0]   # shortest first


def test_golden_split_deals_every_batch_to_exactly_one_engine(monkeypatch: Any, tmp_path: Any) -> None:
    e = engine(monkeypatch, tmp_path)
    texts = [("w " * (1 + i % 70)) for i in range(1000)]
    e.run = lambda ids, mask: np.ones((len(ids), 1))   # type: ignore[method-assign]
    for a in (0.0, 0.3, 0.5, 1.0):
        ane_rows, _ = e.encode(texts, (0.0, a))
        gpu_rows, _ = e.encode(texts, (a, 1.0))
        assert sorted(ane_rows + gpu_rows) == list(range(1000))
