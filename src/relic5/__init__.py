"""relic5: the hub for every machine's relic-extract parts."""
import re
from importlib.metadata import PackageNotFoundError, version as _dist_version


def _calver(pep440: str) -> str:
    """'26.10.24a1310' (pyproject, PEP 440) -> '26.10.24-alpha.1310' (CalVer v{yy}.{m}.{d}-alpha.{HMM}, Bangkok, /calver)."""
    m = re.fullmatch(r"(\d+\.\d+\.\d+)(?:(a|b)(\d+))?", pep440)
    if not m:
        return pep440
    return m.group(1) + (f"-{'alpha' if m.group(2) == 'a' else 'beta'}.{m.group(3)}" if m.group(2) else "")


try:   # one source: pyproject's version (v26.10.24-alpha.1310 shipped with a stale copy here)
    __version__ = _calver(_dist_version("relic5"))
except PackageNotFoundError:
    __version__ = "unknown"
