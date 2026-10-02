"""k-NN baseline (ADR-0002): feature vector and inverse-distance-weighted estimate (#26)."""

from __future__ import annotations

import numpy as np
import pytest

from gateway.knn import RSSI_FLOOR_DBM, KnnLocalizer, feature_vector
from gateway.radiomap import AnchorFingerprint, RadioMap, ReferencePoint

ANCHORS = ["A1", "A2", "A3", "A4"]
N_DCFR = 6


def _point(rng, x, y):
    return ReferencePoint(
        x=x, y=y, n_windows=10,
        anchors={
            a: AnchorFingerprint(
                rssi=float(rng.uniform(-80, -40)),
                dcfr=rng.normal(0, 0.05, N_DCFR),
                amp=rng.uniform(0.1, 0.2, N_DCFR + 1),
            )
            for a in ANCHORS
        },
    )


@pytest.fixture
def radio_map():
    rng = np.random.default_rng(0)
    points = {
        f"R{i + 1:02d}": _point(rng, float(x), float(y))
        for i, (x, y) in enumerate([(0.5, 0.5), (1.5, 0.5), (0.5, 1.5), (1.5, 1.5), (2.5, 2.5)])
    }
    return RadioMap(anchor_ids=ANCHORS, points=points)


def _window_from(point, sufficient=True):
    return {
        "sufficient": sufficient,
        "anchors": {
            a: None if fp is None else {"rssi": fp.rssi, "dcfr": fp.dcfr.tolist()}
            for a, fp in point.anchors.items()
        },
    }


def test_own_fingerprint_returns_the_reference_point_exactly(radio_map):
    knn = KnnLocalizer(radio_map, k=3)
    for point in radio_map.points.values():
        assert knn.estimate(_window_from(point)) == (point.x, point.y)


def test_insufficient_window_gives_no_estimate(radio_map):
    knn = KnnLocalizer(radio_map, k=3)
    point = radio_map.points["R01"]
    assert knn.estimate(_window_from(point, sufficient=False)) is None


def test_missing_anchor_is_floor_imputed(radio_map):
    knn = KnnLocalizer(radio_map, k=3)
    window = _window_from(radio_map.points["R02"])
    window["anchors"]["A4"] = None
    x, y = knn.estimate(window)
    assert 0.5 <= x <= 2.5 and 0.5 <= y <= 2.5


def test_rssi_is_z_scored_over_the_anchors_present():
    """ADR-0002: mean and sd over the Anchors present; a missing Anchor is
    placed at the floor on that scale, with zero D-CFR."""
    anchors = {
        "A1": {"rssi": -50.0, "dcfr": [0.1] * N_DCFR},
        "A2": {"rssi": -60.0, "dcfr": [0.2] * N_DCFR},
        "A3": {"rssi": -70.0, "dcfr": [0.3] * N_DCFR},
        "A4": None,
    }
    vec = feature_vector(anchors, ANCHORS, N_DCFR)
    present = np.array([-50.0, -60.0, -70.0])
    mu, sd = present.mean(), present.std()
    expected = np.append((present - mu) / sd, (RSSI_FLOOR_DBM - mu) / sd)
    np.testing.assert_allclose(vec[:4], expected / np.sqrt(4))
    np.testing.assert_allclose(vec[4 + 3 * N_DCFR:], 0.0)


def test_missing_anchor_never_looks_stronger_than_a_present_one():
    anchors = {
        "A1": {"rssi": -60.0, "dcfr": None},
        "A2": {"rssi": -84.0, "dcfr": None},          # below the -80 floor
        "A3": {"rssi": -70.0, "dcfr": None},
        "A4": None,
    }
    vec = feature_vector(anchors, ANCHORS, N_DCFR)
    assert vec[3] <= vec[1]


def test_estimate_is_inverse_distance_weighted(radio_map):
    """Halfway (in feature space) between two points with k=2 -> midpoint."""
    a, b = radio_map.points["R01"], radio_map.points["R02"]
    knn = KnnLocalizer(RadioMap(anchor_ids=ANCHORS, points={"R01": a, "R02": b}), k=2)
    fa = feature_vector(_window_from(a)["anchors"], ANCHORS, N_DCFR)
    fb = feature_vector(_window_from(b)["anchors"], ANCHORS, N_DCFR)
    x, y = knn.estimate_from_vector((fa + fb) / 2)
    assert (x, y) == pytest.approx(((a.x + b.x) / 2, (a.y + b.y) / 2))


def test_feature_blocks_have_equal_weight():
    anchors = {
        "A1": {"rssi": -50.0, "dcfr": [0.1, -0.1, 0.2, 0.0, 0.1, -0.2]},
        "A2": {"rssi": -60.0, "dcfr": [0.0] * N_DCFR},
        "A3": {"rssi": -70.0, "dcfr": [0.3] * N_DCFR},
        "A4": {"rssi": -80.0, "dcfr": [-0.1, 0.1] * 3},
    }
    vec = feature_vector(anchors, ANCHORS, N_DCFR)
    assert vec.shape == (4 + 4 * N_DCFR,)
    rssi = np.array([-50.0, -60.0, -70.0, -80.0])
    z = (rssi - rssi.mean()) / rssi.std()
    np.testing.assert_allclose(vec[:4], z / np.sqrt(4))
    # D-CFR is mean-centred per Anchor (tilt-invariant) and scaled by 1/sqrt(dim).
    a3 = vec[4 + 2 * N_DCFR: 4 + 3 * N_DCFR]
    np.testing.assert_allclose(a3, 0.0, atol=1e-12)
    a1 = np.array(anchors["A1"]["dcfr"])
    np.testing.assert_allclose(vec[4:4 + N_DCFR], (a1 - a1.mean()) / np.sqrt(4 * N_DCFR))
