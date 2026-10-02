from __future__ import annotations

import numpy as np
import pytest

from gateway.csi import (
    HW_TO_USABLE,
    N_DCFR,
    N_USABLE,
    dcfr,
    dcfr_stability,
    aggregate,
    hw_to_usable_indices,
    is_valid_csi,
    normalize,
    remap_hw64_to_usable,
    valid_spectra,
)


def test_remap_default_drops_dc_and_first_pos():
    # Default drops DC (0) and the corrupt subcarrier +1 (hw index 1).
    amps = np.arange(64, dtype=float)  # amps[i] = i
    out = remap_hw64_to_usable(amps)
    expected = list(range(38, 64)) + list(range(2, 27))  # 51 values
    assert out.tolist() == expected


def test_remap_keep_first_pos_gives_52():
    idx = hw_to_usable_indices(drop_first_pos=False)
    amps = np.arange(64, dtype=float)
    out = remap_hw64_to_usable(amps, idx)
    expected = list(range(38, 64)) + list(range(1, 27))  # 52 values
    assert out.tolist() == expected
    assert len(idx) == 52


def test_remap_drops_dc_guard_and_first_pos():
    dropped = {0, 1} | set(range(27, 38))
    assert dropped.isdisjoint(set(HW_TO_USABLE.tolist()))
    assert len(HW_TO_USABLE) == N_USABLE == 51


def test_remap_rejects_wrong_shape():
    with pytest.raises(ValueError):
        remap_hw64_to_usable(np.zeros(52))


def test_l2_norm_unit_length_and_scale_invariance():
    v = np.random.default_rng(0).uniform(1, 50, 51)
    n1 = normalize(v, "l2")
    assert np.isclose(np.linalg.norm(n1), 1.0)
    assert np.allclose(normalize(3 * v, "l2"), n1)


def test_center_norm():
    v = np.arange(51, dtype=float)
    assert np.isclose(normalize(v, "center").mean(), 0.0)


def test_unknown_norm_raises():
    with pytest.raises(ValueError):
        normalize(np.ones(52), "bogus")


def test_dcfr_known_vector():
    assert dcfr(np.array([1, 3, 6, 10])).tolist() == [2, 3, 4]


def test_dcfr_length_default():
    assert len(dcfr(np.ones(N_USABLE))) == N_DCFR == 50


def test_median_aggregate_rejects_outlier():
    base = np.full(51, 10.0)
    outlier = np.full(51, 100.0)
    agg = aggregate([base, base, outlier], "median")
    assert np.allclose(agg, 10.0)


def test_is_valid_csi():
    assert not is_valid_csi(np.zeros(51))
    assert not is_valid_csi(np.full(51, np.nan))
    assert is_valid_csi(np.ones(51))


def test_valid_spectra_drops_dead_records():
    good = np.zeros(64)
    good[1:27] = 10
    good[38:] = 10
    dead = np.zeros(64)
    spectra = valid_spectra([good, dead, good])
    assert len(spectra) == 2
    assert all(s.shape == (51,) for s in spectra)


def test_valid_spectra_all_dead():
    assert valid_spectra([np.zeros(64)]) == []


def test_stability_identical_records_is_one():
    v = np.random.default_rng(0).normal(size=N_DCFR)
    assert dcfr_stability([v, v.copy(), v.copy()]) == pytest.approx(1.0)


def test_stability_uncorrelated_records_is_near_zero():
    rng = np.random.default_rng(1)
    vectors = [rng.normal(size=N_DCFR) for _ in range(40)]
    assert abs(dcfr_stability(vectors)) < 0.05


def test_stability_single_record_is_none():
    assert dcfr_stability([np.ones(N_DCFR)]) is None
    assert dcfr_stability([]) is None


def test_stability_ignores_pairs_with_a_constant_vector():
    # Pearson is undefined against a zero-variance vector; skip those pairs
    # rather than letting NaN leak into the JSON output.
    v = np.random.default_rng(2).normal(size=N_DCFR)
    flat = np.zeros(N_DCFR)
    assert dcfr_stability([v, v.copy(), flat]) == pytest.approx(1.0)
    assert dcfr_stability([flat, flat.copy()]) is None
