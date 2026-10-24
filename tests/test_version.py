import re
import tomllib

import relic5


def test_version_is_pyproject_s():
    v = tomllib.load(open("pyproject.toml", "rb"))["project"]["version"]
    assert relic5.__version__ == relic5._calver(v)
    assert re.fullmatch(r"\d+\.\d+\.\d+(-(alpha|beta)\.\d+)?", relic5.__version__)


def test_calver_form():
    assert relic5._calver("26.10.24a1310") == "26.10.24-alpha.1310"
    assert relic5._calver("26.10.24b5") == "26.10.24-beta.5"
    assert relic5._calver("26.10.24") == "26.10.24"
