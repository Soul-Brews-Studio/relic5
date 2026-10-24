import json, os, stat

import pytest

from relic5.doors import Doors
from relic5.tokens import Tokens


@pytest.fixture
def T(tmp_path):
    return Tokens(str(tmp_path / "tokens.json"), str(tmp_path / "tokens"))


def test_new_is_hashed_and_shown_once(T):
    s = T.new("script")
    raw = open(T.path).read()
    assert s not in raw and json.loads(raw)["script"]["sha256"] and stat.S_IMODE(os.stat(T.path).st_mode) == 0o600
    assert T.check(s) == "script" and T.check("nope") is None and T.check("") is None
    with pytest.raises(SystemExit):
        T.new("script")


def test_rotate_keeps_the_old_one_for_the_grace(T):
    old = T.new("ci")
    new = T.rotate("ci", grace="1h")
    assert T.check(new) == "ci" and T.check(old) == "ci"
    assert T.check(old, now="2999-01-01T00:00:00Z") is None and T.check(new, now="2999-01-01T00:00:00Z") == "ci"


def test_expiry_and_revoke(T):
    s = T.new("tmp", expires="1d")
    assert T.check(s) == "tmp" and T.check(s, now="2999-01-01T00:00:00Z") is None
    T.revoke("tmp")
    assert T.check(s) is None


def test_legacy_lines_still_work_and_doors_use_them(T):
    open(T.legacy, "w").write("m5 plainsecret\n")
    assert T.check("plainsecret") == "m5" and [t["name"] for t in T.list()] == ["m5"]
    d = Doors(T, enabled=False)
    assert d.door("", "", "", "plainsecret") == "token:m5" and d.door("", "", "", "x") is None
