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
    def __init__(self, mats):
        self.index = FakeIndex(mats)

    def _names(self, sids):
        return {s: s.upper() for s in sids}

    def _repos(self, sids):
        return {s: "repo-" + s for s in sids}


def test_sessions_map_groups_projects_and_orders():
    universe._CACHE.clear()
    rng = np.random.default_rng(1)
    a, b = rng.normal(size=8), rng.normal(size=8)
    rows = [("s1", f"2026-10-0{i}", a + 0.01 * i) for i in range(1, 4)] + [("s2", f"2026-10-1{i}", b + 0.01 * i) for i in range(1, 5)]
    rows += [("s3", "2026-10-20", a), ("s3", "2026-10-21", a)]   # two chunks: under MIN_CHUNKS, left out
    open_m = FakeMatrix([r[0] for r in rows[:4]], [r[1] for r in rows[:4]], [r[2] for r in rows[:4]], [["m5"]] * 4)
    hist_m = FakeMatrix([r[0] for r in rows[4:]], [r[1] for r in rows[4:]], [r[2] for r in rows[4:]], [["white"]] * (len(rows) - 4))
    out = universe.sessions_map(FakeRelic([open_m, hist_m]))
    assert [p["sid"] for p in out["points"]] == ["s2", "s1"]          # newest first, s3 dropped
    s2 = out["points"][0]
    assert s2["n"] == 4 and s2["ts"] == "2026-10-14" and s2["repo"] == "repo-s2" and s2["name"] == "S2"
    assert out["points"][1]["machines"] == ["m5"] and out["sessions"] == 2 and out["chunks"] == 7
    for p in out["points"]:
        assert all(-1.0001 <= p[k] <= 1.0001 for k in "xyz")
    assert abs(sum(out["explained"]) - 1) < 1e-6 or len(out["explained"]) <= 3
