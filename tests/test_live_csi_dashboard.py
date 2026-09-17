"""Tests for scripts/live_csi_dashboard.py's pure parts (no matplotlib)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from datetime import datetime, timezone

import numpy as np

from tests.conftest import make_csi_line, make_stat_line

_SCRIPT_PATH = Path(__file__).parent.parent / "scripts" / "live_csi_dashboard.py"
_spec = importlib.util.spec_from_file_location("live_csi_dashboard", _SCRIPT_PATH)
dash = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = dash
_spec.loader.exec_module(dash)

RELAY = "68:fe:71:fa:df:fc"
PHONE = "aa:bb:cc:dd:ee:01"


def _row(line: str, t: float = 0.0) -> str:
    iso = datetime.fromtimestamp(t, timezone.utc).isoformat()
    return f'{iso},1,"{line}"\n'


def _payload(line: str):
    return dash.payload_from_row(_row(line))[0]


def test_read_new_lines_leaves_partial_line_for_next_call(tmp_path):
    p = tmp_path / "A1_x.csv"
    p.write_text("host_iso,host_ns,line\nrow1\nrow2 partial")
    with open(p, newline="") as fh:
        assert list(dash.read_new_lines(fh)) == ["host_iso,host_ns,line\n", "row1\n"]
        with open(p, "a") as w:
            w.write(" done\nrow3\n")
        assert list(dash.read_new_lines(fh)) == ["row2 partial done\n", "row3\n"]
        assert list(dash.read_new_lines(fh)) == []


def test_read_new_lines_limit_resumes_where_it_stopped(tmp_path):
    p = tmp_path / "A1_x.csv"
    p.write_text("a\nb\nc\n")
    with open(p, newline="") as fh:
        assert list(dash.read_new_lines(fh, limit=2)) == ["a\n", "b\n"]
        assert list(dash.read_new_lines(fh, limit=2)) == ["c\n"]


def test_payload_from_row_accepts_csi_and_rejects_header_and_stat():
    assert dash.payload_from_row("host_iso,host_ns,line\n") is None
    assert dash.payload_from_row(_row(make_stat_line())) is None
    parsed = dash.payload_from_row(_row(make_csi_line(mac=PHONE, rssi=-40), t=1234.5))
    assert parsed is not None
    p, t_host = parsed
    assert p.mac == PHONE and p.rssi == -40 and t_host == 1234.5


def test_clean_amplitudes_fills_zero_bins_with_mean_of_rest():
    amps = np.full(64, 20.0, dtype=np.float32)
    amps[5] = 0.0  # subcarrier +5, usable
    cleaned = dash.clean_amplitudes(amps)
    assert cleaned.shape == (51,)
    assert np.all(cleaned == 20.0)


def test_moving_average_rows_matches_centred_movmean():
    buf = np.arange(10, dtype=float)[:, None]
    out = dash.moving_average_rows(buf, 3)[:, 0]
    assert out[0] == 0.5            # edge: mean(0,1)
    assert out[5] == 5.0            # interior: mean(4,5,6)
    assert out[-1] == 8.5           # edge: mean(8,9)
    assert np.array_equal(dash.moving_average_rows(buf, 1), buf)


def test_state_counts_every_mac_but_only_plots_unfiltered():
    st = dash.DashboardState(window=4, smooth_span=1, exclude_macs=frozenset({RELAY}))
    relay = _payload(make_csi_line(mac=RELAY, seq=1))
    phone = _payload(make_csi_line(mac=PHONE, seq=2, rssi=-55))
    assert st.push(relay, 0.0) is False
    assert st.push(phone, 0.1) is True
    assert st.mac_counts == {RELAY: 1, PHONE: 1}
    assert st.shown == 1 and st.skipped == 1
    assert list(st.rssi) == [-55]
    assert st.raw[-1].tolist() == phone.amps_hw.tolist()
    assert st.top_macs(1) in ([(RELAY, 1)], [(PHONE, 1)])


def test_state_tracks_seq_gaps_and_rate():
    st = dash.DashboardState(window=10, smooth_span=3)
    for i, seq in enumerate([1, 2, 5]):
        st.push(_payload(make_csi_line(seq=seq)), float(i))
    assert st.seq_gaps == 2
    assert st.rate_hz(horizon_s=5.0) == 2 / 5.0
    assert st.smoothed().shape == st.clean.shape
