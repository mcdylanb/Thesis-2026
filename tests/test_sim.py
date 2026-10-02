"""Spatial simulator: layout, physics, schedules and Capture output (#25)."""

from __future__ import annotations

import itertools
import json
from pathlib import Path

import numpy as np
import pytest

from gateway.csi import dcfr, normalize, remap_hw64_to_usable
from gateway.parser import load_session
from gateway.preprocess import PreprocessConfig, run
from gateway.sim import (
    Device,
    check_coverage,
    csi_fingerprint,
    load_layout,
    load_physics,
    reference_grid,
    rssi_mean,
    simulate_session,
    transmit_times,
    zone_of,
)

DEFAULT_LAYOUT = Path(__file__).resolve().parents[1] / "layouts" / "techhub_default.yaml"


@pytest.fixture(scope="module")
def layout():
    return load_layout(DEFAULT_LAYOUT)


def _dcfr(hw64):
    return dcfr(normalize(remap_hw64_to_usable(hw64)))


# --- layout ---------------------------------------------------------------


def test_default_layout_loads(layout):
    assert set(layout.anchors) == {"A1", "A2", "A3", "A4"}
    assert set(layout.test_positions) == {f"P{i}" for i in range(1, 11)}
    grid = reference_grid(layout)
    assert len(grid) == 48
    assert grid[0] == ("R01", 0.5, 0.5)


def test_test_positions_are_held_out_of_grid(layout):
    grid = reference_grid(layout)
    for x, y in layout.test_positions.values():
        nearest = min(np.hypot(x - gx, y - gy) for _, gx, gy in grid)
        assert nearest >= 0.3


def test_test_position_on_grid_is_rejected(tmp_path):
    text = DEFAULT_LAYOUT.read_text().replace("P1: [1.0, 1.0]", "P1: [1.5, 1.5]")
    path = tmp_path / "bad.yaml"
    path.write_text(text)
    with pytest.raises(ValueError, match="P1"):
        load_layout(path)


# --- RSSI -----------------------------------------------------------------


def test_rssi_decreases_with_distance(layout):
    physics = dict(layout.physics, rssi_shadowing_db=0.0)
    beacon = layout.devices["beacon"]
    distances = [0.5, 1.0, 2.0, 4.0, 8.0]
    values = [
        rssi_mean(layout, physics, beacon, "A1", (0.3 + d, 0.3)) for d in distances
    ]
    assert all(a > b for a, b in zip(values, values[1:]))


# --- CSI ------------------------------------------------------------------


def test_neighbouring_grid_points_correlate_more_than_distant(layout):
    beacon = layout.devices["beacon"]
    grid = reference_grid(layout)
    near, far = [], []
    for anchor in layout.anchors:
        fps = {
            rp: _dcfr(csi_fingerprint(layout, layout.physics, beacon, anchor, (x, y)))
            for rp, x, y in grid
        }
        for (a, ax, ay), (b, bx, by) in itertools.combinations(grid, 2):
            d = np.hypot(ax - bx, ay - by)
            rho = np.corrcoef(fps[a], fps[b])[0, 1]
            if d <= 1.0:
                near.append(rho)
            elif d >= 4.0:
                far.append(rho)
    assert np.mean(near) > np.mean(far) + 0.1


def test_device_nuisance_changes_fingerprint_at_fixed_spot(layout):
    spot = layout.test_positions["P6"]
    beacon, phone = layout.devices["beacon"], layout.devices["phone"]
    fp_b = csi_fingerprint(layout, layout.physics, beacon, "A1", spot)
    fp_p = csi_fingerprint(layout, layout.physics, phone, "A1", spot)
    assert not np.allclose(fp_b, fp_p, atol=0.5)
    assert rssi_mean(layout, layout.physics, beacon, "A1", spot) != rssi_mean(
        layout, layout.physics, phone, "A1", spot
    )


def test_fingerprint_has_hardware_quirks(layout):
    fp = csi_fingerprint(
        layout, layout.physics, layout.devices["beacon"], "A2", (4.0, 3.0)
    )
    assert fp.shape == (64,)
    assert fp[0] == 0                              # DC
    assert np.all(fp[27:38] == 0)                  # guard band
    usable = remap_hw64_to_usable(fp)
    assert fp[1] < 0.3 * np.median(usable)         # corrupt subcarrier +1
    assert np.all(usable > 0)


# --- transmit schedules ---------------------------------------------------


def test_steady_schedule_has_fixed_rate():
    beacon = Device(name="b", role="beacon", mac="aa:bb:cc:dd:ee:ff", rate_hz=20.0)
    times = transmit_times(beacon, 10.0, np.random.default_rng(0))
    assert len(times) == 200
    assert np.all(np.diff(times) > 0)
    assert np.median(np.diff(times)) == pytest.approx(0.05, abs=0.005)


def test_sporadic_schedule_reproduces_gap_statistics():
    plug = Device(name="p", role="ambient", mac="aa:bb:cc:dd:ee:01",
                  mode="sporadic", rate_hz=0.1, burst_mean=3.0)
    duration = 200_000.0
    times = transmit_times(plug, duration, np.random.default_rng(1))
    assert len(times) / duration == pytest.approx(0.1, rel=0.1)
    gaps = np.diff(times)
    burst_gaps = gaps[gaps > 1.0]                   # between bursts
    assert np.mean(burst_gaps) == pytest.approx(3.0 / 0.1, rel=0.1)
    # Bursty: most gaps are the short intra-burst spacing.
    assert np.mean(gaps < 1.0) == pytest.approx(1 - 1 / 3.0, abs=0.05)
    assert np.all((times >= 0) & (times < duration))


# --- physics overrides and placement --------------------------------------


def test_noise_json_overrides_physics(layout, tmp_path):
    noise = tmp_path / "noise.json"
    noise.write_text(json.dumps({"rssi_jitter_db": 5.5, "unrelated": 1}))
    physics = load_physics(layout, noise)
    assert physics["rssi_jitter_db"] == 5.5
    assert "unrelated" not in physics
    assert physics["path_loss_exponent"] == layout.physics["path_loss_exponent"]


def test_default_layout_covers_every_test_position(layout):
    assert check_coverage(layout, layout.physics, min_anchors=3) == []


def test_coverage_uses_the_named_target(layout):
    physics = dict(layout.physics, rssi_at_1m_dbm=-53.5)  # Beacon weakest -78 dBm, phone -82
    assert check_coverage(layout, physics, min_anchors=4) == []
    assert check_coverage(layout, physics, min_anchors=4, target="phone")


def test_coverage_flags_far_position(layout):
    physics = dict(layout.physics, rssi_at_1m_dbm=-75.0)
    assert check_coverage(layout, physics, min_anchors=3)


# --- sessions -------------------------------------------------------------


@pytest.fixture(scope="module")
def small_calibration(layout, tmp_path_factory):
    out = tmp_path_factory.mktemp("sim")
    truth = simulate_session(
        layout, out, "calibration", dwell_s=8.0, seed=3,
        positions=reference_grid(layout)[:3],
    )
    return out / "calibration", truth


def test_session_writes_trials_and_ground_truth(small_calibration, layout):
    session_dir, truth = small_calibration
    on_disk = json.loads((session_dir / "ground_truth.json").read_text())
    assert on_disk == truth
    assert [t["id"] for t in truth["trials"]] == ["R01", "R02", "R03"]
    trial = truth["trials"][0]
    assert sorted(p.name for p in (session_dir / "R01").glob("*.csv")) == [
        f"{a}_sim.csv" for a in ("A1", "A2", "A3", "A4")
    ]
    beacon = next(d for d in trial["devices"] if d["role"] == "beacon")
    assert (beacon["x"], beacon["y"]) == (0.5, 0.5)
    assert beacon["mac"] == layout.devices["beacon"].mac
    ambient = [d for d in trial["devices"] if d["role"] == "ambient"]
    assert {d["name"] for d in ambient} == {"plug", "camera"}
    # Trials do not overlap in host time.
    spans = [(t["t_start"], t["t_end"]) for t in truth["trials"]]
    assert all(a[1] <= b[0] for a, b in zip(spans, spans[1:]))


def test_output_parses_without_malformed_records(small_calibration):
    session_dir, _ = small_calibration
    csi, stat, stats = load_session([session_dir / "R02"])
    assert stats.malformed == 0
    assert len(csi) > 0
    assert len(stat) == 4


def test_malformed_fraction_is_injected(layout, tmp_path):
    truth = simulate_session(
        layout, tmp_path, "calibration", dwell_s=5.0, seed=4,
        positions=reference_grid(layout)[:1], malformed_frac=0.1,
    )
    _, _, stats = load_session([tmp_path / "calibration" / "R01"])
    assert stats.malformed == truth["trials"][0]["malformed"] > 0


def test_dropout_silences_anchor(layout, tmp_path):
    simulate_session(
        layout, tmp_path, "calibration", dwell_s=6.0, seed=5,
        positions=reference_grid(layout)[:1], dropouts=[("A3", 0.0, 6.0)],
    )
    csi, _, _ = load_session([tmp_path / "calibration" / "R01"])
    assert csi and not [r for r in csi if r.anchor == "A3"]


def test_beacon_windows_are_sufficient(small_calibration, layout, tmp_path):
    session_dir, _ = small_calibration
    beacon_mac = layout.devices["beacon"].mac
    for trial in ("R01", "R02", "R03"):
        summary = run(PreprocessConfig(
            inputs=[session_dir / trial], out=tmp_path / f"{trial}.jsonl",
            mac_filter=[beacon_mac],
        ))
        assert summary["windows"]["usable_window_rate"] >= 0.9


def test_test_session_uses_target_device(layout, tmp_path):
    truth = simulate_session(
        layout, tmp_path, "test", dwell_s=4.0, seed=6, target="phone",
        positions=[("P6", *layout.test_positions["P6"])],
    )
    trial = truth["trials"][0]
    target = next(d for d in trial["devices"] if d["role"] != "ambient")
    assert target["name"] == "phone"
    assert (target["x"], target["y"]) == layout.test_positions["P6"]
    assert truth["session"] == "test"


# --- zones ----------------------------------------------------------------


def test_zone_of_maps_every_test_position(layout):
    assert set(layout.zones) == {f"Z{i}" for i in range(1, 7)}
    assert zone_of(layout, 0.0, 0.0) == "Z1"
    assert zone_of(layout, 8.0, 6.0) == "Z6"            # far corner belongs too
    for x, y in layout.test_positions.values():
        assert zone_of(layout, x, y) in layout.zones


def test_zones_that_leave_a_gap_are_rejected(tmp_path):
    text = DEFAULT_LAYOUT.read_text().replace("Z6: [5.3, 3.5, 8.0, 6.0]", "Z6: [5.3, 3.5, 7.0, 6.0]")
    path = tmp_path / "gap.yaml"
    path.write_text(text)
    with pytest.raises(ValueError, match="zone"):
        load_layout(path)


def test_test_position_on_a_zone_edge_is_rejected(tmp_path):
    text = DEFAULT_LAYOUT.read_text().replace("P6: [4.0, 3.0]", "P6: [4.0, 3.4]")
    path = tmp_path / "edge.yaml"
    path.write_text(text)
    with pytest.raises(ValueError, match="P6.*zone edge"):
        load_layout(path)
