from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from gateway.parser import (
    CsiPayload,
    StatPayload,
    iter_logged_records,
    load_session,
    parse_firmware_line,
)
from gateway.records import CsiRecord, ParseStats, StatRecord
from tests.conftest import LEGACY_DIR, make_csi_line, make_logged_row, make_stat_line


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


# Trimmed, MAC-anonymised excerpt of the 2026-08-28 Pi-era Captures
# (host_iso,host_ns,type,anchor_id,seq,mac,rssi,channel,len,csi_payload).
LEGACY_A1 = LEGACY_DIR / "A1_20260828_140440.csv"


def test_legacy_capture_first_record():
    stats = ParseStats()
    first = next(iter_logged_records(LEGACY_A1, stats))

    # Hand-read from the fixture's first data row.
    assert isinstance(first, CsiRecord)
    assert first.anchor == "A1"
    assert first.seq == 1329
    assert first.mac == "02:ab:cd:00:00:01"   # file has it uppercase
    assert first.rssi == -86
    assert first.channel == 11
    assert first.sig_mode == 0 and first.timestamp_us == 0  # not in legacy format
    assert first.t_host == pytest.approx(1787899225.832231)  # 06:40:25.832231Z
    assert first.host_ns == 2399798873288
    # [imag, real] pairs: hw2 = (-57, 0), hw10 = (-21, 0), hw11 = (-9, 7).
    assert first.amps_hw.shape == (64,)
    assert first.amps_hw[2] == 57.0
    assert first.amps_hw[10] == 21.0
    assert first.amps_hw[11] == pytest.approx(np.sqrt(130))


def test_legacy_captures_count_truncated_payloads_as_malformed():
    csi, stat, stats = load_session([LEGACY_DIR])

    # 109 + 94 rows; three have payloads cut short (85, 86 and 90 values).
    assert stats.total_rows == 203
    assert stats.malformed == 3
    assert stats.csi == len(csi) == 200
    assert stats.per_anchor == {"A1": 108, "A2": 92}
    assert stat == []
    assert all(r.mac == r.mac.lower() for r in csi)


def _legacy_capture(tmp_path, rows):
    f = tmp_path / "A1_legacy.csv"
    header = "host_iso,host_ns,type,anchor_id,seq,mac,rssi,channel,len,csi_payload"
    f.write_text("\n".join([header, *rows]) + "\n")
    return f


ISO = "2026-08-28T06:40:25+00:00"
PAYLOAD = '"' + ",".join(["3,4"] * 64) + '"'  # [imag, real] = (3, 4) -> amplitude 5


def test_legacy_malformed_and_non_csi_rows(tmp_path):
    f = _legacy_capture(tmp_path, [
        f"{ISO},1,CSI,A1,7,AA:BB:CC:DD:EE:0F,-60,11,128,{PAYLOAD}",
        f"{ISO},2,CSI,A1,8,not-a-mac,-60,11,128,{PAYLOAD}",
        f"{ISO},3,CSI,A1,9,AA:BB:CC:DD:EE:0F,-60,11,128",   # no payload column
        f"{ISO},4,CSI,A1,10,AA:BB:CC:DD:EE:0F,abc,11,128,{PAYLOAD}",
        f"{ISO},5,STAT,A1,5000,100,80,80,0,180000",          # listener wrote it verbatim
        f"{ISO},6,ets Jul 29 2019 12:21:46",
    ])

    stats = ParseStats()
    records = list(iter_logged_records(f, stats))

    assert [type(r) for r in records] == [CsiRecord, StatRecord]
    assert records[0].mac == "aa:bb:cc:dd:ee:0f"
    assert np.allclose(records[0].amps_hw, 5.0)
    assert records[1].free_heap == 180000
    assert stats.total_rows == 6
    assert stats.malformed == 3
    assert stats.ignored_prefix == 1


def test_legacy_and_logger_captures_load_together(tmp_path):
    legacy = _legacy_capture(tmp_path, [
        f"{ISO},1,CSI,A1,7,AA:BB:CC:DD:EE:0F,-60,11,128,{PAYLOAD}",
    ])
    logger = tmp_path / "A2_logger.csv"
    logger.write_text(
        "host_iso,host_ns,line\n"
        + make_logged_row(1787899224.0, make_csi_line(anchor="A2")) + "\n"
    )

    csi, _, stats = load_session([legacy, logger])

    # ISO is 1787899225.0; the logger Record is one second earlier.
    assert [(r.anchor, r.t_host) for r in csi] == [("A2", 1787899224.0), ("A1", 1787899225.0)]
    assert [r.sig_mode for r in csi] == [1, 0]
    assert stats.csi == 2 and stats.malformed == 0


def test_legacy_header_with_byte_order_mark_is_detected(tmp_path):
    # Files saved from Excel / Windows editors start with a UTF-8 BOM.
    path = tmp_path / "A1_bom.csv"
    path.write_bytes(b"\xef\xbb\xbf" + LEGACY_A1.read_bytes())
    stats = ParseStats()
    records = list(iter_logged_records(path, stats))
    assert stats.csi == len(records) > 0


def test_unrecognised_header_falls_back_to_logger_format(tmp_path):
    # A legacy file with a renamed column is not guessed at: it reads as the
    # logger format, so every row is counted malformed rather than misread.
    lines = LEGACY_A1.read_text().splitlines()
    path = tmp_path / "A1_renamed.csv"
    path.write_text("\n".join([lines[0].replace("anchor_id", "anchor")] + lines[1:]) + "\n")
    stats = ParseStats()
    assert list(iter_logged_records(path, stats)) == []
    assert stats.malformed == stats.total_rows == len(lines) - 1
