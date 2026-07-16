from __future__ import annotations

import numpy as np

from gateway.parser import (
    CsiPayload,
    StatPayload,
    iter_logged_records,
    parse_firmware_line,
)
from gateway.records import CsiRecord, ParseStats, StatRecord
from tests.conftest import make_csi_line, make_logged_row, make_stat_line


def test_valid_csi_line_fields():
    p = parse_firmware_line(make_csi_line(anchor="A2", seq=42, rssi=-61))
    assert isinstance(p, CsiPayload)
    assert p.anchor == "A2"
    assert p.seq == 42
    assert p.mac == "a4:cf:12:3b:9e:01"
    assert p.rssi == -61
    assert p.sig_mode == 1
    assert p.channel == 6
    assert p.timestamp_us == 123456789
    assert p.amps_hw.shape == (64,)
    assert p.amps_hw.dtype == np.float32


def test_valid_stat_line():
    p = parse_firmware_line(make_stat_line(dropped=3))
    assert isinstance(p, StatPayload)
    assert p.dropped == 3
    assert p.free_heap == 180000


def test_unknown_prefix_returns_none():
    assert parse_firmware_line("ets Jul 29 2019 12:21:46") is None
    assert parse_firmware_line("INFO,A1,channel=6,udp=0,raw_iq=0") is None


def test_wrong_value_count_rejected():
    line = make_csi_line()  # n_sub says 64
    truncated = ",".join(line.split(",")[:-1])  # 63 values
    assert parse_firmware_line(truncated) is None


def test_non_integer_field_rejected():
    assert parse_firmware_line(make_csi_line(rssi="abc")) is None


def test_bad_mac_rejected():
    assert parse_firmware_line(make_csi_line(mac="zz:zz:zz:zz:zz:zz")) is None
    assert parse_firmware_line(make_csi_line(mac="a4cf123b9e01")) is None


def test_bad_n_sub_rejected():
    assert parse_firmware_line(make_csi_line(values=[1, 2, 3])) is None  # n_sub=3


def test_raw_iq_line_amplitudes():
    # 64 pairs of (imag, real) = (3, 4) -> amplitude 5 everywhere.
    values = [3, 4] * 64
    p = parse_firmware_line(make_csi_line(values=values))
    assert isinstance(p, CsiPayload)
    assert p.amps_hw.shape == (64,)
    assert np.allclose(p.amps_hw, 5.0)


def test_iter_logged_records(tmp_path):
    f = tmp_path / "A1_test.csv"
    rows = [
        "host_iso,host_ns,line",
        make_logged_row(1000.0, make_csi_line(seq=1)),
        make_logged_row(1000.1, "boot garbage not a record"),
        make_logged_row(1000.2, make_stat_line()),
        make_logged_row(1000.3, "CSI,A1,broken"),
        'not,a,valid,row,with,many,fields',
    ]
    f.write_text("\n".join(rows) + "\n")

    stats = ParseStats()
    records = list(iter_logged_records(f, stats))

    kinds = [type(r) for r in records]
    assert kinds == [CsiRecord, StatRecord]
    assert stats.csi == 1
    assert stats.stat == 1
    assert stats.ignored_prefix == 1
    assert stats.malformed == 2  # broken CSI line + bad row shape
    assert records[0].t_host == 1000.0


def test_truncated_last_line_skipped(tmp_path):
    f = tmp_path / "A1_test.csv"
    good = make_logged_row(1000.0, make_csi_line())
    truncated = make_logged_row(1000.1, make_csi_line())[:40]  # cut mid-line
    f.write_text("host_iso,host_ns,line\n" + good + "\n" + truncated)

    stats = ParseStats()
    records = list(iter_logged_records(f, stats))
    assert len(records) == 1
    assert stats.malformed == 1
