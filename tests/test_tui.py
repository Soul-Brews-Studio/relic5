from relic5 import tui


def test_line_builders_on_real_shapes(root, monkeypatch):
    monkeypatch.setenv("RELIC5_NOW", "2026-10-23T14:00:00Z")
    from relic5.status import status
    from relic5.query import Relic5
    from relic5 import selfknow
    import duckdb
    from relic5.parts import Parts
    Parts(root).index(duckdb.connect(), log=lambda s: None)
    lines = tui.status_lines(status(root) | {"you": "loopback"})
    assert any(l.startswith("m5 ") for l in lines) and lines[0].endswith("you: loopback")
    r = Relic5(root, duckdb.connect())
    assert tui.live_lines(r.tail(n=5))[0][:5] == "10-23"
    assert tui.job_lines([{"at": "2026-10-23T14:00:00Z", "verb": "push", "state": "done", "rc": 0, "host": "m5", "done": 5, "unit": "bytes"}])[0].startswith("10-23 14:00:00  push")
    assert "running now: 0" in tui.query_lines(selfknow.queries(root))[0]
