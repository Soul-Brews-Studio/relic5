"""Disk warning: low only when both the share and the bytes left are small (m5: 19.9 % = 1.6 TB, 2026-11-13)."""
from relic5.selfknow import disk_low, warnings


def test_big_disk_at_19_percent_is_fine() -> None:
    assert not disk_low({"free_pct": 19.9, "free": 1_592e9})


def test_small_disk_at_12_percent_is_low() -> None:
    assert disk_low({"free_pct": 12.3, "free": 120e9 - 30e9})


def test_warning_names_the_machine(monkeypatch) -> None:   # type: ignore[no-untyped-def]
    import relic5.status as S
    monkeypatch.setattr(S, "_HUB_MACHINE", ["white"])
    w = warnings({"disk": {"free_pct": 12.3, "free": 90e9}, "total": 13.2e9}, {"load": [0, 0, 0], "cpus": 8})
    assert any(x.startswith("disk: only 12.3% (90 GB) free on white") for x in w)
