"""Figures of a real Calibration session, drawn over the room (#46, #47).

    python -m gateway.plot_calibration --report out/techhub/report/report.json \
        --loo out/techhub/trim_ablation/loo.json --out out/techhub/plots

Reads only generated files (the calibration report, and optionally the
trimming comparison's leave-one-out errors), so every figure traces to the
same numbers as Appendix H. Each Reference point is one cell of the 1.2 m
lattice, seen from above with A4 at the origin. Writes PNG and PDF of:

- rssi_by_anchor: per Anchor, the median Beacon RSSI with the Beacon at
  each Reference point; cells at or above the Sniper's floor are outlined.
- coverage: sufficient windows per point (holes marked), and how many
  Anchors hear the Beacon above the floor in most of the point's windows.
- loo_error: leave-one-out k-NN error per point (sanity check, ADR-0003).

Needs the `viz` extra (matplotlib).
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from gateway.features import DEFAULT_RSSI_FLOOR_DBM
from gateway.sim import load_layout

# Sequential blue ramp, light -> dark (dataviz reference palette, steps 100-700).
BLUE = ["#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95", "#0d366b"]
NO_DATA = "#e4e3df"
INK, MUTED = "#0b0b0b", "#52514e"
STEP_M = 1.2


def grid_values(points: Dict[str, dict], values: Dict[str, Optional[float]],
                width_m: float, height_m: float, step_m: float = STEP_M
                ) -> Tuple[List[float], List[float], List[List[float]]]:
    """Lattice x and y coordinates and a rows-by-y grid of `values` (NaN
    where there is no point or no value)."""
    xs = [round(i * step_m, 6) for i in range(round(width_m / step_m) + 1)]
    ys = [round(j * step_m, 6) for j in range(round(height_m / step_m) + 1)]
    grid = [[math.nan] * len(xs) for _ in ys]
    for pid, p in points.items():
        v = values.get(pid)
        if v is not None:
            grid[round(p["y"] / step_m)][round(p["x"] / step_m)] = v
    return xs, ys, grid


def _room_axes(ax, layout, title: str) -> None:
    import matplotlib.patheffects as pe

    ax.set_xlim(-STEP_M, layout.width_m + STEP_M)
    ax.set_ylim(-STEP_M / 2, layout.height_m + STEP_M / 2)
    ax.set_aspect("equal")
    ax.set_title(title, loc="left", fontsize=10, color=INK)
    ax.tick_params(labelsize=7, colors=MUTED, length=0)
    ax.set_xticks([x for x in range(0, int(layout.width_m) + 1, 2)])
    ax.set_xlabel("x (m)", fontsize=7, color=MUTED)
    ax.set_ylabel("y (m)", fontsize=7, color=MUTED)
    for side in ax.spines.values():
        side.set_visible(False)
    for name, (x, y) in layout.anchors.items():
        ax.plot(x, y, marker="^", markersize=9, color=INK, markeredgecolor="white",
                markeredgewidth=1.5, zorder=4)
        left = x < layout.width_m / 2          # label outside the room, beside the corner
        ax.annotate(name, (x, y), xytext=(-9 if left else 9, 0),
                    textcoords="offset points", ha="right" if left else "left", va="center",
                    fontsize=7, color=INK, zorder=5,
                    path_effects=[pe.withStroke(linewidth=2.5, foreground="white")])


def _heat(ax, layout, points, values, cmap, norm, title, outline=None, marks=None):
    import numpy as np

    xs, ys, grid = grid_values(points, values, layout.width_m, layout.height_m)
    ax.set_facecolor("white")
    point_cells = {(round(p["x"] / STEP_M), round(p["y"] / STEP_M)) for p in points.values()}
    for i, j in point_cells:                      # gray under every point: no data
        ax.add_patch(_cell(xs[i], ys[j], NO_DATA, hatch="////"))
    mesh = ax.pcolormesh(np.array(xs + [xs[-1] + STEP_M]) - STEP_M / 2,
                         np.array(ys + [ys[-1] + STEP_M]) - STEP_M / 2,
                         np.ma.masked_invalid(np.array(grid)), cmap=cmap, norm=norm,
                         edgecolors="white", linewidth=2)
    for pid in outline or ():
        p = points[pid]
        ax.add_patch(_cell(p["x"], p["y"], "none", edge=INK, lw=1.6, inset=0.1))
    for pid, text in (marks or {}).items():
        p, v = points[pid], values.get(pid)
        r, g, b, _ = cmap(norm(v)) if v is not None else (1, 1, 1, 1)
        dark = 0.2126 * r + 0.7152 * g + 0.0722 * b < 0.45   # white ink on dark cells
        ax.text(p["x"], p["y"], text, ha="center", va="center", fontsize=7,
                color="white" if dark else INK, fontweight="bold", zorder=6)
    _room_axes(ax, layout, title)
    return mesh


def _cell(x, y, face, edge="white", lw=2.0, hatch=None, inset=0.0):
    from matplotlib.patches import Rectangle

    half = STEP_M / 2 - inset
    return Rectangle((x - half, y - half), 2 * half, 2 * half, facecolor=face,
                     edgecolor=edge, linewidth=lw, hatch=hatch, zorder=1 if face != "none" else 3)


def _save(fig, out: Path, name: str) -> List[Path]:
    paths = [out / f"{name}.png", out / f"{name}.pdf"]
    for path in paths:
        fig.savefig(path, dpi=200, bbox_inches="tight", facecolor="white")
    return paths


def plot_rssi_by_anchor(report: dict, layout, out: Path,
                        floor_dbm: float = DEFAULT_RSSI_FLOOR_DBM) -> List[Path]:
    import matplotlib.pyplot as plt
    from matplotlib.colors import LinearSegmentedColormap, Normalize

    points = report["points"]
    anchors = sorted(next(iter(points.values()))["anchors"])
    cmap = LinearSegmentedColormap.from_list("rssi", BLUE)
    norm = Normalize(vmin=-96, vmax=-62)
    fig, axes = plt.subplots(2, 2, figsize=(10, 5.6), constrained_layout=True)
    for ax, a in zip(axes.flat, anchors):
        values = {pid: p["anchors"][a]["median_rssi"] for pid, p in points.items()}
        above = [pid for pid, v in values.items() if v is not None and v >= floor_dbm]
        faults = {pid: "F" for pid, p in points.items()
                  if p["anchors"][a]["status"] == "fault"}
        mesh = _heat(ax, layout, points, values, cmap, norm,
                     f"{a}: median Beacon RSSI", outline=above, marks=faults)
    bar = fig.colorbar(mesh, ax=axes, shrink=0.8, label="median RSSI (dBm), darker = stronger")
    bar.ax.axhline(floor_dbm, color=INK, linewidth=1.2)
    bar.ax.tick_params(labelsize=7)
    fig.suptitle(f"Beacon heard at each Reference point. Outlined: at or above the "
                 f"{floor_dbm:.0f} dBm floor. Hatched: not heard. F: field-noted fault.",
                 fontsize=9, color=MUTED, x=0.01, ha="left")
    paths = _save(fig, out, "rssi_by_anchor")
    plt.close(fig)
    return paths


def plot_coverage(report: dict, layout, out: Path, majority: float = 0.5) -> List[Path]:
    import matplotlib.pyplot as plt
    from matplotlib.colors import BoundaryNorm, LinearSegmentedColormap, ListedColormap, Normalize

    points = report["points"]
    fig, (left, right) = plt.subplots(1, 2, figsize=(11, 3.4), constrained_layout=True)
    sufficient = {pid: p["n_sufficient"] for pid, p in points.items()}
    holes = {pid: ("0" if p["hole"] == "empty" else str(p["n_sufficient"]))
             for pid, p in points.items() if p["hole"]}
    mesh = _heat(left, layout, points, sufficient,
                 LinearSegmentedColormap.from_list("windows", BLUE),
                 Normalize(vmin=0, vmax=max(sufficient.values())),
                 "Sufficient windows (outlined: < 30, recapture)",
                 outline=list(holes), marks=holes)
    fig.colorbar(mesh, ax=left, shrink=0.85, label="windows").ax.tick_params(labelsize=7)

    def strong(p):
        return sum(1 for c in p["anchors"].values()
                   if c["above_floor_rate"] is not None and c["above_floor_rate"] > majority)
    counts = {pid: strong(p) for pid, p in points.items()}
    ramp = ["#f0efec", BLUE[1], BLUE[3], BLUE[5], BLUE[6]]
    mesh = _heat(right, layout, points, counts, ListedColormap(ramp),
                 BoundaryNorm([-0.5, 0.5, 1.5, 2.5, 3.5, 4.5], 5),
                 "Anchors above the floor in most windows (Sniper needs 3)",
                 marks={pid: str(n) for pid, n in counts.items()})
    bar = fig.colorbar(mesh, ax=right, shrink=0.85, ticks=range(5), label="Anchors")
    bar.ax.tick_params(labelsize=7)
    paths = _save(fig, out, "coverage")
    plt.close(fig)
    return paths


def plot_loo_error(report: dict, loo: dict, layout, out: Path) -> List[Path]:
    import matplotlib.pyplot as plt
    from matplotlib.colors import LinearSegmentedColormap, Normalize

    points = report["points"]
    fig, axes = plt.subplots(1, len(loo), figsize=(5.5 * len(loo), 3.4),
                             constrained_layout=True, squeeze=False)
    top = max(max(r["errors"].values()) for r in loo.values())
    for ax, (name, res) in zip(axes.flat, loo.items()):
        mesh = _heat(ax, layout, points, res["errors"],
                     LinearSegmentedColormap.from_list("err", BLUE), Normalize(0, top),
                     f"Leave-one-out k-NN error, {name} (median {res['median_m']:.2f} m)",
                     marks={pid: f"{e:.1f}" for pid, e in res["errors"].items()})
    fig.colorbar(mesh, ax=axes, shrink=0.85, label="error (m)").ax.tick_params(labelsize=7)
    fig.suptitle("Sanity check, not a result (ADR-0003). Hatched: no sufficient window, "
                 "not in the Radio map.", fontsize=9, color=MUTED, x=0.01, ha="left")
    paths = _save(fig, out, "loo_error")
    plt.close(fig)
    return paths


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        prog="gateway.plot_calibration", description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--report", required=True, type=Path, help="calibration report.json")
    ap.add_argument("--loo", type=Path, help="trim_ablation loo.json (optional)")
    ap.add_argument("--layout", type=Path, default=Path("layouts/techhub_default.yaml"))
    ap.add_argument("--out", required=True, type=Path)
    args = ap.parse_args(argv)

    import matplotlib
    matplotlib.use("Agg")

    args.out.mkdir(parents=True, exist_ok=True)
    report = json.loads(args.report.read_text())
    layout = load_layout(args.layout)
    written = plot_rssi_by_anchor(report, layout, args.out) + plot_coverage(report, layout, args.out)
    if args.loo and args.loo.exists():
        written += plot_loo_error(report, json.loads(args.loo.read_text()), layout, args.out)
    for path in written:
        print(path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
