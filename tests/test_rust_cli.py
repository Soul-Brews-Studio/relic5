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
