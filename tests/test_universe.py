"""universe.py: one point per session from the mean of its vectors, PCA to 3D, newest sessions first."""
import numpy as np

from relic5 import universe


class FakeMatrix:
    def __init__(self, sids, ts, vecs, machines):
        self.M = np.asarray(vecs, dtype=np.float32)
        self.cols = {"sid": np.asarray(sids, dtype=object), "ts": np.asarray(ts, dtype=object)}
        self.machines = machines
        self.n = len(sids)


class FakeIndex:
    seen = 1.0

    def __init__(self, mats):
        self.mats = mats

    def vector_models(self):
        return ["g"]

    def matrices(self, model):
        return self.mats


class FakeRelic:
    def __init__(self, mats, root="/tmp"):
        self.index = FakeIndex(mats)
        self.parts = type("P", (), {"root": str(root)})()

    def _names(self, sids):
        return {s: s.upper() for s in sids}

    def _repos(self, sids):
        return {s: "repo-" + s for s in sids}


def test_sessions_map_groups_projects_and_orders(tmp_path):
    universe._CACHE.clear()
    rng = np.random.default_rng(1)
    a, b = rng.normal(size=8), rng.normal(size=8)
    rows = [("s1", f"2026-10-0{i}", a + 0.01 * i) for i in range(1, 4)] + [("s2", f"2026-10-1{i}", b + 0.01 * i) for i in range(1, 5)]
    rows += [("s3", "2026-10-20", a), ("s3", "2026-10-21", a)]   # two chunks: under MIN_CHUNKS, left out
    open_m = FakeMatrix([r[0] for r in rows[:4]], [r[1] for r in rows[:4]], [r[2] for r in rows[:4]], [["m5"]] * 4)
    hist_m = FakeMatrix([r[0] for r in rows[4:]], [r[1] for r in rows[4:]], [r[2] for r in rows[4:]], [["white"]] * (len(rows) - 4))
    out = universe.sessions_map(FakeRelic([open_m, hist_m], tmp_path))
    assert [p["sid"] for p in out["points"]] == ["s2", "s1"]          # newest first, s3 dropped
    s2 = out["points"][0]
    assert s2["n"] == 4 and s2["ts"] == "2026-10-14" and s2["repo"] == "repo-s2" and s2["name"] == "S2"
    assert out["points"][1]["machines"] == ["m5"] and out["sessions"] == 2 and out["chunks"] == 7
    for p in out["points"]:
        assert all(-1.0001 <= p[k] <= 1.0001 for k in "xyz")
    assert abs(sum(out["explained"]) - 1) < 1e-6 or len(out["explained"]) <= 3

    universe._CACHE.clear()                                  # a restart: the map comes back from disk, not rebuilt
    again = universe.sessions_map(FakeRelic([], tmp_path))   # no matrices: only a cached map can answer
    assert [p["sid"] for p in again["points"]] == ["s2", "s1"]
    assert len(list((tmp_path / "index" / "_maps").glob("*.json"))) == 1



def test_a_message_is_placed_in_the_maps_own_space(tmp_path):
    """search_space(): a message's vector through the Map's PCA lands on its session's point; the centre is where
    the hits sit; a uid with no vector is reported, not invented."""
    universe._CACHE.clear()
    universe._BASIS.clear()
    rng = np.random.default_rng(2)
    base = {f"s{k}": rng.normal(size=8) for k in range(1, 7)}   # six sessions: three real PCA axes
    rows = [(s, f"2026-10-{k:02d}", v + 0.001 * i, f"{s}-{i}") for k, (s, v) in enumerate(base.items(), 1) for i in range(4)]
    m = FakeMatrix([r[0] for r in rows], [r[1] for r in rows], [r[2] / np.linalg.norm(r[2]) for r in rows], [["m5"]] * len(rows))
    m.cols["uid"] = np.asarray([r[3] for r in rows], dtype=object)
    relic = FakeRelic([m], tmp_path)
    out = universe.search_space(relic, ["s2-1", "nope"], [1.0, 1.0])
    s2 = next(p for p in out["cloud"] if p["sid"] == "s2")
    hit = out["points"][0]
    assert hit["uid"] == "s2-1" and out["missing"] == ["nope"] and len(out["cloud"]) == 6
    assert all(abs(hit[k] - s2[k]) < 0.05 for k in "xyz")      # a session's own message sits on the session
    assert all(abs(out["centre"][k] - hit[k]) < 1e-3 for k in "xyz")
