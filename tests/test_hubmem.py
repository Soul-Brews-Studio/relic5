"""hubmem.py (#306): the hub's DuckDB memory cap, set from the CLI or MCP, saved for the next start."""
import json

import duckdb
import pytest
from fastapi.testclient import TestClient

from relic5 import hubmem, mcp
from relic5.api import make_app
from relic5.doors import Doors
from relic5.query import Relic5


@pytest.fixture(autouse=True)
def cfg(tmp_path, monkeypatch):
    monkeypatch.setattr(hubmem, "CONFIG", str(tmp_path / "hub.json"))
    monkeypatch.delenv("RELIC5_DUCK_MEM", raising=False)
    return tmp_path / "hub.json"


def test_parse_only_lets_a_size_through():
    assert [hubmem.parse(v) for v in ("8GB", "8 gb", "7.5GiB", "1024MB")] == ["8GB", "8GB", "7.5GiB", "1024MB"]
    for bad in ("8", "100MB", "1000GB", "8GB'; DROP TABLE x; --", "", "eight GB"):
        with pytest.raises(ValueError):
            hubmem.parse(bad)


def test_start_value_flag_then_env_then_file_then_default(cfg, monkeypatch):
    assert hubmem.at_start() == ("6GB", "default")
    cfg.write_text(json.dumps({"duck_mem": "10GB", "other": 1}))
    assert hubmem.at_start() == ("10GB", str(cfg))
    monkeypatch.setenv("RELIC5_DUCK_MEM", "12GB")
    assert hubmem.at_start() == ("12GB", "RELIC5_DUCK_MEM")
    assert hubmem.at_start("14gb") == ("14GB", "--duck-mem")


def test_change_live_and_saved_only_from_a_tokenless_door(cfg):
    con = duckdb.connect(config={"memory_limit": "6GB"})
    before = hubmem.current(con)
    with pytest.raises(PermissionError):
        hubmem.change(con, "8GB", "token:m5")
    assert hubmem.current(con) == before and not cfg.exists()
    out = hubmem.change(con, "8GB", "loopback")
    assert out["set"] == "8GB" and out["before"] == before and hubmem.current(con) != before
    assert json.loads(cfg.read_text()) == {"duck_mem": "8GB"} and out["saved"] == "8GB"
    hubmem.change(con, "9GB", "tailnet:mba", persist=False)
    assert json.loads(cfg.read_text()) == {"duck_mem": "8GB"}


def test_mcp_reads_for_anyone_changes_for_tokenless(root):
    r = Relic5(root, duckdb.connect(config={"memory_limit": "6GB"}))
    ok, st = mcp.call_tool(r, "relic_hub_memory", {}, "token:m5")
    assert ok and st["default"] == "6GB" and st["saved"] is None
    ok, err = mcp.call_tool(r, "relic_hub_memory", {"set": "8GB"}, "token:m5")
    assert not ok and err[0] == "usage" and "not with a token" in err[1]
    ok, st = mcp.call_tool(r, "relic_hub_memory", {"set": "8GB"}, "tailnet:mba")
    assert ok and st["set"] == "8GB" and st["persisted"] is True
    ok, err = mcp.call_tool(r, "relic_hub_memory", {"set": "lots"}, "loopback")
    assert not ok and err[0] == "usage"


def test_api_read_with_a_token_change_refused_with_a_token(root):
    c = TestClient(make_app(root, {"m5": "tok"}, Doors({"m5": "tok"}, enabled=False), duck_mem="7GB"))
    h = {"Authorization": "Bearer tok"}
    got = c.get("/api/duck-mem", headers=h).json()
    assert got["default"] == "6GB" and got["memory_limit"]
    assert c.post("/api/duck-mem", json={"memory_limit": "8GB"}, headers=h).status_code == 400   # no X-Relic5-Request
    r = c.post("/api/duck-mem", json={"memory_limit": "8GB"}, headers=h | {"X-Relic5-Request": "1"})
    assert r.status_code == 403 and "not with a token" in r.json()["error"]
