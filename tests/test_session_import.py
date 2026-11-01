"""Importing a real Calibration session recorded as one zip per Reference point (#45)."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from gateway.radiomap import build_radio_map
from gateway.evaluate import preprocess_session
from gateway.session_import import import_session
from gateway.sim import load_layout

from conftest import make_logged_row, make_wireless_csi_line

LAYOUT = Path(__file__).resolve().parents[1] / "layouts" / "techhub_default.yaml"
AMBIENT = "aa:bb:cc:dd:ee:01"


@pytest.fixture(scope="module")
def layout():
    return load_layout(LAYOUT)


def _write_point(src: Path, point: str, beacon_mac: str, t0: float, t1: float,
                 step: float = 0.5) -> None:
    """One point's zip as the team uploads it: data/A{n}_<stamp>.csv inside."""
    (src / point).mkdir(parents=True)
    with zipfile.ZipFile(src / point / f"data_{point}.zip", "w") as zf:
        for anchor, rssi in (("A1", -60), ("A2", -70), ("A3", -75), ("A4", -65)):
            rows = ["host_iso,host_ns,line"]
            # Ambient traffic starts earlier and ends later than the Beacon.
            rows.append(make_logged_row(t0 - 20.0, make_wireless_csi_line(anchor, mac=AMBIENT)))
            t, seq = t0, 1
            while t <= t1 + 1e-9:
                rows.append(make_logged_row(
                    t, make_wireless_csi_line(anchor, seq=seq, mac=beacon_mac, rssi=rssi)))
                t, seq = t + step, seq + 1
            rows.append(make_logged_row(t1 + 20.0, make_wireless_csi_line(anchor, mac=AMBIENT)))
            zf.writestr(f"data/{anchor}_20261029_113718.csv", "\n".join(rows) + "\n")


@pytest.fixture(scope="module")
def source(tmp_path_factory, layout):
    src = tmp_path_factory.mktemp("compiled_data")
    mac = layout.devices["beacon"].mac
    _write_point(src, "p1", mac, 1_000.0, 1_300.0)      # 5 min: enough
    _write_point(src, "p2", mac, 2_000.0, 2_200.0)      # 200 s: too short to trim
    return src


def test_trimmed_trials_skip_30_s_and_keep_4_min(source, layout, tmp_path):
    truth = import_session(source, layout, tmp_path, points=["p1", "p2"])

    p1, p2 = truth["trials"]
    assert p1["id"] == "p1"
    assert (p1["t_start"], p1["t_end"]) == pytest.approx((1_030.0, 1_270.0))
    beacon = p1["devices"][0]
    assert beacon["role"] == "beacon"
    assert beacon["mac"] == layout.devices["beacon"].mac
    assert (beacon["x"], beacon["y"]) == (1.2, 6.0)
    assert not p1["short"]
    assert p2["short"]                       # flagged, not silently shortened
    assert truth["short"] == ["p2"]


def test_untrimmed_trials_span_the_beacons_records(source, layout, tmp_path):
    truth = import_session(source, layout, tmp_path, points=["p1"], trim=None)

    (p1,) = truth["trials"]
    assert p1["t_start"] == pytest.approx(1_000.0)
    assert p1["t_end"] > 1_300.0             # the last Record is inside [t_start, t_end)
    assert p1["t_end"] < 1_301.0             # the ambient tail is not


def test_imported_session_builds_a_radio_map(source, layout, tmp_path):
    truth = import_session(source, layout, tmp_path, points=["p1"])

    session_dir = tmp_path / "calibration"
    assert json.loads((session_dir / "ground_truth.json").read_text()) == truth
    assert sorted(p.name for p in (session_dir / "p1").glob("*.csv")) == [
        f"A{n}_20261029_113718.csv" for n in range(1, 5)
    ]
    meta, windows, on_disk = preprocess_session(session_dir, tmp_path / "w.jsonl")
    rmap = build_radio_map(windows, meta, on_disk)
    point = rmap.points["p1"]
    assert (point.x, point.y) == (1.2, 6.0)
    assert 230 <= point.n_windows <= 241     # the 4 min kept, 1 s windows
    assert point.anchors["A1"].rssi == pytest.approx(-60.0)


def test_point_without_a_recording_is_an_error(source, layout, tmp_path):
    with pytest.raises(FileNotFoundError, match="p3"):
        import_session(source, layout, tmp_path, points=["p1", "p3"])
