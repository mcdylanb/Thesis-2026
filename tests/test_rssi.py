from __future__ import annotations

import numpy as np
import pytest

from gateway.rssi import ewma, median_filter, smooth_series


def test_ewma_constant_series_is_constant():
    out = ewma(np.full(10, -60.0), alpha=0.3)
    assert np.allclose(out, -60.0)


def test_ewma_step_response_geometry():
    # Step from 0 to 1: after seeding at 0, sample k (0-based, k>=1) is
    # 1 - (1-alpha)^k ... verify monotone convergence toward 1.
    values = np.array([0.0] + [1.0] * 20)
    out = ewma(values, alpha=0.3)
    assert np.all(np.diff(out) >= 0)
    assert out[-1] > 0.99 * 1.0 - 0.05
    assert out[1] == pytest.approx(0.3, abs=1e-9)


def test_median_filter_rejects_outlier():
    values = np.array([-58.0, -59.0, -100.0, -58.0, -59.0])
    out = median_filter(values, k=5)
    assert out[2] == -59.0


def test_dispatcher_unknown_method():
    with pytest.raises(ValueError):
        smooth_series([1, 2, 3], method="kalman")


def test_dispatcher_empty_input():
    assert len(smooth_series([], method="ewma")) == 0
