"""The Rust CLI (cli/, binary relic5) prints what the Python CLI prints: the same stdout, stderr and exit code for every
command it owns, against one test hub. Hub-side commands are handed to the Python core and must match too.
Skipped when the Rust binary is not built (cargo build --release in cli/)."""
import json, os, re, socket, subprocess, sys, threading, time

import pytest

RUST = os.path.join(os.path.dirname(__file__), "..", "cli", "target", "release", "relic5")
pytestmark = pytest.mark.skipif(not os.path.exists(RUST), reason="Rust CLI not built (cd cli && cargo build --release)")


@pytest.fixture
def hub(root, tmp_path):
    import uvicorn
    from relic5.api import make_app
    from relic5.doors import Doors
    tokens = {"m5": "tok-m5"}
    app = make_app(root, tokens, Doors(tokens, enabled=False))
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    srv = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    threading.Thread(target=srv.run, daemon=True).start()
    for _ in range(100):
        if srv.started:
            break
        time.sleep(0.05)
    tok = tmp_path / "token"
    tok.write_text("tok-m5\n")
    # RELIC5_CORE: the Rust CLI hands hub-side commands to this same Python CLI
    core = tmp_path / "relic5-core"
    core.write_text(f"#!/bin/sh\nexec {sys.executable} -m relic5.cli \"$@\"\n")
    core.chmod(0o755)
    env = os.environ | {"RELIC5_URL": f"http://127.0.0.1:{port}", "RELIC5_TOKEN_FILE": str(tok), "RELIC5_CORE": str(core),
                        "RELIC5_ROOT": root}
    yield env
    srv.should_exit = True


TRACE = re.compile(r'("(?:id|root|parent)": )"[0-9a-f]{10}"')


def both(env, *args):
    py = subprocess.run([sys.executable, "-m", "relic5.cli", *args], env=env, capture_output=True, text=True, timeout=60)
    rs = subprocess.run([RUST, *args], env=env, capture_output=True, text=True, timeout=60)
    # each request gets its own trace id from the hub; everything else must be the same bytes
    norm = lambda s: TRACE.sub(r'\1"<trace>"', s)
    return (py.returncode, norm(py.stdout), py.stderr), (rs.returncode, norm(rs.stdout), rs.stderr)


CASES = [
    ["search", "hub"],
    ["search", "hub", "--limit", "1", "--json"],
    ["search", "ภาษาไทย"],
    ["search", "hub", "--with", "tools", "--since", "30d"],
    ["search", "x", "--with", "raw"],          # 400 from the hub: exit 2, the same message
    ["recap", "s1-aaaa"],
    ["recap", "s1-aaaa", "--limit", "2", "--json"],
    ["conversation", "s1-aaaa"],
    ["conversation", "s1-aaaa", "--limit", "2", "--json"],
    ["conversation", "s1-aaaa", "--role", "user"],
    ["handoff", "s1-aaaa"],
    ["tail", "--n", "5"],
    ["tail", "--n", "3", "--full"],
    ["show", "0" * 32],                         # 404: exit 2
    ["recap"],                                  # no id: unknown command, from the core
    ["nosuch"],
    ["log", "-n", "2"],                         # a hub-side command, through the core
]


@pytest.mark.parametrize("args", CASES, ids=lambda a: " ".join(a))
def test_same_as_python(hub, args):
    py, rs = both(hub, *args)
    assert rs == py


def test_show_a_hit(hub):
    uid = json.loads(both(hub, "search", "hub", "--limit", "1", "--json")[0][1])["hits"][0]["uid"]
    for extra in ([], ["--json"], ["--before", "1", "--after", "0"]):
        py, rs = both(hub, "show", uid, *extra)
        assert rs == py


def test_version_is_pyprojects(hub):
    from relic5 import __version__
    out = subprocess.run([RUST, "--version"], capture_output=True, text=True).stdout
    assert out == f"relic5 {__version__}\n"


def test_embedded_mode_matches_python(hub):
    """RELIC5_LOCAL=1 (#311): the Rust CLI goes through the core's local-call, the Python CLI reads in-process; both print
    the same bytes and exit codes, the hub never asked."""
    env = hub | {"RELIC5_LOCAL": "1", "RELIC5_URL": "http://127.0.0.1:9"}
    for args in (["search", "hub"], ["search", "hub", "--json"], ["search", "hub", "--limit", "2"], ["show", "f" * 32],
                 ["show", "0" * 32], ["recap", "s1-aaaa"], ["conversation", "s1-aaaa"], ["search", ""]):
        py, rs = both(env, *args)
        assert py == rs, args
    py, rs = both(env, "status")   # its ages move between two runs: the same keys and the same mode
    p_, r_ = json.loads(py[1]), json.loads(rs[1])
    assert list(p_) == list(r_) and p_["mode"] == r_["mode"] == {"used": "local", "why": "RELIC5_LOCAL=1", "root": hub["RELIC5_ROOT"]}
    # no token, no hub, but a store: both fall back on their own
    py, rs = both(hub | {"RELIC5_URL": "http://127.0.0.1:9", "RELIC5_TOKEN_FILE": "/nonexistent"}, "search", "hub")
    assert py == rs and py[0] == 0


RS = os.path.join(os.path.dirname(__file__), "..", "cli", "target", "native", "relic5")


@pytest.mark.skipif(not os.path.exists(RS), reason="the rs engine is not built (cargo build --profile native --features native)")
def test_native_engine_matches_the_core(hub, monkeypatch):
    """The rs build (just cli --engine rs) answers search in Rust (native.rs, #311); RELIC5_LOCAL_ENGINE=py asks the Python core. Same bytes, same
    exit codes, for plain queries, phrases, Thai, layers, windows, sort, paging and the filters it hands back to the core."""
    import duckdb
    from relic5 import fts
    from relic5.parts import Parts
    root = hub["RELIC5_ROOT"]
    monkeypatch.setenv("RELIC5_NOW", "2026-10-23T14:00:00Z")
    con = duckdb.connect()
    Parts(root).index(con, log=lambda s: None)
    fts.build(root, con, log=lambda s: None)
    env = hub | {"RELIC5_LOCAL": "1", "RELIC5_URL": "http://127.0.0.1:9", "RELIC5_NOW": "2026-10-23T14:00:00Z"}
    cases = [["hub"], ["hub", "--limit", "2"], ["hub", "shared"], ['"hub shared"'], ["ภาษาไทย"], ["rg", "--with", "tools"],
             ["hub", "--with", "all"], ["hub", "--since", "2026-10-01"], ["hub", "--since", "30d"], ["hub", "--until", "2026-10-22"],
             ["hub", "--horizon", "7d"], ["hub", "--role", "user"], ["hub", "--session", "s1-"], ["chunk", "long"],
             ["nothingmatchesthis"], ["hub", "--repo", "relic5"], ["hub", "--since", "bogus"], ["hub", "--limit", "0"]]
    assert subprocess.run([RS, "--version"], capture_output=True, text=True).stdout.endswith(" (engine rs)\n")
    native_answered = 0
    for c in cases:
        rs = subprocess.run([RS, "search", *c, "--json"], env=env, capture_output=True, text=True, timeout=120)
        py = subprocess.run([RS, "search", *c, "--json"], env=env | {"RELIC5_LOCAL_ENGINE": "py"}, capture_output=True, text=True, timeout=120)
        if (rs.returncode, rs.stdout, rs.stderr) != (py.returncode, py.stdout, py.stderr) and os.environ.get("RELIC5_DEBUG_DIR"):
            for n_, r_ in (("rs", rs), ("py", py)):
                open(os.path.join(os.environ["RELIC5_DEBUG_DIR"], n_ + ".out"), "w").write(f"{r_.returncode}\n{r_.stdout}\n{r_.stderr}")
        assert (rs.returncode, rs.stdout, rs.stderr) == (py.returncode, py.stdout, py.stderr), c
        pyc = subprocess.run([sys.executable, "-m", "relic5.cli", "search", *c, "--json"], env=env, capture_output=True, text=True, timeout=120)
        assert (rs.returncode, rs.stdout) == (pyc.returncode, pyc.stdout), c
        native_answered += rs.returncode == 0 and "--repo" not in c
    assert native_answered >= 14
    # the text view too
    rs = subprocess.run([RS, "search", "hub"], env=env, capture_output=True, text=True)
    py = subprocess.run([sys.executable, "-m", "relic5.cli", "search", "hub"], env=env, capture_output=True, text=True)
    assert rs.stdout == py.stdout and rs.returncode == 0
