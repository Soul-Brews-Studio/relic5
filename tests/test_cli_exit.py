import subprocess, sys


def run(*a, env=None):
    import os
    return subprocess.run([sys.executable, "-m", "relic5.cli", *a], capture_output=True, text=True, env=dict(os.environ, **(env or {})))


def test_usage_and_unreachable_exit_codes(tmp_path):
    assert run("nope").returncode == 2
    # no hub and no store at the root: today's error, with the commands that fix it (#311)
    r = run("status", env={"RELIC5_URL": "http://127.0.0.1:9", "RELIC5_ROOT": str(tmp_path)})
    assert r.returncode == 1 and "hub unreachable" in r.stderr
    assert "relic5 serve --root" in r.stderr and "RELIC5_LOCAL=1" in r.stderr
