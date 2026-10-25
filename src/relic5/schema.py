"""schema.py: the hub's Lance tables, each one typed class (LanceDB's Pydantic models; Nat, 2026-10-25: "all queries put
to like a const class ... orm style? ... this style? docs.lancedb.com/integrations/data/pydantic").

  Chunk      what every searchable row carries: where it came from (uid, msgkey, chunk, month, sid), when, who, the text
  LayerRow   a BM25 layer table (prose|tools|thinking|git|memory _ open|history), plus the home it was written in
  VecRow     a vector table (vec_<model>_open|history): the prose rows with their embedding

The indexer checks every table it builds against its class (fts.build -> check): a column renamed or retyped in the
SELECT that feeds it fails the build instead of reaching search. Reading stays on Arrow: a Pydantic object per hit
would cost more than the search (`to_pydantic` is for tools and tests, `Model.of(row)`).
"""
from typing import Optional

import pyarrow as pa
from lancedb.pydantic import LanceModel, Vector

from .types_ import Json


class Chunk(LanceModel):
    uid: str
    msgkey: str
    chunk: int
    key: Optional[str] = None
    month: str
    sid: Optional[str] = None
    ts: Optional[str] = None
    ts_th: Optional[str] = None
    role: Optional[str] = None
    engine: Optional[str] = None
    cat: Optional[str] = None
    layer: Optional[str] = None
    text: Optional[str] = None
    title: Optional[str] = None
    machines: Optional[list[str]] = None

    @classmethod
    def of(cls, row: Json) -> "Chunk":
        """A search hit (a dict) as this model: only the fields the model knows, extra keys (_score, link) left out."""
        return cls(**{k: v for k, v in row.items() if k in cls.model_fields})


class LayerRow(Chunk):
    home: Optional[str] = None     # the .claude/.codex the row was written in (fts.HOME_SQL)
    homes: Optional[str] = None    # every home holding it, newline-joined
    agent: Optional[str] = None    # relic-scan's user@host


def vec_row(dim: int) -> type[Chunk]:
    """The vector table's class for a model of `dim` dimensions."""
    class VecRow(Chunk):
        vector: Vector(dim)  # type: ignore[valid-type]
        chars: int
    VecRow.__name__ = f"VecRow{dim}"
    return VecRow


def model_for(name: str, schema: pa.Schema) -> type[Chunk]:
    if name.startswith("vec_"):
        t = schema.field("vector").type if "vector" in schema.names else None
        return vec_row(t.list_size if isinstance(t, pa.FixedSizeListType) else 0)
    return LayerRow


def _same(a: pa.DataType, b: pa.DataType) -> bool:
    """Arrow types equal for our purpose: a list's item name (item, l) and a float width inside a vector do not matter."""
    if pa.types.is_list(a) and pa.types.is_list(b):
        return _same(a.value_type, b.value_type)
    if isinstance(a, pa.FixedSizeListType) and isinstance(b, pa.FixedSizeListType):
        return bool(a.list_size == b.list_size and pa.types.is_floating(a.value_type) and pa.types.is_floating(b.value_type))
    if pa.types.is_integer(a) and pa.types.is_integer(b):
        return True
    if (pa.types.is_string(a) or pa.types.is_large_string(a)) and (pa.types.is_string(b) or pa.types.is_large_string(b)):
        return True
    return bool(a.equals(b))


def check(name: str, schema: pa.Schema) -> list[str]:
    """What a built table gets wrong against its class: a missing required column, a column of another
    type, a column the class does not know. -> [] when it matches."""
    want: pa.Schema = model_for(name, schema).to_arrow_schema()  # type: ignore[no-untyped-call]
    out = []
    for f in want:
        if f.name not in schema.names:
            if not f.nullable:   # an Optional column may be missing (a table built before it existed)
                out.append(f"{name}: no column {f.name}")
        elif not _same(schema.field(f.name).type, f.type):
            out.append(f"{name}: {f.name} is {schema.field(f.name).type}, the model says {f.type}")
    out += [f"{name}: column {n} is not in {model_for(name, schema).__name__}" for n in schema.names if n not in want.names]
    return out
