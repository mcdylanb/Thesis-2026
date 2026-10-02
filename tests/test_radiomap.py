"""Radio map: build from a calibration session's windows, round-trip to disk (#26)."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from gateway.io import read_jsonl
from gateway.preprocess import PreprocessConfig, run
from gateway.radiomap import RadioMap, build_radio_map
from gateway.sim import load_layout, reference_grid, simulate_session

DEFAULT_LAYOUT = Path(__file__).resolve().parents[1] / "layouts" / "techhub_default.yaml"


@pytest.fixture(scope="module")
def calibration(tmp_path_factory):
    layout = load_layout(DEFAULT_LAYOUT)
    out = tmp_path_factory.mktemp("cal")
    truth = simulate_session(
        layout, out, "calibration", dwell_s=6.0, seed=11,
        positions=reference_grid(layout)[:3],
    )
    session = out / "calibration"
    run(PreprocessConfig(
        inputs=[session / t["id"] for t in truth["trials"]],
        out=out / "windows.jsonl", include_csi52=True,
    ))
    meta, windows = read_jsonl(out / "windows.jsonl")
    return layout, truth, meta, windows


def test_build_gives_one_entry_per_reference_point(calibration):
    layout, truth, meta, windows = calibration
    rmap = build_radio_map(windows, meta, truth)
    assert list(rmap.points) == ["R01", "R02", "R03"]
    r01 = rmap.points["R01"]
    assert (r01.x, r01.y) == (0.5, 0.5)
    assert r01.n_windows >= 5
    for anchor in ("A1", "A2", "A3", "A4"):
        fp = r01.anchors[anchor]
        assert -95 < fp.rssi < -20
        assert fp.dcfr.shape == (meta["n_dcfr"],)
        assert fp.amp.shape == (meta["n_usable_subcarriers"],)
    assert rmap.meta == meta


def test_build_ignores_other_devices(calibration):
    _, truth, meta, windows = calibration
    ambient_mac = next(
        d["mac"] for d in truth["trials"][0]["devices"] if d["role"] == "ambient"
    )
    relabelled = [dict(w, mac=ambient_mac) for w in windows]
    assert build_radio_map(relabelled, meta, truth).points == {}


def test_closer_anchor_is_stronger_in_the_map(calibration):
    _, truth, meta, windows = calibration
    r01 = build_radio_map(windows, meta, truth).points["R01"]  # next to A1
    assert r01.anchors["A1"].rssi > r01.anchors["A3"].rssi


def test_radio_map_round_trips_through_disk(calibration, tmp_path):
    _, truth, meta, windows = calibration
    rmap = build_radio_map(windows, meta, truth)
    path = tmp_path / "radio_map.json"
    rmap.save(path)
    loaded = RadioMap.load(path)
    assert loaded.meta == rmap.meta
    assert loaded.anchor_ids == rmap.anchor_ids
    assert list(loaded.points) == list(rmap.points)
    for rp, point in rmap.points.items():
        other = loaded.points[rp]
        assert (other.x, other.y, other.n_windows) == (point.x, point.y, point.n_windows)
        for anchor, fp in point.anchors.items():
            assert other.anchors[anchor].rssi == pytest.approx(fp.rssi)
            np.testing.assert_allclose(other.anchors[anchor].dcfr, fp.dcfr)
            np.testing.assert_allclose(other.anchors[anchor].amp, fp.amp)
