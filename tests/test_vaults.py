import json, os

import duckdb

from conftest import COLS, row, write_parquet
from relic5 import fts, vaults
from relic5.parts import Parts
from relic5.query import Relic5

ODIN = "/opt/Code/github.com/Soul-Brews-Studio/odin-oracle/ψ"


def test_repo_key_reads_like_a_project_folder():
    assert vaults.repo_key(ODIN) == "-opt-Code-github-com-Soul-Brews-Studio-odin-oracle"
    assert vaults.repo_key("/x/y") == "-x-y"


def test_load_and_of_per_machine(tmp_path):
    root = str(tmp_path)
    os.makedirs(f"{root}/parts/m5/meta")
    os.makedirs(f"{root}/parts/mba/meta")
    json.dump({"vaults": [{"id": "3", "name": "odin-oracle", "path": ODIN}]}, open(f"{root}/parts/m5/meta/vaults.json", "w"))
    open(f"{root}/parts/mba/meta/vaults.json", "w").write("{broken")              # a broken file is no vaults
    vs = vaults.load(root)
    assert set(vs) == {("m5", "vault:3")}
    assert vaults.of(vs, "vault:3", ["mba", "m5"])["name"] == "odin-oracle"     # first machine that knows it
    assert vaults.of(vs, "vault:3", ["mba"]) is None                             # ids are per machine
    assert vaults.of(vs, "s1-aaaa", ["m5"]) is None


def test_vault_hit_gets_its_oracle(root, monkeypatch):
    monkeypatch.setenv("RELIC5_NOW", "2026-10-23T14:00:00Z")
    note = row("garage keeps the backups on odin", "2026-10-20T00:00:00.000Z", sid="vault:3", role="note")
    write_parquet(os.path.join(root, "parts/m5/vault/notes.parquet"), COLS + ["title", "path"],
                  [note | {"title": "Garage plan", "path": "memory/learnings/garage.md"}])
    os.makedirs(os.path.join(root, "parts/m5/meta"), exist_ok=True)
    json.dump({"vaults": [{"id": "3", "name": "odin-oracle", "path": ODIN}]}, open(os.path.join(root, "parts/m5/meta/vaults.json"), "w"))
    con = duckdb.connect()
    Parts(root).index(con, log=lambda s: None)
    fts.build(root, con, log=lambda s: None)
    hits = Relic5(root, duckdb.connect()).search("garage backups", with_="vault")["hits"]
    hit = next(h for h in hits if h["session_uuid"] == "vault:3")
    assert hit["repo_key"] == "-opt-Code-github-com-Soul-Brews-Studio-odin-oracle" and hit["session_name"] == "odin-oracle"
