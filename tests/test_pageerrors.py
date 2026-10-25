"""pageerrors.py and its routes: the page's own errors, kept on the hub and grouped."""
from fastapi.testclient import TestClient

from relic5 import pageerrors
from relic5.api import make_app
from relic5.doors import Doors

H = {"Authorization": "Bearer tok-m5", "X-Relic5-Request": "1"}


def test_reports_are_kept_and_grouped(root):
    c = TestClient(make_app(root, {"m5": "tok-m5"}, Doors({"m5": "tok-m5"}, enabled=False)))
    rep = {"kind": "chunk", "message": "Failed to fetch dynamically imported module", "view": "memory", "at": "2026-10-26T05:00:00Z",
           "stack": "x" * 5000}
    assert c.post("/api/client-error", json=[rep, rep | {"view": "hours"}, {"kind": "fetch", "message": "ERR_CONNECTION_REFUSED", "count": 4}],
                  headers=H).json() == {"kept": 3}
    assert c.post("/api/client-error", json=[rep], headers={"Authorization": "Bearer tok-m5"}).status_code == 400   # no X-Relic5-Request
    g = c.get("/api/client-errors", headers=H).json()
    assert g["total"] == 6
    chunk = next(x for x in g["groups"] if x["kind"] == "chunk")
    assert chunk["count"] == 2 and chunk["views"] == ["memory", "hours"] and len(chunk["stack"]) == 2000


def test_a_page_in_a_loop_cannot_fill_the_disk(root, monkeypatch):
    monkeypatch.setattr(pageerrors, "MAX_BYTES", 10)
    assert pageerrors.record(root, [{"message": "a"}], None) == 1
    assert pageerrors.record(root, [{"message": "b"}], None) == 0
