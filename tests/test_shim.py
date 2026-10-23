import io, json

from relic5 import shim


def fake_encode(texts, model):
    return [[0.6, 0.8] for _ in texts]


def test_semantic_search_gets_a_vector():
    m = {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "relic_search", "arguments": {"query": "x", "semantic": True, "model": "m"}}}
    a = shim.add_vector(m, fake_encode)["params"]["arguments"]
    assert a["vector"] == [0.6, 0.8] and "model" not in a and a["semantic"]


def test_everything_else_passes_through():
    for m in ({"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
              {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "relic_search", "arguments": {"query": "x"}}},
              {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "relic_search", "arguments": {"query": "x", "semantic": True, "vector": [1]}}}):
        assert shim.add_vector(m, fake_encode) == m


def test_serve_forwards_and_reports_an_unreachable_hub(monkeypatch):
    sent = []
    monkeypatch.setattr(shim, "forward", lambda url, msg: sent.append(msg) or {"jsonrpc": "2.0", "id": msg.get("id"), "result": {}})
    out = io.StringIO()
    shim.serve("http://hub", io.StringIO('{"jsonrpc":"2.0","id":1,"method":"ping"}\nnot json\n'), out, fake_encode)
    lines = [json.loads(l) for l in out.getvalue().splitlines()]
    assert lines[0]["result"] == {} and lines[1]["error"]["code"] == -32700 and sent[0]["method"] == "ping"
    def boom(url, msg):
        raise OSError("down")
    monkeypatch.setattr(shim, "forward", boom)
    out = io.StringIO()
    shim.serve("http://hub", io.StringIO('{"jsonrpc":"2.0","id":5,"method":"tools/list"}\n'), out, fake_encode)
    assert "hub unreachable" in json.loads(out.getvalue())["error"]["message"]
