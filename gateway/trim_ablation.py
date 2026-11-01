"""Trimmed vs untrimmed Calibration windows: does trimming change the Radio map? (#47)

    python -m gateway.trim_ablation --trimmed out/techhub \
        --untrimmed out/techhub_untrimmed --out out/techhub/trim_ablation

Each side is an imported session root (gateway.session_import, with and
without --untrimmed). Its Radio map is read from <root>/report/radio_map.json
when gateway.calibration_report has built it, else built here with the same
default preprocessing. Writes, under --out:

- differences.csv: per Reference point and Anchor, untrimmed minus trimmed
  mean RSSI, the Euclidean distance between the two D-CFR fingerprints, and
  both window counts; a point in only one map gets one row with no Anchor.
- loo.csv / loo.tex: leave-one-out k-NN error over each map's Reference
  points, in the CSV + LaTeX form the #29 ablation tables use. This is a
  SANITY CHECK, not a result: Test positions are held out and measured on
  another day (ADR-0003); leave-one-out only says whether the map is
  self-consistent.
- summary.md: both of the above in short.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
from typing import Dict, List

import numpy as np

from gateway.evaluate import preprocess_session
from gateway.knn import KnnLocalizer, feature_vector
from gateway.radiomap import RadioMap, build_radio_map

BIG_RSSI_DELTA_DB = 3.0


def leave_one_out(radio_map: RadioMap, k: int = 3) -> dict:
    """k-NN error of each Reference point located against all the others."""
    errors: Dict[str, float] = {}
    for pid, point in radio_map.points.items():
        rest = RadioMap(anchor_ids=radio_map.anchor_ids, meta=radio_map.meta,
                        points={p: v for p, v in radio_map.points.items() if p != pid})
        knn = KnnLocalizer(rest, k=k)
        anchors = {a: None if fp is None else {"rssi": fp.rssi, "dcfr": fp.dcfr}
                   for a, fp in point.anchors.items()}
        x, y = knn.estimate_from_vector(
            feature_vector(anchors, knn.anchor_ids, knn.n_dcfr, knn.floor_dbm))
        errors[pid] = float(np.hypot(x - point.x, y - point.y))
    values = np.array(list(errors.values()))
    return {
        "k": k,
        "n_points": len(errors),
        "errors": errors,
        "median_m": float(np.median(values)),
        "mean_m": float(values.mean()),
        "p90_m": float(np.percentile(values, 90)),
    }


def compare_maps(trimmed: RadioMap, untrimmed: RadioMap) -> List[dict]:
    """Per (point, Anchor) differences, untrimmed minus trimmed."""
    rows = []
    order = list(trimmed.points) + [p for p in untrimmed.points if p not in trimmed.points]
    for pid in order:
        t, u = trimmed.points.get(pid), untrimmed.points.get(pid)
        n_windows = (t.n_windows if t else 0, u.n_windows if u else 0)
        if t is None or u is None:
            rows.append({"point": pid, "anchor": None, "rssi_delta_db": None,
                         "dcfr_distance": None, "n_windows": n_windows})
            continue
        for a in trimmed.anchor_ids:
            ft, fu = t.anchors.get(a), u.anchors.get(a)
            both = ft is not None and fu is not None
            rows.append({
                "point": pid, "anchor": a,
                "rssi_delta_db": fu.rssi - ft.rssi if both else None,
                "dcfr_distance": float(np.linalg.norm(fu.dcfr - ft.dcfr)) if both else None,
                "n_windows": n_windows,
            })
    return rows


def _radio_map(root: Path, scratch: Path) -> RadioMap:
    saved = root / "report" / "radio_map.json"
    if saved.exists():
        return RadioMap.load(saved)
    meta, windows, truth = preprocess_session(root / "calibration", scratch)
    return build_radio_map(windows, meta, truth)


def _fmt(v, spec=".2f") -> str:
    return "" if v is None else format(v, spec)


def write_outputs(out: Path, rows: List[dict], loo: Dict[str, dict]) -> str:
    out.mkdir(parents=True, exist_ok=True)
    with open(out / "differences.csv", "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["point", "anchor", "rssi_delta_db", "dcfr_distance",
                    "n_windows_trimmed", "n_windows_untrimmed"])
        for r in rows:
            w.writerow([r["point"], r["anchor"] or "", _fmt(r["rssi_delta_db"]),
                        _fmt(r["dcfr_distance"], ".4f"), *r["n_windows"]])
    with open(out / "loo.csv", "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["map", "k", "reference_points", "median_m", "mean_m", "p90_m"])
        for name, res in loo.items():
            w.writerow([name, res["k"], res["n_points"], _fmt(res["median_m"]),
                        _fmt(res["mean_m"]), _fmt(res["p90_m"])])
    tex = [
        "% Leave-one-out k-NN over the Tech Hub Radio map: a sanity check, not a result (ADR-0003).",
        "\\begin{tabular}{lrrrrr}", "\\hline",
        "Map & $k$ & Points & Median (m) & Mean (m) & p90 (m) \\\\", "\\hline",
    ]
    tex += [f"{name} & {r['k']} & {r['n_points']} & {r['median_m']:.2f} & "
            f"{r['mean_m']:.2f} & {r['p90_m']:.2f} \\\\" for name, r in loo.items()]
    tex += ["\\hline", "\\end{tabular}"]
    (out / "loo.tex").write_text("\n".join(tex) + "\n")
    with open(out / "loo.json", "w") as fh:
        json.dump(loo, fh, indent=2)

    deltas = [abs(r["rssi_delta_db"]) for r in rows if r["rssi_delta_db"] is not None]
    dists = [r["dcfr_distance"] for r in rows if r["dcfr_distance"] is not None]
    big = sorted({r["point"] for r in rows
                  if r["rssi_delta_db"] is not None and abs(r["rssi_delta_db"]) > BIG_RSSI_DELTA_DB})
    only = [f"{r['point']} (windows {r['n_windows'][0]} trimmed / {r['n_windows'][1]} untrimmed)"
            for r in rows if r["anchor"] is None]
    lines = [
        "# Trimmed vs untrimmed Calibration windows", "",
        f"- (point, Anchor) pairs compared: {len(deltas)}",
        f"- |RSSI change|: median {np.median(deltas):.2f} dB, max {max(deltas):.2f} dB",
        f"- D-CFR fingerprint distance: median {np.median(dists):.4f}, max {max(dists):.4f}",
        f"- Points with an Anchor's RSSI changed > {BIG_RSSI_DELTA_DB:.0f} dB: "
        f"{', '.join(big) or 'none'}",
        f"- Points in only one map: {', '.join(only) or 'none'}",
        "", "Leave-one-out k-NN (sanity check, not a result; ADR-0003):", "",
        "| map | k | points | median m | mean m | p90 m |", "|---|---|---|---|---|---|",
    ]
    lines += [f"| {n} | {r['k']} | {r['n_points']} | {r['median_m']:.2f} | "
              f"{r['mean_m']:.2f} | {r['p90_m']:.2f} |" for n, r in loo.items()]
    md = "\n".join(lines) + "\n"
    (out / "summary.md").write_text(md)
    return md


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        prog="gateway.trim_ablation", description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--trimmed", required=True, type=Path)
    ap.add_argument("--untrimmed", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--k", type=int, default=3)
    args = ap.parse_args(argv)

    args.out.mkdir(parents=True, exist_ok=True)
    trimmed = _radio_map(args.trimmed, args.out / "trimmed_windows.jsonl")
    untrimmed = _radio_map(args.untrimmed, args.out / "untrimmed_windows.jsonl")
    loo = {"trimmed": leave_one_out(trimmed, args.k),
           "untrimmed": leave_one_out(untrimmed, args.k)}
    print(write_outputs(args.out, compare_maps(trimmed, untrimmed), loo))
    return 0


if __name__ == "__main__":
    sys.exit(main())
