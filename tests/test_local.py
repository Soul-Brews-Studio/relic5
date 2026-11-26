"""Embedded mode (local.py, issue #311): the same answers as the hub, with no hub, never writing, beside a writer."""
import io, json, os, stat, subprocess, sys, threading

import duckdb
import pytest
from fastapi.testclient import TestClient

from conftest import COLS, row, write_parquet
from relic5 import fts, local, shim
from relic5.api import make_app
from relic5.doors import Doors
from relic5.parts import Parts

H = {"Authorization": "Bearer tok-m5"}
DEAD = "http://127.0.0.1:9"   # nothing listens on the discard port


@pytest.fixture
def built(root, monkeypatch):
    """The conftest store with its manifests and BM25 index published, as `relic5 index` leaves it."""
    monkeypatch.setenv("RELIC5_NOW", "2026-10-23T14:00:00Z")
    con = duckdb.connect()
    Parts(root).index(con, log=lambda s: None)
    fts.build(root, con, log=lambda s: None)
    return root


@pytest.fixture
def hub(built):
    tokens = {"m5": "tok-m5"}
    return TestClient(make_app(built, tokens, Doors(tokens, enabled=False)))


def strip(v):
    """What only the hub adds: its trace record, and who called (the door)."""
    if isinstance(v, dict):
        return {k: strip(x) for k, x in v.items() if k not in ("trace", "you")}
    if isinstance(v, list):
        return [strip(x) for x in v]
    return v


QUERIES = [
    ("/api/search", [("q", "hub")]),
    ("/api/search", [("q", "hub"), ("limit", "2")]),
    ("/api/search", [("q", "ภาษาไทย")]),
    ("/api/search", [("q", "rg"), ("with", "tools")]),
    ("/api/search", [("q", "hub"), ("sort", "newest"), ("since", "2026-10-01")]),
    ("/api/search", [("q", "x"), ("typo", "1")]),                       # a usage error: 400 both ways
    ("/api/search", [("q", "")]),
    ("/api/show", [("id", "f" * 32), ("before", "1"), ("after", "1")]),
    ("/api/show", [("id", "0" * 32)]),                                  # not found: 404 both ways
    ("/api/sessions", [("limit", "10")]),
    ("/api/sessions", [("by_repo", "1")]),
    ("/api/session", [("id", "s1-a")]),
    ("/api/session", [("id", "zzzz")]),
    ("/api/conversation", [("id", "s1-aaaa")]),
    ("/api/conversation", [("id", "s1-aaaa"), ("tools", "1"), ("limit", "2")]),
    ("/api/recap", [("id", "s1-aaaa")]),
    ("/api/handoff", [("id", "s1-aaaa")]),
    ("/api/tail", [("n", "3")]),
    ("/api/readings", []),
    ("/api/searched", [("q", "hub")]),
    ("/api/chain", [("id", "s1-aaaa")]),
    ("/api/arc", [("words", "hub")]),
]


@pytest.mark.parametrize("path,params", QUERIES)
def test_same_answer_as_the_hub(hub, built, path, params):
    want = hub.get(path, params=params, headers=H)
    status, body = local.Reader(built).get(path, params)
    assert status == want.status_code, (path, params, body)
    assert strip(body) == strip(want.json())


def test_status_same_as_the_hub_but_the_door(hub, built):
    want = hub.get("/api/status", headers=H).json()
    status, body = local.Reader(built).get("/api/status", [])
    assert status == 200 and body["you"] == "local"
    drop = lambda d: {k: v for k, v in d.items() if k not in ("you", "now", "generated_at", "uptime_s")}
    assert drop(body).keys() == drop(want).keys()
    assert body["months"] == want["months"] and body.get("machines") == want.get("machines")


def test_writes_refused_and_semantic_is_keyword(built):
    rd = local.Reader(built)
    for name, args in (("relic_tag", {"target": "x", "add": ["a"]}), ("relic_found", {"parent": "p", "goal": "g", "found": "f"}),
                       ("relic_saved", {"action": "add", "query": "hub"}), ("relic_hub_memory", {"set": "8GB"}),
                       ("relic_artifact_put", {"title": "t", "text": "x"})):
        ok, r = rd.tool(name, args)
        assert not ok and r[0] == "unavailable" and "relic5 serve --root" in r[1], name
    ok, r = rd.tool("relic_search", {"query": "hub", "semantic": True, "vector": [0.6, 0.8]})
    assert ok and r["hits"] and "keyword hits" in r["note"]
    assert rd.tool("relic_saved", {})[0]   # listing is a read


def test_unknown_route_says_it_needs_the_hub(built):
    status, body = local.Reader(built).get("/api/map", [])
    assert status == 501 and "relic5 serve" in body["error"]


def test_reader_closes_when_idle(built):
    rd = local.Reader(built)
    rd.tool("relic_search", {"query": "hub"})
    assert rd.open and not rd.close_idle(3600)
    assert rd.close_idle(0) and not rd.open
    assert rd.tool("relic_search", {"query": "hub"})[0] and rd.open   # opens again on the next call
    import time
    rd._last = time.monotonic() - 999
    rd.tool("relic_search", {"query": "hub"})   # a call longer than the idle window is not idle: closes only after IDLE_S more
    assert not rd.close_idle(60)


def cli(*a, env):
    return subprocess.run([sys.executable, "-m", "relic5.cli", *a], capture_output=True, text=True,
                          env=dict(os.environ, RELIC5_URL=DEAD, RELIC5_TOKEN_FILE="/nonexistent/token", **env))


def test_cli_with_no_hub_running(hub, built):
    """No server listens: search falls back to the store (hits identical to the hub's), status says why, errors keep
    the hub's text and exit code."""
    want = strip(hub.get("/api/search", params={"q": "hub"}, headers=H).json())
    r = cli("search", "hub", "--json", env={"RELIC5_ROOT": built})
    assert r.returncode == 0, r.stderr
    assert strip(json.loads(r.stdout)) == want
    r = cli("search", "hub", "--json", "--local", "--root", built, env={})
    assert r.returncode == 0 and strip(json.loads(r.stdout)) == want
    st = json.loads(cli("status", "--root", built, env={}).stdout)
    assert st["mode"]["used"] == "local" and "no hub token" in st["mode"]["why"] and st["mode"]["root"] == built
    st = json.loads(cli("status", env={"RELIC5_ROOT": built, "RELIC5_LOCAL": "1"}).stdout)
    assert st["mode"] == {"used": "local", "why": "RELIC5_LOCAL=1", "root": built, "engine": "py"}
    bad = cli("show", "0" * 32, env={"RELIC5_ROOT": built})
    assert bad.returncode == 2 and bad.stderr.startswith('relic5: 404 {"error":')


def test_core_local_call(built):
    r = subprocess.run([sys.executable, "-m", "relic5.cli", "local-call", "/api/search", json.dumps([["q", "hub"], ["limit", "2"]])],
                       capture_output=True, text=True, env=dict(os.environ, RELIC5_ROOT=built))
    assert r.returncode == 0 and len(json.loads(r.stdout)["hits"]) == 2
    r = subprocess.run([sys.executable, "-m", "relic5.cli", "local-call", "/api/search", json.dumps([["q", ""]])],
                       capture_output=True, text=True, env=dict(os.environ, RELIC5_ROOT=built))
    assert r.returncode == 2 and r.stderr.startswith('relic5: 400 {"error":')


def test_never_writes(built, tmp_path):
    """Every read answered from a store nobody may write to (and no file appears in it)."""
    def files():
        return sorted(os.path.join(d, f) for d, _, fs in os.walk(built) for f in fs)
    before = files()
    modes = {}
    for d, ds, fs in os.walk(built):
        for x in ds + fs:
            p = os.path.join(d, x)
            modes[p] = os.stat(p).st_mode
    for p in sorted(modes, key=len, reverse=True):
        os.chmod(p, modes[p] & ~(stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH))
    os.chmod(built, os.stat(built).st_mode & ~stat.S_IWUSR)
    try:
        rd = local.Reader(built)
        for path, params in QUERIES + [("/api/status", [])]:
            status, body = rd.get(path, params)
            assert status != 500, (path, body)
        assert files() == before
    finally:
        os.chmod(built, os.stat(built).st_mode | stat.S_IWUSR)
        for p, m in modes.items():
            os.chmod(p, m)


def test_reader_beside_a_writer(built):
    """An index rebuilding (new parts, a new generation, current.json swapped) while a reader searches: every read
    answers, and the reader sees the new line once it is published."""
    stop, errors, done = threading.Event(), [], []

    def read():
        rd = local.Reader(built)
        while not stop.is_set():
            st, body = rd.get("/api/search", [("q", "hub")])
            if st != 200 or not body["hits"]:
                errors.append((st, body))
            rd.close()   # every call opens the store again: sees whichever generation is current
            done.append(1)

    t = threading.Thread(target=read)
    t.start()
    try:
        con = duckdb.connect()
        for i in range(3):
            write_parquet(os.path.join(built, "parts/m5/text/2026-10.parquet"), COLS,
                          [row("hub shared by two machines", "2026-10-23T09:00:00.000Z")] +
                          [row(f"writer line {j} zebra{j}", f"2026-10-23T13:0{j}:00.000Z") for j in range(i + 1)])
            Parts(built).index(con, log=lambda s: None)
            fts.build(built, con, log=lambda s: None)
    finally:
        stop.set()
        t.join(60)
    assert not errors and done
    st, body = local.Reader(built).get("/api/search", [("q", "zebra2")])
    assert st == 200 and body["hits"]


def test_mcp_shim_answers_embedded_when_the_hub_is_down(hub, built, monkeypatch):
    msgs = [{"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "relic_search", "arguments": {"query": "hub"}}},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
            {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "relic_tag", "arguments": {"target": "x", "add": ["a"]}}}]
    want = hub.post("/mcp", json=msgs[0], headers=H).json()
    out = io.StringIO()
    shim.serve(DEAD, io.StringIO("".join(json.dumps(m) + "\n" for m in msgs)), out, reader=local.Reader(built))
    got = [json.loads(x) for x in out.getvalue().splitlines()]
    assert strip(json.loads(got[0]["result"]["content"][0]["text"])) == strip(json.loads(want["result"]["content"][0]["text"]))
    assert len(got[1]["result"]["tools"]) == len(hub.post("/mcp", json=msgs[1], headers=H).json()["result"]["tools"])
    assert got[2]["result"]["isError"] and "relic5 serve" in got[2]["result"]["content"][0]["text"]
    monkeypatch.setenv("RELIC5_LOCAL", "1")   # forced: the hub is never tried
    monkeypatch.setattr(shim, "forward", lambda *a: pytest.fail("forwarded in forced embedded mode"))
    out = io.StringIO()
    shim.serve("http://hub", io.StringIO(json.dumps(msgs[0]) + "\n"), out, reader=local.Reader(built))
    assert json.loads(json.loads(out.getvalue())["result"]["content"][0]["text"])["hits"]


def test_worker_child_matches_and_ends_when_idle(hub, built, monkeypatch):
    """relic5 mcp's default: the reader in a child process, the same answers, the child gone after the idle close."""
    monkeypatch.setenv("RELIC5_ROOT", built)
    w = local.Worker(built)
    try:
        ok, r = w.tool("relic_search", {"query": "hub"})
        want = hub.get("/api/search", params={"q": "hub"}, headers=H).json()
        assert ok and strip(r) == strip(want)
        ok, r = w.tool("relic_tag", {"target": "x", "add": ["a"]})
        assert not ok and r[0] == "unavailable"
        pid = w._p.pid
        assert w.open and w.close_idle(0) and not w.open
        with pytest.raises(ProcessLookupError):
            os.kill(pid, 0)
        assert w.tool("relic_show", {"id": "f" * 32})[0]   # started again on the next call
    finally:
        w.close()


def test_store_first_by_default(built, tmp_path, monkeypatch):
    """The CLI's default (#311): a store is here, so it is read and the hub is never asked; --hub / RELIC5_HUB=1 / an
    explicit RELIC5_URL / no store send it to the hub; status asks the hub first."""
    from relic5 import cli as rcli
    for k in ("RELIC5_URL", "RELIC5_LOCAL", "RELIC5_HUB"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("RELIC5_ROOT", built)
    monkeypatch.setattr(rcli.urllib.request, "urlopen", lambda *a, **k: pytest.fail("asked the hub"))
    r = rcli.call("/api/search", {"q": "hub"})
    assert r["hits"] and rcli.MODE == {"used": "local", "why": local.DEFAULT_WHY, "root": built}
    assert local.local_first("/api/search") and not local.local_first("/api/status")
    monkeypatch.setenv("RELIC5_HUB", "1")
    assert not local.local_first("/api/search")
    monkeypatch.delenv("RELIC5_HUB")
    monkeypatch.setenv("RELIC5_URL", DEAD)
    assert not local.local_first("/api/search")
    monkeypatch.delenv("RELIC5_URL")
    monkeypatch.setenv("RELIC5_ROOT", str(tmp_path / "empty"))   # no store here
    assert not local.local_first("/api/search")
