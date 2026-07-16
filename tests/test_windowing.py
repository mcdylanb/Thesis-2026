from __future__ import annotations

import numpy as np

from gateway.records import CsiRecord
from gateway.windowing import assign_windows, is_sufficient


def rec(anchor="A1", mac="a4:cf:12:3b:9e:01", t_host=0.0):
    return CsiRecord(
        anchor=anchor, seq=1, mac=mac, rssi=-60, sig_mode=1, channel=6,
        timestamp_us=0, t_host=t_host, host_ns=int(t_host * 1e9),
        amps_hw=np.ones(64, dtype=np.float32),
    )


def test_boundary_record_lands_in_later_window():
    records = [rec(t_host=100.0), rec(t_host=101.0)]  # exactly t0 + 1*W
    t0, groups = assign_windows(records, window_s=1.0)
    assert t0 == 100.0
    window_ids = sorted(w for w, _ in groups)
    assert window_ids == [0, 1]


def test_records_split_across_windows():
    records = [rec(t_host=t) for t in (100.0, 100.4, 100.9, 101.1, 102.5)]
    _, groups = assign_windows(records, window_s=1.0)
    counts = {w: len(v["A1"]) for (w, _), v in groups.items()}
    assert counts == {0: 3, 1: 1, 2: 1}


def test_sufficiency_three_of_four():
    per_anchor = {"A1": [rec()], "A2": [rec()], "A3": [rec()]}
    assert is_sufficient(per_anchor, min_anchors=3, min_pkts=1)
    per_anchor = {"A1": [rec()], "A2": [rec()]}
    assert not is_sufficient(per_anchor, min_anchors=3, min_pkts=1)


def test_min_pkts_demotes_anchor():
    per_anchor = {"A1": [rec(), rec()], "A2": [rec(), rec()], "A3": [rec()]}
    assert is_sufficient(per_anchor, min_anchors=3, min_pkts=1)
    assert not is_sufficient(per_anchor, min_anchors=3, min_pkts=2)


def test_macs_grouped_independently():
    records = [
        rec(mac="a4:cf:12:3b:9e:01", t_host=100.1),
        rec(mac="3c:22:fb:aa:10:07", t_host=100.2),
    ]
    _, groups = assign_windows(records, window_s=1.0)
    assert len(groups) == 2
    assert {m for _, m in groups} == {"a4:cf:12:3b:9e:01", "3c:22:fb:aa:10:07"}


def test_deterministic_t0():
    records = [rec(t_host=t) for t in (500.5, 500.7)]
    t0, _ = assign_windows(records, window_s=1.0)
    assert t0 == 500.5
    t0_explicit, groups = assign_windows(records, window_s=1.0, t0=500.0)
    assert t0_explicit == 500.0
    assert sorted(w for w, _ in groups) == [0]


def test_empty_input():
    t0, groups = assign_windows([], window_s=1.0)
    assert groups == {}
