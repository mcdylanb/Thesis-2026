"""Anchor layout search from a real Calibration session's signal fade (#49).

    python -m gateway.layout_search --report out/techhub/report/report.json \
        --layout layouts/techhub_default.yaml --out out/techhub/layout_search

The TechHub pilot showed the Sniper needs every point within reach of 3
Anchors above the -80 dBm floor (ADR-0002, ADR-0003). This module turns the
session's per-(point, Anchor) median Beacon RSSI into a placement rule and
searches Anchor layouts against it:

- Path-loss fit: least squares of median RSSI on log10(distance) over the
  pairs that heard the Beacon (field-noted faults and unheard pairs left
  out), giving the simulator's rssi_at_1m_dbm and path_loss_exponent; the
  spread around the line is the per-spot shadowing.
- Distance curve: per distance band, the share of pairs whose median RSSI
  clears the floor (a pair that never heard the Beacon counts as below).
- Coverage: the fitted mean RSSI meets the floor at a fixed range, so a spot
  passes when >= 3 Anchors lie within that range. A margin above the floor
  (e.g. 3 dB) shortens the range to allow for the per-spot shadowing.
- Search: for a given area and Anchor count, a local search over Anchor
  positions on a lattice (walls only, or walls and inside; not only
  corners), Anchors kept >= 2 m apart; and the
  largest area of a given shape that a given count covers fully.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np
import yaml

from gateway.sim import MIN_DISTANCE_M, RSSI_FLOOR_DBM, load_layout, reference_grid

Point = Tuple[float, float]
Area = Tuple[float, float, float, float]  # x0, y0, x1, y1
SPOT_STEP_M = 0.3  # spacing of the spots a layout must cover
CANDIDATE_STEP_M = 0.6  # spacing of the spots an Anchor may be placed on
RESTARTS = 8
MIN_SPACING_M = 2.0  # closer Anchors add little geometry
EPS_M = 1e-9  # a spot exactly at the range counts as in range
MIN_ANCHORS = 3  # ADR-0002: the Sniper needs 3 Anchors above the floor
MIN_COUNT = 4
MAX_ANCHORS = 16
MARGINS_DB = (0.0, 3.0)
AREA_COUNTS = (4, 5, 6, 8)
CLASH_M = 0.5  # a Reference point this close to an Anchor has to move
FIT_KEYS = ("rssi_at_1m_dbm", "path_loss_exponent", "rssi_shadowing_db")
DISTANCE_EDGES_M = (0.0, 2.0, 4.0, 6.0, 8.0, float("inf"))


def _heard_pairs(report: dict, anchor_xy: Dict[str, Point]):
    """(distance m, median RSSI) of every (point, Anchor) pair that heard the Beacon."""
    for p in report["points"].values():
        for a, cell in p["anchors"].items():
            if cell["status"] != "heard" or cell["median_rssi"] is None or a not in anchor_xy:
                continue
            ax, ay = anchor_xy[a]
            d = max(float(np.hypot(p["x"] - ax, p["y"] - ay)), MIN_DISTANCE_M)
            yield d, float(cell["median_rssi"])


def distance_curve(
    report: dict,
    anchor_xy: Dict[str, Point],
    floor_dbm: float = RSSI_FLOOR_DBM,
    edges_m: Sequence[float] = DISTANCE_EDGES_M,
    fit: Optional[dict] = None,
) -> List[dict]:
    """Per distance band [from, to): how many (point, Anchor) pairs there are
    and how many have a median Beacon RSSI at or above the floor. A pair that
    never heard the Beacon counts as below it; faulty pairs are left out.
    Given a path-loss `fit`, each row also holds `model_share`: the share the
    fitted mean and shadowing predict for the same pairs, a check of the fit."""
    rows = [{"from_m": lo, "to_m": hi, "n": 0, "above": 0, "_p": []}
            for lo, hi in zip(edges_m, edges_m[1:])]
    for p in report["points"].values():
        for a, cell in p["anchors"].items():
            if cell["status"] == "fault" or a not in anchor_xy:
                continue
            ax, ay = anchor_xy[a]
            d = float(np.hypot(p["x"] - ax, p["y"] - ay))
            above = cell["median_rssi"] is not None and cell["median_rssi"] >= floor_dbm
            for row in rows:
                if row["from_m"] <= d < row["to_m"]:
                    row["n"] += 1
                    row["above"] += int(above)
                    if fit is not None:
                        row["_p"].append(_p_above(fit, d, floor_dbm))
    for row in rows:
        p_above = row.pop("_p")
        if fit is not None:
            row["model_share"] = float(np.mean(p_above)) if p_above else None
    return rows


def mean_rssi(fit: Dict[str, float], d: float) -> float:
    """The fitted log-distance mean RSSI at `d` metres."""
    return fit["rssi_at_1m_dbm"] - 10 * fit["path_loss_exponent"] * np.log10(
        max(d, MIN_DISTANCE_M))


def _p_above(fit: Dict[str, float], d: float, floor_dbm: float) -> float:
    """Chance a pair at `d` m clears the floor, with Gaussian shadowing."""
    z = (mean_rssi(fit, d) - floor_dbm) / fit["rssi_shadowing_db"]
    return 0.5 * (1 + math.erf(z / math.sqrt(2)))


def fit_path_loss(report: dict, anchor_xy: Dict[str, Point]) -> dict:
    """Log-distance model RSSI = P0 - 10 n log10(d) fitted to the report's
    heard pairs, with the residual sd as the per-spot shadowing."""
    pairs = list(_heard_pairs(report, anchor_xy))
    if len(pairs) < 3:
        raise ValueError(f"need >= 3 heard (point, Anchor) pairs, got {len(pairs)}")
    log_d = np.log10([d for d, _ in pairs])
    rssi = np.array([r for _, r in pairs])
    slope, p0 = np.polyfit(log_d, rssi, 1)
    residual = rssi - (p0 + slope * log_d)
    return {
        "rssi_at_1m_dbm": float(p0),
        "path_loss_exponent": float(-slope / 10),
        "rssi_shadowing_db": float(residual.std()),
        "n_pairs": len(pairs),
    }


def anchor_range_m(physics: Dict[str, float], floor_dbm: float = RSSI_FLOOR_DBM) -> float:
    """Distance at which the model's mean RSSI falls to `floor_dbm`."""
    return float(10 ** ((physics["rssi_at_1m_dbm"] - floor_dbm)
                        / (10 * physics["path_loss_exponent"])))


def spots(area: Area, step_m: float = SPOT_STEP_M) -> np.ndarray:
    """(n, 2) lattice of spots covering the rectangle (x0, y0, x1, y1), edges included."""
    x0, y0, x1, y1 = area
    xs = np.arange(x0, x1 + 1e-9, step_m)
    ys = np.arange(y0, y1 + 1e-9, step_m)
    return np.array([(x, y) for y in ys for x in xs])


def coverage(
    anchors: Sequence[Point],
    area: Area,
    range_m: float,
    min_anchors: int = 3,
    step_m: float = SPOT_STEP_M,
) -> float:
    """Share of the area's spots with >= `min_anchors` Anchors within `range_m`:
    the ADR-0003 placement rule with the fitted mean RSSI, no shadowing."""
    grid = spots(area, step_m)
    d = np.hypot(grid[:, None, 0] - np.array(anchors)[None, :, 0],
                 grid[:, None, 1] - np.array(anchors)[None, :, 1])
    return float(((d <= range_m + EPS_M).sum(axis=1) >= min_anchors).mean())


def _seed_grid(area: Area, n: int) -> List[Point]:
    """n positions on a regular cols x rows grid of cell centres, shaped like the area."""
    x0, y0, x1, y1 = area
    w, h = x1 - x0, y1 - y0
    cols = max(1, round(np.sqrt(n * w / h))) if h > 0 else n
    rows = int(np.ceil(n / cols))
    return [(x0 + (i + 0.5) * w / cols, y0 + (j + 0.5) * h / rows)
            for j in range(rows) for i in range(cols)][:n]


def _seed_perimeter(area: Area, n: int) -> List[Point]:
    """n positions evenly spaced around the walls, starting at (x0, y0)."""
    x0, y0, x1, y1 = area
    w, h = x1 - x0, y1 - y0
    out = []
    for i in range(n):
        t = i * 2 * (w + h) / n
        if t < w:
            out.append((x0 + t, y0))
        elif t < w + h:
            out.append((x1, y0 + t - w))
        elif t < 2 * w + h:
            out.append((x1 - (t - w - h), y1))
        else:
            out.append((x0, y1 - (t - 2 * w - h)))
    return out


def search_layout(
    area: Area,
    n_anchors: int,
    range_m: float,
    min_anchors: int = 3,
    walls_only: bool = False,
    min_spacing_m: float = MIN_SPACING_M,
    candidate_step_m: float = CANDIDATE_STEP_M,
    spot_step_m: float = SPOT_STEP_M,
    restarts: int = RESTARTS,
    seed: int = 0,
    starts: Sequence[Sequence[Point]] = (),
) -> dict:
    """Best placement found for `n_anchors` Anchors on a lattice over the area
    (its walls only, or walls and inside), every two Anchors at least
    `min_spacing_m` apart: Anchors bunched together pass the range rule but
    add no geometry. Local search, one Anchor moved at a time, from the
    corners, a regular grid, evenly round the walls and random starts. Ranks layouts by
    coverage, then by the worst spot's distance to its `min_anchors`-th
    nearest Anchor (smaller is more robust), which also steers the search
    while coverage is flat. `starts` adds starting layouts (e.g. the best
    layout for one Anchor fewer, so adding an Anchor never loses coverage)."""
    x0, y0, x1, y1 = area
    cands = spots(area, candidate_step_m)
    if walls_only:
        on_wall = np.isclose(cands[:, 0], x0) | np.isclose(cands[:, 0], x1) \
            | np.isclose(cands[:, 1], y0) | np.isclose(cands[:, 1], y1)
        cands = cands[on_wall]
    grid = spots(area, spot_step_m)
    dist = np.hypot(cands[:, None, 0] - grid[None, :, 0], cands[:, None, 1] - grid[None, :, 1])
    apart = np.hypot(cands[:, None, 0] - cands[None, :, 0],
                     cands[:, None, 1] - cands[None, :, 1]) >= min_spacing_m - EPS_M
    k = min(min_anchors, n_anchors)

    def key(sel):
        d = dist[sel]
        cov = float(((d <= range_m + EPS_M).sum(axis=0) >= min_anchors).mean())
        kth = float(np.partition(d, k - 1, axis=0)[k - 1].max())
        return (round(cov, 9), round(-kth, 9))

    def fits(c, others):
        return all(apart[c, o] for o in others)

    def nearest(p):
        return int(np.argmin(np.hypot(cands[:, 0] - p[0], cands[:, 1] - p[1])))

    rng = np.random.default_rng(seed)
    corners = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
    seeds = [list(p) for p in starts] \
        + [corners, _seed_grid(area, n_anchors), _seed_perimeter(area, n_anchors)] \
        + [[] for _ in range(restarts)]
    best_sel, best_key = None, None
    for wanted in seeds:
        sel: List[int] = []
        for c in [nearest(p) for p in wanted] + [int(c) for c in rng.permutation(len(cands))]:
            if len(sel) < n_anchors and c not in sel and fits(c, sel):
                sel.append(c)
        if len(sel) < n_anchors:
            continue  # no room for this many Anchors at this spacing
        current = key(sel)
        improved = True
        while improved:
            improved = False
            for i in range(n_anchors):
                others = sel[:i] + sel[i + 1:]
                for c in range(len(cands)):
                    if c in sel or not fits(c, others):
                        continue
                    trial = others[:i] + [c] + others[i:]
                    k_trial = key(trial)
                    if k_trial > current:
                        sel, current, improved = trial, k_trial, True
                        others = sel[:i] + sel[i + 1:]
        if best_key is None or current > best_key:
            best_sel, best_key = sel, current
    if best_sel is None:
        raise ValueError(f"{n_anchors} Anchors do not fit {min_spacing_m} m apart in {area}")
    anchors = sorted((round(float(cands[c][0]), 6), round(float(cands[c][1]), 6))
                     for c in best_sel)
    return {"anchors": anchors, "coverage": best_key[0], "worst_kth_m": -best_key[1]}


def largest_area(
    n_anchors: int,
    range_m: float,
    max_w: float,
    max_h: float,
    aspect: float,
    step_m: float = SPOT_STEP_M,
    **search,
) -> Tuple[float, float, dict]:
    """Largest w x h rectangle (w = aspect * h, h a multiple of `step_m`,
    within max_w x max_h) that `n_anchors` Anchors cover fully, with that
    layout. (0, 0, None) if not even the smallest one is covered."""
    hs = [round(step_m * i, 6) for i in range(1, int(max_h / step_m + 1e-9) + 1)
          if aspect * step_m * i <= max_w + 1e-9]
    found = (0.0, 0.0, None)
    lo, hi = 0, len(hs) - 1
    while lo <= hi:
        mid = (lo + hi) // 2
        h = hs[mid]
        w = round(aspect * h, 6)
        try:
            best = search_layout((0.0, 0.0, w, h), n_anchors, range_m, **search)
        except ValueError:  # too small to hold the Anchors apart: grow it
            lo = mid + 1
            continue
        if best["coverage"] == 1.0:
            found, lo = (w, h, best), mid + 1
        else:
            hi = mid - 1
    return found


# --- whole run ----------------------------------------------------------------


def whole_room(
    area: Area, range_m: float, walls_only: bool, max_anchors: int,
    min_count: int = MIN_COUNT,
) -> List[dict]:
    """Best coverage for min_count, min_count + 1, ... Anchors, up to the first
    count that covers the whole area, `max_anchors`, or the most that fit."""
    rows, prev = [], None
    for n in range(min_count, max_anchors + 1):
        starts = [prev["anchors"] + [((area[0] + area[2]) / 2, (area[1] + area[3]) / 2)]] \
            if prev else []
        try:
            best = search_layout(area, n, range_m, walls_only=walls_only, starts=starts)
        except ValueError:
            break
        rows.append({"n_anchors": n, **best})
        prev = best
        if best["coverage"] == 1.0:
            break
    return rows


def current_layout(report: dict, layout, fit: Dict[str, float],
                   floor_dbm: float = RSSI_FLOOR_DBM) -> dict:
    """The session's own Anchors: the room share the model says meets the rule
    (0 dB margin), next to the points whose medians actually did."""
    observed = sum(
        1 for p in report["points"].values()
        if sum(1 for c in p["anchors"].values()
               if c["status"] == "heard" and c["median_rssi"] is not None
               and c["median_rssi"] >= floor_dbm) >= MIN_ANCHORS)
    return {
        "anchors": sorted(layout.anchors.values()),
        "model_coverage": coverage(list(layout.anchors.values()),
                                   (0.0, 0.0, layout.width_m, layout.height_m),
                                   anchor_range_m(fit, floor_dbm)),
        "observed_points": observed, "n_points": len(report["points"]),
    }


def clashes(layout, anchors: Sequence[Point], within_m: float = CLASH_M) -> List[str]:
    """Reference points and Test positions within `within_m` of an Anchor."""
    named = [(n, (x, y)) for n, x, y in reference_grid(layout)] \
        + list(layout.test_positions.items())
    return [n for n, xy in named if any(math.dist(xy, a) < within_m for a in anchors)]


def hardest_points(
    layout, anchors: Sequence[Point], fit: Dict[str, float], k: int = 3, top: int = 5,
) -> List[dict]:
    """The layout's Reference points with the weakest k-th strongest Anchor
    under the fitted mean RSSI: the pilot points of the next capture day."""
    rows = []
    for name, x, y in reference_grid(layout):
        kth = sorted((mean_rssi(fit, math.dist((x, y), a)) for a in anchors), reverse=True)
        rows.append({"point": name, "x": x, "y": y, "kth_rssi_dbm": float(kth[k - 1])})
    return sorted(rows, key=lambda r: r["kth_rssi_dbm"])[:top]


def candidate_yaml(layout_path: Path, anchors: Sequence[Point], fit: Dict[str, float],
                   note: str) -> str:
    """The source layout with the candidate Anchors and the fitted physics."""
    raw = yaml.safe_load(Path(layout_path).read_text())
    raw["anchors"] = {f"A{i}": [x, y] for i, (x, y) in enumerate(anchors, 1)}
    raw["physics"] = {**raw.get("physics", {}),
                      **{k: round(fit[k], 3) for k in FIT_KEYS}}
    header = (f"# GENERATED by gateway.layout_search from {layout_path}: {note}.\n"
              "# Anchors and the RSSI physics (fitted to the Calibration session) are\n"
              "# replaced; everything else is copied. Do not edit; rerun instead.\n")
    return header + yaml.safe_dump(raw, sort_keys=False)


def _pct(v: Optional[float]) -> str:
    return "-" if v is None else f"{100 * v:.0f} %"


def _cov(v: float) -> str:
    """Coverage rounded down, so only full coverage reads 100 %."""
    return f"{math.floor(100 * v + 1e-9):.0f} %"


def _xy(anchors: Sequence[Point]) -> str:
    return ", ".join(f"({x:g}, {y:g})" for x, y in anchors)


def format_markdown(result: dict) -> str:
    fit, margins = result["fit"], result["margins_db"]
    lines = [
        "# Anchor layout search", "",
        f"From `{result['report']}` and `{result['layout']}`. Placement rule (ADR-0003): "
        f">= {MIN_ANCHORS} Anchors whose fitted mean Beacon RSSI is at or above the floor "
        f"({result['floor_dbm']:g} dBm) plus a margin. Anchors >= {MIN_SPACING_M:g} m apart, "
        f"on a {CANDIDATE_STEP_M:g} m lattice; coverage checked every {SPOT_STEP_M:g} m.", "",
        "## Path-loss fit", "",
        f"RSSI = {fit['rssi_at_1m_dbm']:.1f} dBm - 10 x {fit['path_loss_exponent']:.2f} "
        f"x log10(d), shadowing sd {fit['rssi_shadowing_db']:.1f} dB, {fit['n_pairs']} heard "
        "(point, Anchor) pairs. Unheard pairs are left out of the fit, so it is slightly "
        "optimistic far from an Anchor.", "",
        "| margin | floor + margin | range of one Anchor |", "|---|---|---|",
    ]
    for m in margins:
        lines.append(f"| {m:g} dB | {result['floor_dbm'] + m:g} dBm | "
                     f"{result['range_m'][str(m)]:.2f} m |")
    lines += ["", "## Distance curve", "",
              "Share of (point, Anchor) pairs whose median RSSI clears the floor; "
              "model = what the fit predicts for the same pairs.", "",
              "| distance | pairs | observed | model |", "|---|---|---|---|"]
    for r in result["distance_curve"]:
        hi = "" if math.isinf(r["to_m"]) else f"{r['to_m']:g}"
        lines.append(f"| {r['from_m']:g}-{hi} m | {r['n']} | "
                     f"{_pct(r['above'] / r['n'] if r['n'] else None)} | "
                     f"{_pct(r['model_share'])} |")
    cur = result["current"]
    w, h = result["room"]
    cols = [(m, p) for p in ("walls", "anywhere") for m in margins]
    lines += ["", f"## Whole room ({w:g} x {h:g} m)", "",
              "Share of the room meeting the rule with the best layout found per Anchor "
              "count; `walls` = Anchors on the walls only, `anywhere` = also inside the "
              "room (on stands). Stops at the first count covering 100 %.", "",
              f"Check against the session: its own Anchors at {_xy(cur['anchors'])} meet the "
              f"rule over {_cov(cur['model_coverage'])} of the room by the model; in the data, "
              f"{cur['observed_points']} of {cur['n_points']} Reference points had "
              f">= {MIN_ANCHORS} Anchors with a median at or above the floor.", "",
              "| Anchors | " + " | ".join(f"{p}, {m:g} dB" for m, p in cols) + " |",
              "|---|" + "---|" * len(cols)]
    counts = sorted({r["n_anchors"] for rows in result["whole_room"].values() for r in rows})
    for n in counts:
        cells = []
        for m, p in cols:
            row = next((r for r in result["whole_room"][f"{p}/{m:g}"] if r["n_anchors"] == n),
                       None)
            cells.append(_cov(row["coverage"]) if row else "")
        lines.append(f"| {n} | " + " | ".join(cells) + " |")
    lines += ["", "## Largest area fully covered", "",
              "Largest rectangle of the room's shape, and largest square, that up to "
              "this many Anchors cover at every spot (Anchors anywhere in it, 2 m apart). "
              "0 x 0 = none found.", "",
              "| up to | margin | room-shaped | square |", "|---|---|---|---|"]
    for r in sorted(result["largest_area"], key=lambda r: (r["n_anchors"], r["margin_db"])):
        lines.append(f"| {r['n_anchors']} | {r['margin_db']:g} dB | "
                     f"{r['room_shaped'][0]:g} x {r['room_shaped'][1]:g} m | "
                     f"{r['square'][0]:g} x {r['square'][1]:g} m |")
    c = result["candidate"]
    lines += ["", "## Candidate layout", "",
              f"{c['note']}: {c['n_anchors']} Anchors at {_xy(c['anchors'])}; "
              f"coverage {_cov(c['coverage'])}. Written to `candidate_layout.yaml`.", "",
              "Reference points or Test positions within "
              f"{CLASH_M:g} m of a candidate Anchor (move them): "
              f"{', '.join(c['clashes']) or 'none'}.", "",
              "Hardest Reference points under it (pilot points for the capture day):", "",
              f"| point | x, y | {MIN_ANCHORS}rd strongest Anchor |", "|---|---|---|"]
    for r in c["hardest_points"]:
        lines.append(f"| {r['point']} | {r['x']:g}, {r['y']:g} | {r['kth_rssi_dbm']:.1f} dBm |")
    return "\n".join(lines) + "\n"


def run(report_path: Path, layout_path: Path, margins: Sequence[float], max_anchors: int,
        candidate_margin: float, floor_dbm: float = RSSI_FLOOR_DBM) -> Tuple[dict, str]:
    layout = load_layout(layout_path)
    report = json.loads(Path(report_path).read_text())
    fit = fit_path_loss(report, layout.anchors)
    room = (0.0, 0.0, layout.width_m, layout.height_m)
    ranges = {str(m): anchor_range_m(fit, floor_dbm + m) for m in margins}
    result = {
        "report": str(report_path), "layout": str(layout_path), "floor_dbm": floor_dbm,
        "margins_db": list(margins), "room": [layout.width_m, layout.height_m],
        "fit": fit, "range_m": ranges,
        "distance_curve": distance_curve(report, layout.anchors, floor_dbm, fit=fit),
        "whole_room": {}, "largest_area": [],
        "current": current_layout(report, layout, fit, floor_dbm),
    }
    for walls in (True, False):
        for m in margins:
            result["whole_room"][f"{'walls' if walls else 'anywhere'}/{m:g}"] = whole_room(
                room, ranges[str(m)], walls, max_anchors)
    aspect = layout.width_m / layout.height_m
    for m in margins:
        # Spare Anchors can stay unused, so each count keeps the best of fewer.
        shaped, square = (0.0, 0.0), (0.0, 0.0)
        for n in [c for c in AREA_COUNTS if c <= max_anchors]:
            shaped = max(shaped, largest_area(n, ranges[str(m)], layout.width_m,
                                              layout.height_m, aspect)[:2])
            square = max(square, largest_area(n, ranges[str(m)], layout.width_m,
                                              layout.height_m, 1.0)[:2])
            result["largest_area"].append({"n_anchors": n, "margin_db": m,
                                           "room_shaped": list(shaped), "square": list(square)})
    rows = whole_room(room, anchor_range_m(fit, floor_dbm + candidate_margin), False,
                      max_anchors)
    best = rows[-1]
    full = best["coverage"] == 1.0
    note = (f"fewest Anchors (anywhere) covering the whole room at a "
            f"{candidate_margin:g} dB margin" if full else
            f"no count up to {max_anchors} covers the whole room at a {candidate_margin:g} dB "
            f"margin; best found with {best['n_anchors']}")
    result["candidate"] = {
        "note": note, "margin_db": candidate_margin, "n_anchors": best["n_anchors"],
        "anchors": best["anchors"], "coverage": best["coverage"],
        "hardest_points": hardest_points(layout, best["anchors"], fit),
        "clashes": clashes(layout, best["anchors"]),
    }
    return result, candidate_yaml(layout_path, best["anchors"], fit, note)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        prog="gateway.layout_search", description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--report", required=True, type=Path,
                    help="calibration report.json of a real session")
    ap.add_argument("--layout", required=True, type=Path,
                    help="the session's layout: room size, Anchor positions")
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--margin", type=float, nargs="+", default=list(MARGINS_DB),
                    help="dB above the floor a spot's Anchors must clear (default 0 3)")
    ap.add_argument("--max-anchors", type=int, default=MAX_ANCHORS)
    ap.add_argument("--candidate-margin", type=float, default=0.0,
                    help="margin the candidate layout must meet everywhere (default 0)")
    args = ap.parse_args(argv)

    result, candidate = run(args.report, args.layout, args.margin, args.max_anchors,
                            args.candidate_margin)
    args.out.mkdir(parents=True, exist_ok=True)
    with open(args.out / "layout_search.json", "w") as fh:
        json.dump(result, fh, indent=2)
    (args.out / "candidate_layout.yaml").write_text(candidate)
    md = format_markdown(result)
    (args.out / "summary.md").write_text(md)
    print(md)
    return 0


if __name__ == "__main__":
    sys.exit(main())
