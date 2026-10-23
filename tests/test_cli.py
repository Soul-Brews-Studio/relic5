import os, stat

import pytest

from relic5 import cli


def test_token_add_list(tmp_path):
    p = str(tmp_path / "cfg/tokens")
    t = cli.add_token("m5", p)
    assert stat.S_IMODE(os.stat(p).st_mode) == 0o600
    assert cli.read_tokens(p) == {"m5": t}
    cli.add_token("mba", p)
    assert sorted(cli.read_tokens(p)) == ["m5", "mba"]
    with pytest.raises(SystemExit):
        cli.add_token("m5", p)          # never replaced silently
    with pytest.raises(SystemExit):
        cli.add_token("M5 x", p)
