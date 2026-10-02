from __future__ import annotations

import numpy as np
import pytest

from gateway.features import build_anchor_feature
from gateway.records import CsiRecord


def _record(rssi: int, amps: np.ndarray, seq: int = 0) -> CsiRecord:
    return CsiRecord(
        anchor="A1", seq=seq, mac="aa:bb:cc:dd:ee:ff", rssi=rssi, sig_mode=1,
        channel=6, timestamp_us=0, t_host=float(seq), host_ns=0,
        amps_hw=amps.astype(np.float32),
    )


def _amps(seed: int) -> np.ndarray:
    return np.random.default_rng(seed).uniform(5, 30, size=64)


def test_identical_records_are_fully_stable():
    amps = _amps(0)
    recs = [_record(-60, amps, seq=i) for i in range(5)]
    assert build_anchor_feature(recs).stability == pytest.approx(1.0)


def test_single_record_has_no_stability():
    assert build_anchor_feature([_record(-60, _amps(0))]).stability is None


def test_dead_records_do_not_count_toward_stability():
    recs = [_record(-60, _amps(0)), _record(-60, np.zeros(64), seq=1)]
    assert build_anchor_feature(recs).stability is None


@pytest.mark.parametrize("rssi, expected", [(-79, True), (-80, False), (-81, False)])
def test_above_floor_is_strict(rssi, expected):
    recs = [_record(rssi, _amps(i), seq=i) for i in range(3)]
    assert build_anchor_feature(recs, rssi_floor=-80.0).above_floor is expected
