import subprocess, sys


def run(*a, env=None):
    import os
    return subprocess.run([sys.executable, "-m", "relic5.cli", *a], capture_output=True, text=True, env=dict(os.environ, **(env or {})))


def test_usage_and_unreachable_exit_codes():
    assert run("nope").returncode == 2
    r = run("status", env={"RELIC5_URL": "http://127.0.0.1:9"})
    assert r.returncode == 1 and "hub unreachable" in r.stderr
