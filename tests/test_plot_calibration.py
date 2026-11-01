"""Calibration-session figures (plot_calibration): the grid the heatmaps draw."""

from __future__ import annotations

import math

from gateway.plot_calibration import grid_values


def test_grid_values_place_each_point_on_the_lattice_and_leave_gaps_empty():
    points = {"p1": {"x": 1.2, "y": 6.0}, "p2": {"x": 0.0, "y": 0.0}}
    xs, ys, grid = grid_values(points, {"p1": -70.0, "p2": None}, width_m=2.4,
                               height_m=6.0, step_m=1.2)
    assert xs == [0.0, 1.2, 2.4] and ys[0] == 0.0 and ys[-1] == 6.0
    assert grid[-1][1] == -70.0                 # row y = 6.0, column x = 1.2
    assert math.isnan(grid[0][0])               # value None -> no data
    assert math.isnan(grid[-1][0])              # no point there (an Anchor corner)
