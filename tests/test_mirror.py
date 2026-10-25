"""mirror.py and the Storage routes: copy a hub to a second home, verify it, switch only after a clean verify."""
import os

from fastapi.testclient import TestClient

from relic5 import mirror
from relic5.api import make_app
from relic5.doors import Doors

W = {"X-Relic5-Request": "1"}


def test_copy_verify_and_only_what_changed(root, tmp_path):
    dst = str(tmp_path / "mirror")
    first = mirror.copy(root, dst)
    assert first["files"] > 0 and not first["errors"] and mirror.verify(root, dst)["ok"]
    again = mirror.copy(root, dst)
    assert again["files"] == 0 and again["skipped"] == first["files"]          # nothing new: nothing sent
    with open(os.path.join(root, "parts/m5/text/2026-10.parquet"), "ab") as f:
        f.write(b"x")                                                          # a part grew
    v = mirror.verify(root, dst)
    assert not v["ok"] and v["differ"] == 1 and v["examples"] == ["parts/m5/text/2026-10.parquet"]
    os.makedirs(os.path.join(root, "logs"), exist_ok=True)
    with open(os.path.join(root, "logs/queries.jsonl"), "a") as f:
        f.write("{}\n")                                                       # a log moved: behind, not failed
    assert mirror.verify(root, dst)["behind"] == 1
    assert mirror.copy(root, dst)["files"] == 2 and mirror.verify(root, dst)["ok"]   # the part and the log


def test_the_storage_page_sets_a_mirror_verifies_and_switches(root, tmp_path, monkeypatch):
    monkeypatch.setenv("RELIC5_WARM", "0")
    monkeypatch.setattr(mirror, "CONFIG", str(tmp_path / "storage.json"))
    class Local(Doors):        # no bearer = the loopback door (as test_api's hub_with_tokens); a bearer is checked for real
        def door(self, server, client, host, bearer):
            return super().door(server, client, host, bearer) if bearer else "loopback"
    c = TestClient(make_app(root, {"m5": "t"}, Local({"m5": "t"}, enabled=False)))
    st = c.get("/api/storage", headers={"Authorization": "Bearer t"}).json()
    assert st["kind"] == "disk" and st["mirror"] is None
    # a token never repoints the hub's data; the loopback door (no token) may
    assert c.post("/api/storage", json={"action": "set-mirror", "target": "/x"}, headers={"Authorization": "Bearer t"} | W).status_code == 403
    dst = str(tmp_path / "home2")
    assert c.post("/api/storage", json={"action": "set-mirror", "target": root}, headers=W).status_code == 400   # itself
    assert c.post("/api/storage", json={"action": "set-mirror", "target": dst, "every_min": 30}, headers=W).json()["mirror"] == dst
    assert c.post("/api/storage", json={"action": "switch"}, headers=W).status_code == 400                   # no verify yet
    mirror.run(root)
    assert c.post("/api/storage", json={"action": "verify"}, headers=W).json()["ok"]
    assert c.post("/api/storage", json={"action": "switch"}, headers=W).json()["switch_to"] == dst
    st = c.get("/api/storage", headers=W).json()
    assert st["switch_to"] == dst and st["last_job"]["verb"] == "mirror" and st["every_min"] == 30
