"""Live point checker: per-Anchor strength and the move-on verdict (#50)."""

from __future__ import annotations

import os

import numpy as np
import pytest

from gateway.check_point import SessionTail, assess, main
from gateway.records import CsiRecord
from pathlib import Path

from tests.conftest import _default_amps, make_csi_line, make_logged_row

TRIAL_LAYOUT = Path(__file__).resolve().parents[1] / "layouts" / "techhub_trial_4p8.yaml"

BEACON = "68:fe:71:fa:df:fc"
OTHER = "3c:8a:1f:9a:66:c8"
ANCHORS = ("A1", "A2", "A3", "A4")
T0 = 1_000.0
AMPS = np.array(_default_amps(), dtype=np.float32)


def _records(anchor, rssi, start_s=0.0, end_s=300.0, mac=BEACON, rate_hz=5.0):
    """Records from one Anchor at a fixed RSSI, `rate_hz` per second.
    `rssi` may be a function of the time since T0."""
    out = []
    for k in range(int((end_s - start_s) * rate_hz)):
        t = start_s + k / rate_hz + 0.01
        value = rssi(t) if callable(rssi) else rssi
        out.append(CsiRecord(anchor=anchor, seq=k, mac=mac, rssi=int(value), sig_mode=1,
                             channel=6, timestamp_us=0, t_host=T0 + t,
                             host_ns=int((T0 + t) * 1e9), amps_hw=AMPS))
    return out


def _by_anchor(check):
    return {a.anchor: a for a in check.anchors}


def test_an_anchor_is_strong_when_most_heard_windows_clear_the_floor():
    recs = _records("A1", -70) + _records("A2", -85) + _records("A3", -72)
    check = assess(recs, BEACON, ANCHORS)
    a = _by_anchor(check)
    assert [x.anchor for x in check.anchors if x.strong] == ["A1", "A3"]
    assert a["A2"].median_rssi == pytest.approx(-85.0)
    assert a["A2"].above_share == 0.0
    assert a["A4"].windows_heard == 0 and not a["A4"].strong
    assert check.n_strong == 2
    assert check.state == "WEAK"


def test_an_anchor_that_is_mostly_silent_is_not_strong():
    # The Sniper needs 3 Anchors above the floor in the same window, so a
    # loud but mostly silent Anchor does not count (pilot point p56's A1).
    recs = _records("A1", -70) + _records("A2", -70) \
        + _records("A3", -70, rate_hz=0.2)  # heard in about 1 window in 5
    a = _by_anchor(assess(recs, BEACON, ANCHORS))
    assert a["A3"].median_rssi == pytest.approx(-70.0)
    assert a["A3"].above_share < 0.5
    assert not a["A3"].strong


def test_three_strong_anchors_and_a_full_recording_is_good():
    recs = sum((_records(a, -70) for a in ("A1", "A2", "A3")), [])
    check = assess(recs, BEACON, ANCHORS)
    assert check.state == "GOOD"
    # Only the kept part counts, as in the import: 30 s settle + 240 s.
    assert check.sufficient == 240


def test_a_short_recording_keeps_recording_even_when_strong():
    recs = sum((_records(a, -70, end_s=100.0) for a in ("A1", "A2", "A3")), [])
    check = assess(recs, BEACON, ANCHORS)
    assert check.state == "KEEP RECORDING"
    assert check.sufficient == 70
    assert check.elapsed_s == pytest.approx(100.0, abs=0.5)


def test_strength_is_judged_over_the_last_span_only():
    # A2 was strong, then dropped (e.g. someone stood in the way).
    recs = sum((_records(a, -70) for a in ("A1", "A3")), []) \
        + _records("A2", lambda t: -70 if t < 200 else -86)
    assert _by_anchor(assess(recs, BEACON, ANCHORS, span_s=30.0))["A2"].strong is False
    assert _by_anchor(assess(recs, BEACON, ANCHORS, span_s=None))["A2"].strong is True


def test_other_devices_are_ignored_and_no_beacon_is_reported():
    recs = _records("A1", -60, mac=OTHER)
    check = assess(recs, BEACON, ANCHORS)
    assert check.state == "NO BEACON"
    assert check.n_strong == 0


# --- following the listener's files -------------------------------------------


def _row(anchor, t, rssi=-70):
    line = make_csi_line(anchor=anchor, mac=BEACON, rssi=rssi)
    return (make_logged_row(T0 + t, line) + "\n").encode()


def test_a_half_written_row_waits_for_the_rest(tmp_path):
    path = tmp_path / "A1_20261102_100000.csv"
    full, half = _row("A1", 0.0), _row("A1", 1.0)
    path.write_bytes(b"host_iso,host_ns,line\n" + full + half[:40])
    tail = SessionTail(tmp_path)
    assert [r.t_host for r in tail.poll()] == [T0]
    with open(path, "ab") as fh:
        fh.write(half[40:])
    assert [r.t_host for r in tail.poll()] == [T0, T0 + 1.0]


def test_a_new_listen_session_starts_a_new_point(tmp_path):
    old = tmp_path / "A1_20261102_100000.csv"
    old.write_bytes(b"host_iso,host_ns,line\n" + _row("A1", 0.0))
    tail = SessionTail(tmp_path)
    assert len(tail.poll()) == 1 and tail.stamp == "20261102_100000"
    new = tmp_path / "A2_20261102_101000.csv"
    new.write_bytes(b"host_iso,host_ns,line\n" + _row("A2", 600.0))
    os.utime(new, (os.path.getmtime(old) + 10,) * 2)
    records = tail.poll()
    assert tail.stamp == "20261102_101000"
    assert [r.anchor for r in records] == ["A2"]


# --- command ----------------------------------------------------------------


def _write_point(folder, rssi_by_anchor, seconds=300):
    for anchor, rssi in rssi_by_anchor.items():
        rows = b"".join(_row(anchor, k / 5 + 0.01, rssi) for k in range(seconds * 5))
        (folder / f"{anchor}_20261102_100000.csv").write_bytes(
            b"host_iso,host_ns,line\n" + rows)


def test_replaying_a_good_point_prints_the_table_and_the_verdict(tmp_path, capsys):
    _write_point(tmp_path, {"A1": -70, "A2": -72, "A3": -75, "A4": -88})
    assert main(["--data", str(tmp_path), "--layout", str(TRIAL_LAYOUT), "--once"]) == 0
    out = capsys.readouterr().out
    out.encode("ascii")  # plain ASCII: old Windows consoles show it as is
    assert "GOOD" in out
    assert "3/4 Anchors strong" in out
    a4 = next(line for line in out.splitlines() if line.startswith("A4"))
    assert "-88" in a4 and "weak" in a4


def test_replaying_a_weak_point_names_the_weak_anchors(tmp_path, capsys):
    _write_point(tmp_path, {"A1": -70, "A2": -86, "A3": -90})
    main(["--data", str(tmp_path), "--layout", str(TRIAL_LAYOUT), "--once"])
    out = capsys.readouterr().out
    assert "WEAK" in out and "1/4 Anchors strong" in out
    a4 = next(line for line in out.splitlines() if line.startswith("A4"))
    assert "not heard" in a4
