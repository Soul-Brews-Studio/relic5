import duckdb

from relic5 import names
from relic5.parts import Parts
from relic5.query import Relic5


def test_name_rule():
    assert names.name_of("/dig --deep find about wispr flow") == "/dig --deep find about wispr flow"
    assert names.name_of("# AGENTS.md instructions for /x") == "(untitled)"
    assert names.name_of("<image src=x> fix   the\n\nbutton") == "fix the button"
    assert names.name_of("") == "(untitled)"
    assert len(names.name_of("x" * 200)) == 70


def test_names_reach_sessions(root):
    con = duckdb.connect()
    assert names.build(root, con, Parts(root)) >= 2
    r = Relic5(root, duckdb.connect())
    s = {x["uuid"]: x["name"] for x in r.sessions()["sessions"]}
    assert s["s1-aaaa"] == "hub shared by two machines"        # the session's first user message
    assert r.session("s1")["name"] == "hub shared by two machines"
