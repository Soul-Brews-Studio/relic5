"""vaults.py: which oracle a ψ note belongs to.

relic-extract keys a vault note's session as "vault:<id>" and keeps only its path inside the vault, so a hit said
`session_uuid: "vault:3"`, `repo_key: null`. The id is relic-scan's, per machine, and relic-scan writes what it means
to OUT/meta/vaults.json (relic4-scan src/vault.rs: id, name, path, kind, links, notes). relic5-push sends that file
with the session table:

  <root>/parts/<machine>/meta/vaults.json

and a vault hit gets its repo_key (the vault's repo folder, encoded the way Claude Code names a project folder, so it
reads like every other hit's) and its session_name (the oracle's name), looked up on the first machine that holds it.
"""
import json, os, re
from typing import TypedDict
from . import store as rfs


class Vault(TypedDict):
    name: str
    path: str
    repo_key: str


def repo_key(path: str) -> str:
    """'/opt/Code/github.com/Soul-Brews-Studio/odin-oracle/ψ' -> '-opt-Code-github-com-Soul-Brews-Studio-odin-oracle'."""
    p = path[:-2].rstrip("/") if path.endswith("/ψ") else path.rstrip("/")
    return re.sub(r"[^A-Za-z0-9]", "-", p)


def load(root: str) -> dict[tuple[str, str], Vault]:
    """{(machine, "vault:<id>"): Vault} over every machine's pushed vaults.json. A missing or broken file is no vaults."""
    out: dict[tuple[str, str], Vault] = {}
    pdir = os.path.join(root, "parts")
    for machine in sorted(rfs.listdir(pdir)) if rfs.isdir(pdir) else []:
        f = os.path.join(pdir, machine, "meta", "vaults.json")
        try:
            vs = rfs.read_json(f).get("vaults", [])
        except (OSError, ValueError, AttributeError):
            continue
        for v in vs:
            if isinstance(v, dict) and v.get("id") is not None and v.get("path"):
                out[(machine, f"vault:{v['id']}")] = {"name": str(v.get("name") or ""), "path": str(v["path"]),
                                                      "repo_key": repo_key(str(v["path"]))}
    return out


def of(vaults: dict[tuple[str, str], Vault], sid: str | None, machines: list[str] | None) -> Vault | None:
    """The vault of one hit: its sid on the first of its machines that knows it."""
    if not sid or not sid.startswith("vault:"):
        return None
    return next((vaults[(m, sid)] for m in machines or [] if (m, sid) in vaults), None)
