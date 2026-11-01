"""Trimmed vs untrimmed Calibration windows (#47)."""

from __future__ import annotations

import numpy as np
import pytest

from gateway.radiomap import AnchorFingerprint, RadioMap, ReferencePoint
from gateway.trim_ablation import compare_maps, leave_one_out, recordings, unmapped_points

ANCHORS = ["A1", "A2", "A3", "A4"]


def _point(x, y, rssi, n_windows=10):
    return ReferencePoint(x=x, y=y, n_windows=n_windows, anchors={
        a: AnchorFingerprint(rssi=r, dcfr=np.zeros(3), amp=np.ones(4))
        for a, r in zip(ANCHORS, rssi)
    })


def _map(**points):
    return RadioMap(anchor_ids=ANCHORS, points=points)


NEAR_A1 = [-50, -60, -70, -80]
NEAR_A4 = [-80, -70, -60, -50]


def test_leave_one_out_scores_each_point_against_the_rest():
    # Two look-alike pairs 1 m and 2 m apart: each point's nearest
    # fingerprint is its twin, so k = 1 errors are 1, 1, 2, 2.
    rmap = _map(
        a=_point(0.0, 0.0, NEAR_A1), b=_point(1.0, 0.0, [-51, -60, -70, -79]),
        c=_point(5.0, 0.0, NEAR_A4), d=_point(5.0, 2.0, [-79, -70, -60, -51]),
    )
    result = leave_one_out(rmap, k=1)
    assert result["errors"] == pytest.approx({"a": 1.0, "b": 1.0, "c": 2.0, "d": 2.0})
    assert result["median_m"] == pytest.approx(1.5)
    assert result["mean_m"] == pytest.approx(1.5)


def test_compare_maps_reports_per_point_and_anchor_differences():
    trimmed = _map(p1=_point(1.2, 6.0, NEAR_A1, n_windows=240), p2=_point(2.4, 6.0, NEAR_A1))
    untrimmed = _map(p1=_point(1.2, 6.0, [-52, -60, -70, -77], n_windows=300))
    rows = compare_maps(trimmed, untrimmed)

    p1 = {r["anchor"]: r for r in rows if r["point"] == "p1"}
    assert p1["A1"]["rssi_delta_db"] == pytest.approx(-2.0)   # untrimmed - trimmed
    assert p1["A4"]["rssi_delta_db"] == pytest.approx(3.0)
    assert p1["A1"]["dcfr_distance"] == pytest.approx(0.0)
    assert p1["A1"]["n_windows"] == (240, 300)
    # A point in only one map is listed, not dropped.
    (p2,) = [r for r in rows if r["point"] == "p2"]
    assert p2["anchor"] is None and p2["n_windows"] == (10, 0)


def test_compare_maps_reports_the_amplitude_distance_too():
    trimmed = _map(p1=_point(1.2, 6.0, NEAR_A1))
    untrimmed = _map(p1=_point(1.2, 6.0, NEAR_A1))
    untrimmed.points["p1"].anchors["A2"].amp = np.array([1.0, 1.0, 1.0, 3.0])
    rows = {r["anchor"]: r for r in compare_maps(trimmed, untrimmed)}
    assert rows["A1"]["amp_distance"] == pytest.approx(0.0)
    assert rows["A2"]["amp_distance"] == pytest.approx(2.0)


def test_unmapped_points_are_the_trials_with_no_sufficient_window():
    rmap = _map(p1=_point(1.2, 6.0, NEAR_A1), p3=_point(3.6, 6.0, NEAR_A1))
    truth = {"trials": [{"id": "p1"}, {"id": "p2"}, {"id": "p3"}, {"id": "p4"}]}
    assert unmapped_points(rmap, truth) == ["p2", "p4"]


def test_recordings_flag_long_and_short_beacon_spans():
    def trial(tid, minutes, short=False):
        return {"id": tid, "beacon_first": 0.0, "beacon_last": 60.0 * minutes,
                "short": short}
    truth = {"trials": [trial("p1", 6.0), trial("p2", 4.4, short=True),
                        trial("p3", 7.0), trial("p4", 23.6)]}
    rec = recordings(truth)
    assert rec["median_min"] == pytest.approx(6.5)
    assert rec["long"] == [("p4", pytest.approx(23.6))]
    assert rec["short"] == [("p2", pytest.approx(4.4))]
