"""shim.py: `relic5 mcp`, a stdio MCP server on a Mac that forwards to the hub and embeds semantic queries here.

Nat, 2026-10-23: "MCP embed from m5, from the client". The hub embeds nothing, so an agent's relic_search with
semantic=true and no `vector` would get keyword hits. This shim adds the vector: it encodes the query on this machine
(encode.py, the same model@hash as the hub's vectors) and forwards the call to <hub>/mcp. Everything else passes
through unchanged. Newline-delimited JSON-RPC on stdin/stdout (as agent-relic-v3 src/mcp/server.ts); nothing else
is ever written to stdout.

  claude mcp add -s user relic5 -- <repo>/.venv/bin/relic5 mcp      (needs the `embed` extra: uv sync --extra embed)
"""
import json, os, sys, urllib.request
from typing import Callable, TextIO

from .types_ import Json

Encoder = Callable[[list[str], str], list[list[float]]]
"""encode.encode's shape as add_vector calls it: (texts, model) -> unit vectors."""

MODEL = os.environ.get("RELIC5_MODEL", "unsloth--embeddinggemma-300m@806f5f90")


def forward(url: str, msg: object) -> object:
    req = urllib.request.Request(f"{url}/mcp", data=json.dumps(msg).encode(), headers={"Content-Type": "application/json"})
    tok = os.path.expanduser(os.environ.get("RELIC5_TOKEN_FILE", "~/.config/relic5/token"))
    if os.environ.get("RELIC5_USE_TOKEN") and os.path.exists(tok):
        req.add_header("Authorization", "Bearer " + open(tok).read().strip())
    with urllib.request.urlopen(req, timeout=180) as r:
        body = r.read()
    return json.loads(body) if body else None


def add_vector(msg: Json, encode: Encoder | None = None) -> Json:
    """A semantic relic_search with no vector gets one; anything else is returned as is."""
    p = msg.get("params") or {}
    a = p.get("arguments") or {}
    if msg.get("method") != "tools/call" or p.get("name") != "relic_search" or not a.get("semantic") or "vector" in a:
        return msg
    vec = None
    if encode is not None:
        vec = encode([a.get("query", "")], a.get("model") or MODEL)[0]
    else:   # query engines in policy order (Nat: "can we do query embed ane too?"): ANE, then MPS, then keyword
        from .encode import encode as enc
        from .worker import policy
        for eng in policy()["query"]:
            try:
                vec = enc([a.get("query", "")], a.get("model") or MODEL, engine=eng)[0]
                break
            except Exception as ex:
                print(f"relic5 mcp: query embedding on {eng} failed ({type(ex).__name__}: {ex})", file=sys.stderr)
    if vec is None:   # no engine answered: the hub answers by keyword and says so in `note`
        return msg
    a = {k: v for k, v in a.items() if k != "model"} | {"vector": vec}
    return msg | {"params": p | {"arguments": a}}


def serve(url: str, stdin: TextIO = sys.stdin, stdout: TextIO = sys.stdout, encode: Encoder | None = None) -> None:
    for line in stdin:
        if not line.strip():
            continue
        try:
            msg = json.loads(line)
        except ValueError:
            stdout.write(json.dumps({"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "parse error"}}) + "\n")
            stdout.flush()
            continue
        try:
            out = forward(url, add_vector(msg, encode) if isinstance(msg, dict) else msg)
        except Exception as ex:
            out = None if isinstance(msg, dict) and "id" not in msg else \
                {"jsonrpc": "2.0", "id": msg.get("id") if isinstance(msg, dict) else None, "error": {"code": -32603, "message": f"hub unreachable: {ex}"}}
        if out is not None:
            stdout.write(json.dumps(out, ensure_ascii=False) + "\n")
            stdout.flush()
