"""Layout search: path-loss fit, coverage and Anchor placement (#49)."""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest
import yaml

from gateway.layout_search import (
    anchor_range_m,
    coverage,
    distance_curve,
    fit_path_loss,
    largest_area,
    main,
    search_layout,
)
from gateway.sim import load_layout

FIXTURE_LAYOUT = Path(__file__).parent / "fixtures" / "placeholder_8x6_layout.yaml"

ANCHORS = {"A1": (0.0, 0.0), "A2": (10.0, 0.0)}


def _cell(rssi, status="heard"):
    return {"status": status, "median_rssi": rssi,
            "windows_heard": 0 if rssi is None else 100}


def _report(cells):
    """A calibration report holding the given {(x, y): {anchor: cell}}."""
    return {"points": {f"p{i}": {"x": x, "y": y, "anchors": anchors}
                       for i, ((x, y), anchors) in enumerate(cells.items(), 1)}}


# --- path-loss fit ----------------------------------------------------------


def test_fit_recovers_a_known_log_distance_model():
    # -60 dBm at 1 m, exponent 2.5: -60, -67.53, -75.05, -82.58 dBm at 1, 2, 4, 8 m.
    report = _report({
        (1.0, 0.0): {"A1": _cell(-60.0)},
        (2.0, 0.0): {"A1": _cell(-67.526), "A2": _cell(-82.577)},  # 8 m from A2
        (4.0, 0.0): {"A1": _cell(-75.051)},
    })
    fit = fit_path_loss(report, ANCHORS)
    assert fit["rssi_at_1m_dbm"] == pytest.approx(-60.0, abs=0.01)
    assert fit["path_loss_exponent"] == pytest.approx(2.5, abs=0.01)
    assert fit["rssi_shadowing_db"] == pytest.approx(0.0, abs=0.01)
    assert fit["n_pairs"] == 4


def test_fit_ignores_faulty_and_unheard_pairs():
    report = _report({
        (1.0, 0.0): {"A1": _cell(-60.0), "A2": _cell(-20.0, status="fault")},
        (2.0, 0.0): {"A1": _cell(-67.526), "A2": _cell(None, status="out_of_range")},
        (4.0, 0.0): {"A1": _cell(-75.051)},
    })
    fit = fit_path_loss(report, ANCHORS)
    assert fit["n_pairs"] == 3
    assert fit["path_loss_exponent"] == pytest.approx(2.5, abs=0.01)


def test_fit_reports_the_spread_around_the_line_as_shadowing():
    # Residuals +2 and -2 dB around -60 - 25 log10(d): sd 2 dB.
    report = _report({
        (1.0, 0.0): {"A1": _cell(-58.0)},
        (1.0, 1.0): {"A1": _cell(-60.0 - 25 * math.log10(math.sqrt(2)) - 2.0)},
        (4.0, 0.0): {"A1": _cell(-75.051 + 2.0)},
        (4.0, 1.0): {"A1": _cell(-60.0 - 25 * math.log10(math.sqrt(17)) - 2.0)},
    })
    fit = fit_path_loss(report, ANCHORS)
    assert fit["rssi_shadowing_db"] == pytest.approx(2.0, abs=0.3)


def test_distance_curve_counts_unheard_pairs_as_below_the_floor():
    report = _report({
        (1.0, 0.0): {"A1": _cell(-70.0), "A2": _cell(None, status="out_of_range")},
        (3.0, 0.0): {"A1": _cell(-85.0), "A2": _cell(-20.0, status="fault")},
        (1.5, 0.0): {"A1": _cell(-79.0)},
    })
    rows = distance_curve(report, ANCHORS, floor_dbm=-80.0, edges_m=(0.0, 2.0, 4.0, 10.0))
    assert [(r["from_m"], r["to_m"], r["n"], r["above"]) for r in rows] == [
        (0.0, 2.0, 2, 2), (2.0, 4.0, 1, 0), (4.0, 10.0, 1, 0)]


def test_distance_curve_gives_the_model_share_next_to_the_observed_one():
    # A pair exactly at the range has a 50 % chance of clearing the floor;
    # one a shadowing sd above it about 84 %.
    fit = {"rssi_at_1m_dbm": -60.0, "path_loss_exponent": 2.0, "rssi_shadowing_db": 4.0}
    report = _report({
        (10.0, 0.0): {"A1": _cell(-85.0)},                        # mean -80 dBm
        (10.0 ** (16 / 20), 0.0): {"A1": _cell(-70.0)},           # mean -76 dBm
    })
    rows = distance_curve(report, ANCHORS, floor_dbm=-80.0, edges_m=(0.0, 8.0, 20.0), fit=fit)
    assert rows[0]["model_share"] == pytest.approx(0.841, abs=0.001)
    assert rows[1]["model_share"] == pytest.approx(0.5, abs=0.001)


# --- coverage ---------------------------------------------------------------


def test_range_is_where_the_mean_rssi_meets_the_floor():
    # -60 dBm at 1 m, exponent 2: -80 dBm at 10 m, -77 dBm at 10^(17/20) m.
    physics = {"rssi_at_1m_dbm": -60.0, "path_loss_exponent": 2.0}
    assert anchor_range_m(physics, -80.0) == pytest.approx(10.0)
    assert anchor_range_m(physics, -77.0) == pytest.approx(7.079, abs=0.001)


def test_coverage_is_the_share_of_spots_with_enough_anchors_in_range():
    # Spots x = 0..4 on a line; Anchors at 0, 1 and 4, range 2.5 m.
    # Anchors in range per spot: 2, 2, 3, 2, 1 -> only x = 2 passes.
    share = coverage([(0.0, 0.0), (1.0, 0.0), (4.0, 0.0)], area=(0.0, 0.0, 4.0, 0.0),
                     range_m=2.5, min_anchors=3, step_m=1.0)
    assert share == pytest.approx(0.2)


# --- layout search ----------------------------------------------------------


def test_search_finds_the_only_layout_that_covers_a_corridor():
    # A 4 m corridor, range 2.5 m: both ends need 3 Anchors within 2.5 m, so
    # all three must sit in x = 1.5..2.5 (one spot each on a 0.5 m lattice).
    best = search_layout(area=(0.0, 0.0, 4.0, 0.0), n_anchors=3, range_m=2.5,
                         candidate_step_m=0.5, spot_step_m=0.5, min_spacing_m=0.0)
    assert best["coverage"] == 1.0
    assert sorted(x for x, _ in best["anchors"]) == [1.5, 2.0, 2.5]


def test_search_never_does_worse_than_the_corners():
    room = (0.0, 0.0, 12.0, 6.0)
    corners = [(0.0, 0.0), (12.0, 0.0), (12.0, 6.0), (0.0, 6.0)]
    best = search_layout(area=room, n_anchors=4, range_m=6.0)
    assert best["coverage"] >= coverage(corners, room, range_m=6.0)
    assert best["coverage"] == pytest.approx(coverage(best["anchors"], room, range_m=6.0))


def test_search_keeps_anchors_apart():
    # Unconstrained, three Anchors bunch up in the middle of a long room.
    best = search_layout(area=(0.0, 0.0, 12.0, 6.0), n_anchors=4, range_m=3.0,
                         min_spacing_m=2.0)
    xy = best["anchors"]
    assert min(math.dist(a, b) for i, a in enumerate(xy) for b in xy[i + 1:]) >= 2.0


def test_walls_only_search_places_every_anchor_on_a_wall():
    best = search_layout(area=(0.0, 0.0, 12.0, 6.0), n_anchors=6, range_m=4.0,
                         walls_only=True)
    assert all(x in (0.0, 12.0) or y in (0.0, 6.0) for x, y in best["anchors"])


def test_walls_only_cannot_reach_a_centre_beyond_range():
    # The centre line of a 6 m wide room is 3 m from both long walls.
    best = search_layout(area=(0.0, 0.0, 6.0, 6.0), n_anchors=8, range_m=2.9,
                         walls_only=True)
    assert best["coverage"] < 1.0


def test_largest_area_is_covered_and_beats_four_corners():
    # Four corners of a square cover it while the far corners of an edge
    # midpoint (1.118 x side) are in range: up to 3.58 m for a 4 m range.
    w, h, best = largest_area(n_anchors=4, range_m=4.0, max_w=12.0, max_h=6.0, aspect=1.0)
    assert w == h
    assert w >= 3.3
    assert coverage(best["anchors"], (0.0, 0.0, w, h), range_m=4.0) == 1.0


# --- command ----------------------------------------------------------------


def test_command_writes_the_summary_and_a_loadable_candidate_layout(tmp_path):
    layout = load_layout(FIXTURE_LAYOUT)
    cells = {}
    for i, (x, y) in enumerate((x, y) for x in (1.0, 4.0, 7.0) for y in (1.0, 3.0, 5.0)):
        cells[(x, y)] = {}
        for a, (ax, ay) in layout.anchors.items():
            d = max(math.hypot(x - ax, y - ay), 0.1)
            cells[(x, y)][a] = _cell(-66.0 - 23.0 * math.log10(d) + (2.0 if i % 2 else -2.0))
    report_path = tmp_path / "report.json"
    report_path.write_text(json.dumps(_report(cells)))
    out = tmp_path / "out"

    assert main(["--report", str(report_path), "--layout", str(FIXTURE_LAYOUT),
                 "--out", str(out), "--max-anchors", "5"]) == 0

    summary = (out / "summary.md").read_text()
    assert "Distance curve" in summary and "Whole room" in summary
    data = json.loads((out / "layout_search.json").read_text())
    assert data["fit"]["path_loss_exponent"] == pytest.approx(2.3, abs=0.1)
    candidate = load_layout(out / "candidate_layout.yaml")
    assert candidate.physics["path_loss_exponent"] == pytest.approx(2.3, abs=0.1)
    assert candidate.anchors == {f"A{i}": tuple(xy) for i, xy in
                                 enumerate(data["candidate"]["anchors"], 1)}
    assert yaml.safe_load((out / "candidate_layout.yaml").read_text())["test_positions"]
    # Any 3 of the fixture's 4 inset corners include a diagonal pair 9.2 m
    # apart, more than twice the ~4.1 m range: no spot has 3 in range.
    current = data["current"]
    assert current["model_coverage"] == 0.0
    assert current["observed_points"] <= current["n_points"] == 9
