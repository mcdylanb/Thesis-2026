"""Evaluation harness: metrics, per-Trial evaluation, end-to-end baseline (#26)."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from gateway.evaluate import evaluate, metrics, run_baseline
from gateway.sim import load_layout, load_physics, reference_grid, simulate_session

LAYOUTS = Path(__file__).resolve().parents[1] / "layouts"
DEFAULT_LAYOUT = LAYOUTS / "techhub_default.yaml"


def test_metrics_match_hand_computed_values():
    m = metrics(
        errors=[0.0, 3.0, 4.0],
        zone_hits=[True, False, True],
        n_windows=4,
        latencies_s=[0.001, 0.002, 0.003],
    )
    assert m["n_windows"] == 4
    assert m["n_estimates"] == 3
    assert m["availability"] == pytest.approx(0.75)
    assert m["mae_m"] == pytest.approx(7 / 3)
    assert m["rmse_m"] == pytest.approx(np.sqrt(25 / 3))
    assert m["median_m"] == pytest.approx(3.0)
    assert m["p90_m"] == pytest.approx(3.8)
    assert m["zone_accuracy"] == pytest.approx(2 / 3)
    assert m["latency_ms_mean"] == pytest.approx(2.0)
    assert m["latency_ms_p95"] == pytest.approx(2.9)


def test_metrics_without_estimates():
    m = metrics(errors=[], zone_hits=[], n_windows=5, latencies_s=[])
    assert m["availability"] == 0.0
    assert m["mae_m"] is None and m["zone_accuracy"] is None


class FixedLocalizer:
    name = "fixed"

    def __init__(self, xy):
        self.xy = xy

    def estimate(self, window):
        return self.xy if window["sufficient"] else None


def _trial(tid, x, y, t0, mac="aa"):
    return {
        "id": tid, "t_start": t0, "t_end": t0 + 3.0,
        "devices": [
            {"name": "beacon", "role": "beacon", "mac": mac, "x": x, "y": y},
            {"name": "plug", "role": "ambient", "mac": "bb", "x": 6.5, "y": 4.5},
        ],
    }


def _window(t, mac="aa", sufficient=True):
    return {"t_start": t, "t_end": t + 1.0, "mac": mac, "sufficient": sufficient,
            "anchors": {}}


def test_evaluate_scores_each_trial_against_ground_truth():
    layout = load_layout(DEFAULT_LAYOUT)
    truth = {"trials": [_trial("P1", 1.0, 1.0, 100.0), _trial("P2", 4.0, 1.0, 200.0)]}
    windows = [
        _window(100.0), _window(101.0), _window(102.0, sufficient=False),
        _window(101.0, mac="bb"),                    # ambient: ignored
        _window(200.0), _window(201.0),
    ]
    result = evaluate(FixedLocalizer((1.0, 4.0)), windows, truth, layout)

    p1, p2 = result["trials"]
    assert p1["id"] == "P1" and p1["n_windows"] == 3 and p1["n_estimates"] == 2
    assert p1["median_m"] == pytest.approx(3.0)
    assert p1["zone_accuracy"] == 0.0                # (1, 4) is Z4, truth Z1
    assert p2["median_m"] == pytest.approx(np.hypot(3.0, 3.0))
    overall = result["overall"]
    assert overall["n_windows"] == 5
    assert overall["n_estimates"] == 4
    assert overall["availability"] == pytest.approx(0.8)


def test_noiseless_baseline_median_error_below_grid_spacing(tmp_path):
    layout = load_layout(DEFAULT_LAYOUT)
    physics = load_physics(layout, LAYOUTS / "noiseless.json")
    sim = tmp_path / "sim"
    t = 1_000_000.0
    simulate_session(layout, sim, "calibration", dwell_s=3.0, seed=1,
                     physics=physics, t_start=t)
    simulate_session(layout, sim, "test", dwell_s=3.0, seed=2, physics=physics,
                     t_start=t + 10_000.0)

    result = run_baseline(sim, layout, tmp_path / "eval")

    assert result["overall"]["median_m"] < layout.grid_spacing_m
    assert result["overall"]["availability"] > 0.9
    on_disk = json.loads((tmp_path / "eval" / "baseline.json").read_text())
    assert on_disk["overall"] == result["overall"]
    assert (tmp_path / "eval" / "radio_map.json").exists()
