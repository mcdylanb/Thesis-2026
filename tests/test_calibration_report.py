"""Calibration-quality report over an imported real session (#46)."""

from __future__ import annotations

import pytest

from gateway.calibration_report import calibration_report

BEACON = "68:fe:71:fa:df:fc"
ANCHORS = ("A1", "A2", "A3", "A4")
DAY = 86_400.0


def _trial(tid, t0, dur=100.0):
    return {"id": tid, "t_start": t0, "t_end": t0 + dur,
            "devices": [{"name": "beacon", "role": "beacon", "mac": BEACON,
                         "x": 1.2, "y": 6.0}]}


def _window(t, heard, sufficient=True, mac=BEACON):
    """`heard` maps Anchor -> (rssi, above_floor); the rest did not hear it."""
    return {"t_start": t, "t_end": t + 1.0, "mac": mac, "sufficient": sufficient,
            "anchors": {a: ({"rssi": heard[a][0], "above_floor": heard[a][1]}
                            if a in heard else None) for a in ANCHORS}}


@pytest.fixture
def report():
    truth = {"trials": [_trial("p1", 0.0), _trial("p2", 1_000.0), _trial("p3", DAY)]}
    windows = []
    # p1: 40 sufficient windows; 10 with three Anchors above the floor.
    for i in range(40):
        above = i < 10
        windows.append(_window(float(i), {
            "A1": (-70, True), "A2": (-75, True), "A3": (-85, above),
            "A4": (-88, False)}))
    # p2: A1 is a field-noted fault, A2 never hears the Beacon, 5 sufficient.
    for i in range(20):
        windows.append(_window(1_000.0 + i, {"A3": (-82, False), "A4": (-78, True)},
                               sufficient=i < 5))
    windows.append(_window(10.0, {"A1": (-50, True)}, mac="aa:aa:aa:aa:aa:aa"))
    # p3 (the next day): no sufficient window at all.
    windows.append(_window(DAY, {"A1": (-90, False)}, sufficient=False))
    traffic = {
        "records": {
            "p1": {"A1": 1_000, "A2": 900, "A3": 1_100, "A4": 1_000},
            "p2": {"A1": 30, "A2": 950, "A3": 1_000, "A4": 1_050},
            "p3": {"A1": 1_000, "A2": 40, "A3": 1_000, "A4": 1_000},
        },
        # An ambient device at a fixed spot, heard by A1 on both days.
        "ambient_rssi": {
            "p1": {"A1": {"3c:8a:1f:9a:66:c8": [-60] * 40}},
            "p2": {"A1": {"3c:8a:1f:9a:66:c8": [-60] * 40}},
            "p3": {"A1": {"3c:8a:1f:9a:66:c8": [-66] * 80,
                          "06:b4:bb:c0:24:f0": [-50] * 80}},   # day 2 only
        },
    }
    return calibration_report(windows, truth, traffic, faults={"A1": ["p2"]})


def test_holes_flag_points_below_30_and_without_sufficient_windows(report):
    points = report["points"]
    assert points["p1"]["n_sufficient"] == 40 and points["p1"]["hole"] is None
    assert points["p2"]["n_sufficient"] == 5 and points["p2"]["hole"] == "below_30"
    assert points["p3"]["n_sufficient"] == 0 and points["p3"]["hole"] == "empty"
    assert report["recapture"] == ["p2", "p3"]


def test_a_missing_anchor_is_out_of_range_or_a_field_noted_fault(report):
    p2 = report["points"]["p2"]["anchors"]
    assert p2["A1"]["status"] == "fault"
    assert p2["A2"]["status"] == "out_of_range"
    assert p2["A3"]["status"] == "heard"
    assert p2["A3"]["windows_heard"] == 20
    assert p2["A3"]["median_rssi"] == -82


def test_unusually_quiet_anchor_is_hinted_but_not_called_a_fault(report):
    p3_a2 = report["points"]["p3"]["anchors"]["A2"]
    assert p3_a2["status"] == "out_of_range"
    assert p3_a2["low_traffic"] is True
    assert report["points"]["p1"]["anchors"]["A2"]["low_traffic"] is False


def test_above_floor_rate_predicts_sniper_eligibility(report):
    floor = report["above_floor"]
    # p1: 40 windows x 4 Anchors, 40 + 40 + 10 + 0 above; p2: 20 x 2 heard, 20 above;
    # p3: 1 heard, none above. Rate is over heard (window, Anchor) pairs.
    assert floor["rate"] == pytest.approx((90 + 20) / (160 + 40 + 1))
    # Windows with >= 3 Anchors above the floor: 10 of p1's 40, none elsewhere.
    assert floor["sniper_eligible_rate"] == pytest.approx(10 / 61)
    assert report["points"]["p1"]["anchors"]["A3"]["above_floor_rate"] == pytest.approx(0.25)


def test_day_boundary_drift_uses_ambient_devices(report):
    drift = report["drift"]
    assert [d["points"] for d in drift["days"]] == [["p1", "p2"], ["p3"]]
    (row,) = drift["rows"]
    assert (row["anchor"], row["mac"]) == ("A1", "3c:8a:1f:9a:66:c8")
    assert row["delta_db"] == pytest.approx(-6.0)
    assert row["random_mac"] is False        # 0x3c: globally administered
