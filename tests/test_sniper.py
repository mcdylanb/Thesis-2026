"""Sniper particle filter, fallback rule and the proposed pipeline
(ADR-0002, #28)."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("torch")

from gateway.evaluate import evaluate, preprocess_session  # noqa: E402
from gateway.radiomap import AnchorFingerprint, RadioMap, ReferencePoint  # noqa: E402
from gateway.scout import Mixture, MdnScout  # noqa: E402
from gateway.sim import load_layout, simulate_session  # noqa: E402
from gateway.trials import windows_by_trial  # noqa: E402
from gateway.sniper import (  # noqa: E402
    FALLBACK, SNIPER, ParticleFilter, ProposedLocalizer, SniperConfig,
    run_proposed, sniper_ready, systematic_resample,
)

DEFAULT_LAYOUT = Path(__file__).resolve().parents[1] / "layouts" / "techhub_default.yaml"
ANCHORS = ["A1", "A2", "A3", "A4"]
ROOM = (4.0, 3.0)
N_DCFR = 50


def _toy_map(seed=0, missing=()):
    """4 x 3 Reference points 1 m apart, a random D-CFR per (point, Anchor);
    `missing` lists (point, Anchor) pairs stored as None."""
    rng = np.random.default_rng(seed)
    rmap = RadioMap(anchor_ids=ANCHORS)
    for i, (x, y) in enumerate((x, y) for y in (0.5, 1.5, 2.5) for x in (0.5, 1.5, 2.5, 3.5)):
        rp = f"R{i + 1:02d}"
        rmap.points[rp] = ReferencePoint(x=x, y=y, n_windows=10, anchors={
            a: None if (rp, a) in missing else AnchorFingerprint(
                rssi=-60.0, dcfr=rng.normal(size=N_DCFR), amp=np.ones(N_DCFR + 1))
            for a in ANCHORS
        })
    return rmap


def _stored(rmap, rp):
    return {a: fp.dcfr for a, fp in rmap.points[rp].anchors.items() if fp is not None}


def test_pf_converges_to_the_reference_point_whose_dcfr_it_sees():
    rmap = _toy_map()
    pf = ParticleFilter(rmap, SniperConfig(seed=1))
    room = (0.0, 0.0) + ROOM
    for rp in ("R06", "R11"):  # interior (1.5, 1.5) and (2.5, 2.5)
        pf.reset()
        live = _stored(rmap, rp)
        for _ in range(10):
            x, y = pf.step(room, live)
        p = rmap.points[rp]
        assert np.hypot(x - p.x, y - p.y) < 0.25


def test_pf_particles_stay_inside_the_scout_box():
    rmap = _toy_map()
    pf = ParticleFilter(rmap, SniperConfig(seed=2, jitter_m=1.0))
    box = (1.0, 1.0, 2.0, 2.0)
    for _ in range(5):
        x, y = pf.step(box, _stored(rmap, "R06"))
        assert 1.0 <= x <= 2.0 and 1.0 <= y <= 2.0
        assert np.all((pf.particles >= 1.0) & (pf.particles <= 2.0))


def test_weights_are_unaffected_by_a_missing_anchor():
    """An Anchor missing from the live window, or from a particle's stored
    Reference point, contributes a factor of 1 — no penalty, no veto."""
    rmap = _toy_map()
    pf = ParticleFilter(rmap)
    particles = np.random.default_rng(0).uniform((0, 0), ROOM, size=(200, 2))
    live = _stored(rmap, "R06")
    three = {a: live[a] for a in ("A1", "A2", "A3")}
    per_anchor = sum(pf.log_weights(particles, {a: d}) for a, d in three.items())
    np.testing.assert_allclose(pf.log_weights(particles, three), per_anchor)

    # R06 lacks a stored A4: its particles score on A1..A3 alone, whether
    # or not the live window has A4.
    holed = ParticleFilter(_toy_map(missing={("R06", "A4")}))
    at_r06 = np.array([[1.5, 1.5]])
    np.testing.assert_allclose(holed.log_weights(at_r06, live),
                               holed.log_weights(at_r06, three))
    assert holed.log_weights(at_r06, live)[0] == pytest.approx(3 / SniperConfig.sigma)


def test_systematic_resample_keeps_the_weight_proportions():
    w = np.array([0.5, 0.25, 0.25, 0.0])
    idx = systematic_resample(w, np.random.default_rng(0))
    assert np.bincount(idx, minlength=4).tolist() == [2, 1, 1, 0]


# --- fallback rule --------------------------------------------------------

class _StubScout:
    """A Scout that always returns one fixed mixture."""
    room = ROOM
    mixture = Mixture(weights=np.array([0.2, 0.7, 0.1]),
                      means=np.array([[1.0, 1.0], [3.0, 2.0], [2.0, 0.5]]),
                      sds=np.full((3, 2), 0.3))

    def predict(self, window):
        return self.mixture if window["sufficient"] else None


def _obs(dcfr, csi_n=20, stability=0.8, above_floor=True):
    return {"rssi": -60.0, "csi_n": csi_n, "stability": stability,
            "above_floor": above_floor, "dcfr": list(dcfr)}


def _ready_window(rmap, rp="R06"):
    return {"sufficient": True,
            "anchors": {a: _obs(d) for a, d in _stored(rmap, rp).items()}}


@pytest.mark.parametrize("broken", [
    {"csi_n": 2},             # < 3 valid CSI Records
    {"stability": 0.59},      # stability < 0.6
    {"stability": None},      # stability undefined
    {"above_floor": False},   # RSSI at or below the floor
])
def test_each_fallback_condition_alone_makes_an_anchor_not_ready(broken):
    assert sniper_ready(_obs(np.ones(3)), SniperConfig())
    assert not sniper_ready(_obs(np.ones(3), **broken), SniperConfig())


@pytest.mark.parametrize("broken", [
    {"csi_n": 2}, {"stability": 0.59}, {"above_floor": False},
])
def test_each_condition_triggers_fallback_with_the_scout_estimate(broken):
    rmap = _toy_map()
    localizer = ProposedLocalizer(_StubScout(), rmap)
    window = _ready_window(rmap)
    assert localizer.locate(window)["mode"] == SNIPER

    # One failing Anchor is simply not counted: 3 ready still runs the Sniper.
    window["anchors"]["A1"].update(broken)
    assert localizer.locate(window)["mode"] == SNIPER

    # Two failing leave 2 < min_anchors = 3: fallback, at the Scout's estimate.
    window["anchors"]["A2"].update(broken)
    loc = localizer.locate(window)
    assert loc["mode"] == FALLBACK
    assert (loc["x"], loc["y"]) == _StubScout.mixture.mode_mean(ROOM) == (3.0, 2.0)
    assert loc["bbox"] is not None


def test_a_missing_anchor_does_not_stop_the_sniper():
    rmap = _toy_map()
    window = _ready_window(rmap)
    window["anchors"]["A4"] = None
    assert ProposedLocalizer(_StubScout(), rmap).locate(window)["mode"] == SNIPER


def test_insufficient_window_has_no_estimate():
    rmap = _toy_map()
    window = dict(_ready_window(rmap), sufficient=False)
    assert ProposedLocalizer(_StubScout(), rmap).locate(window) is None


# --- end to end on the simulator -----------------------------------------

def test_proposed_pipeline_and_forced_degradation_on_the_simulator(tmp_path):
    """#28 acceptance: baseline, Scout and proposed in one results file with
    fallback rate and latency; forcing low RSSI in the simulator flips every
    window to fallback at the Scout's estimate. Run at min_stability 0, as
    `make eval` does on simulated data (see gateway.sniper)."""
    layout = load_layout(DEFAULT_LAYOUT)
    sim = tmp_path / "sim"
    t = 1_000_000.0
    simulate_session(layout, sim, "calibration", dwell_s=5.0, seed=1, t_start=t)
    simulate_session(layout, sim, "test", dwell_s=10.0, seed=2, t_start=t + 10_000.0)
    config = SniperConfig(min_stability=0.0)

    result = run_proposed(sim, layout, tmp_path / "eval", config)

    assert set(result) == {"baseline", "scout", "proposed"}
    proposed = result["proposed"]["overall"]
    assert proposed["availability"] > 0.9
    assert proposed["fallback_rate"] < 0.2
    assert proposed["latency_ms_mean"] > 0 and result["baseline"]["overall"]["latency_ms_mean"] > 0
    assert proposed["mae_m"] < result["baseline"]["overall"]["mae_m"]
    assert result["baseline"]["overall"]["fallback_rate"] is None
    on_disk = json.loads((tmp_path / "eval" / "proposed.json").read_text())
    assert on_disk["proposed"]["overall"] == proposed

    # Same Radio map and Scout; the target transmits 25 dB weaker, so its
    # RSSI sits below the -80 dBm floor at the Anchors but above sensitivity.
    weak = replace(layout, devices={**layout.devices, "beacon": replace(
        layout.devices["beacon"], tx_offset_db=-25.0)})
    simulate_session(weak, tmp_path / "weak", "test", dwell_s=10.0, seed=2,
                     positions=[("P6", 4.0, 3.0)], t_start=t + 20_000.0)
    _, windows, truth = preprocess_session(tmp_path / "weak" / "test",
                                           tmp_path / "weak_windows.jsonl")
    scout = MdnScout.load(tmp_path / "eval" / "scout.pt")
    localizer = ProposedLocalizer(scout, RadioMap.load(tmp_path / "eval" / "radio_map.json"),
                                  config)
    degraded = evaluate(localizer, windows, truth, layout)["overall"]
    assert degraded["n_estimates"] > 0
    assert degraded["fallback_rate"] == 1.0
    for w in windows_by_trial(windows, truth)["P6"]:
        loc = localizer.locate(w)
        if loc is not None:
            assert (loc["x"], loc["y"]) == scout.estimate(w)
