"""Strong typing is enforced: `mypy --strict` over src/relic5 (pyproject.toml [tool.mypy]) must report nothing, so a
type error fails the suite the way `tsc -b` fails the web build (Nat, 2026-10-24: "can python have a strong type?")."""
import os, subprocess, sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_mypy_strict_is_clean():
    r = subprocess.run([sys.executable, "-m", "mypy"], cwd=REPO, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout[-4000:] + r.stderr[-2000:]
    assert "Success: no issues found" in r.stdout
