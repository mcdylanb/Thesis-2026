"""Shared fixture builders for well-formed firmware lines and logger rows."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest


def _default_amps():
    # 64 values, zeros at DC(0) and guard(27..37), non-zero elsewhere.
    amps = []
    for i in range(64):
        if i == 0 or 27 <= i <= 37:
            amps.append(0)
        else:
            amps.append(10 + (i % 7))
    return amps


def make_csi_line(
    anchor="A1",
    seq=1,
    mac="a4:cf:12:3b:9e:01",
    rssi=-58,
    sig_mode=1,
    channel=6,
    timestamp_us=123456789,
    values=None,
    n_sub=None,
):
    values = _default_amps() if values is None else values
    n_sub = len(values) if n_sub is None else n_sub
    return (
        f"CSI,{anchor},{seq},{mac},{rssi},{sig_mode},{channel},{timestamp_us},"
        f"{n_sub}," + ",".join(str(v) for v in values)
    )


def make_stat_line(anchor="A1", uptime_ms=5000, pkts_seen=100, csi_cb=80,
                   queued=80, dropped=0, free_heap=180000):
    return f"STAT,{anchor},{uptime_ms},{pkts_seen},{csi_cb},{queued},{dropped},{free_heap}"


def make_logged_row(t_epoch: float, line: str) -> str:
    iso = datetime.fromtimestamp(t_epoch, timezone.utc).isoformat()
    return f'{iso},{int(t_epoch * 1e9)},"{line}"'


@pytest.fixture
def csi_line():
    return make_csi_line()


@pytest.fixture
def stat_line():
    return make_stat_line()
