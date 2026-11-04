"""Trimmed vs untrimmed Calibration windows: does trimming change the Radio map? (#47)

    python -m gateway.trim_ablation --trimmed out/techhub \
        --untrimmed out/techhub_untrimmed --out out/techhub/trim_ablation

Each side is an imported session root (gateway.session_import, with and
without --untrimmed). Both Radio maps are rebuilt here from the session's
Captures with the default preprocessing, so neither side reuses a saved map
that could be stale. Writes, under --out:

- differences.csv: per Reference point and Anchor, untrimmed minus trimmed
  mean RSSI, the Euclidean distance between the two D-CFR vectors and
  between the two raw amplitude vectors, and both window counts; a point in
  only one map gets one row with no Anchor.
- recordings.csv: per Reference point, how long the Beacon was recorded
  (first to last Record) and whether the recording fell short of the trim.
- loo.csv / loo.tex: leave-one-out k-NN error over each map's Reference
  points, in the CSV + LaTeX form the #29 ablation tables use. This is a
  SANITY CHECK, not a result: Test positions are held out and measured on
  another day (ADR-0003); leave-one-out only says whether the map is
  self-consistent. A Reference point with no sufficient window is in
  neither map and so is not scored; the summary names those points.
- summary.md: all of the above in short.
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
LONG_RECORDING_MIN = 15.0


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
        pt_trim, pt_untrim = trimmed.points.get(pid), untrimmed.points.get(pid)
        n_windows = (pt_trim.n_windows if pt_trim else 0,
                     pt_untrim.n_windows if pt_untrim else 0)
        if pt_trim is None or pt_untrim is None:
            rows.append({"point": pid, "anchor": None, "rssi_delta_db": None,
                         "dcfr_distance": None, "amp_distance": None,
                         "n_windows": n_windows})
            continue
        for a in trimmed.anchor_ids:
            fp_trim, fp_untrim = pt_trim.anchors.get(a), pt_untrim.anchors.get(a)
            both = fp_trim is not None and fp_untrim is not None
            rows.append({
                "point": pid, "anchor": a,
                "rssi_delta_db": fp_untrim.rssi - fp_trim.rssi if both else None,
                "dcfr_distance": (float(np.linalg.norm(fp_untrim.dcfr - fp_trim.dcfr))
                                  if both else None),
                "amp_distance": (float(np.linalg.norm(fp_untrim.amp - fp_trim.amp))
                                 if both else None),
                "n_windows": n_windows,
            })
    return rows


def unmapped_points(radio_map: RadioMap, truth: dict) -> List[str]:
    """Reference points of the session that have no entry in the Radio map
    (no sufficient window), in walk order."""
    return [t["id"] for t in truth["trials"] if t["id"] not in radio_map.points]


def recordings(truth: dict) -> dict:
    """How long the Beacon was recorded at each point, in minutes; `long`
    lists recordings over LONG_RECORDING_MIN, `short` those the import cut
    at their last Record."""
    minutes = {t["id"]: (t["beacon_last"] - t["beacon_first"]) / 60.0
               for t in truth["trials"]}
    return {
        "minutes": minutes,
        "median_min": float(np.median(list(minutes.values()))),
        "long": [(p, m) for p, m in minutes.items() if m > LONG_RECORDING_MIN],
        "short": [(t["id"], minutes[t["id"]]) for t in truth["trials"] if t.get("short")],
    }


def _session_map(root: Path, windows_out: Path):
    meta, windows, truth = preprocess_session(root / "calibration", windows_out)
    return build_radio_map(windows, meta, truth), truth


def _cell(v, spec=".2f") -> str:
    return "" if v is None else format(v, spec)


def _stats(values: List[float], spec: str) -> str:
    return f"median {format(np.median(values), spec)}, max {format(max(values), spec)}"


def write_outputs(out: Path, rows: List[dict], loo: Dict[str, dict],
                  unmapped: Dict[str, List[str]], n_reference_points: int,
                  rec: dict) -> str:
    out.mkdir(parents=True, exist_ok=True)
    with open(out / "differences.csv", "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["point", "anchor", "rssi_delta_db", "dcfr_distance", "amp_distance",
                    "n_windows_trimmed", "n_windows_untrimmed"])
        for r in rows:
            w.writerow([r["point"], r["anchor"] or "", _cell(r["rssi_delta_db"]),
                        _cell(r["dcfr_distance"], ".4f"), _cell(r["amp_distance"], ".4f"),
                        *r["n_windows"]])
    short = {p for p, _ in rec["short"]}
    with open(out / "recordings.csv", "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["point", "beacon_minutes", "short"])
        for p, m in rec["minutes"].items():
            w.writerow([p, f"{m:.1f}", int(p in short)])
    with open(out / "loo.csv", "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["map", "k", "reference_points", "median_m", "mean_m", "p90_m"])
        for name, res in loo.items():
            w.writerow([name, res["k"], res["n_points"], _cell(res["median_m"]),
                        _cell(res["mean_m"]), _cell(res["p90_m"])])
    tex = [
        "% Leave-one-out k-NN over the TechHub Radio map: a sanity check, not a result (ADR-0003).",
        "\\begin{tabular}{lrrrrr}", "\\hline",
        "Map & $k$ & Points & Median (m) & Mean (m) & p90 (m) \\\\", "\\hline",
    ]
    tex += [f"{name} & {r['k']} & {r['n_points']} & {r['median_m']:.2f} & "
            f"{r['mean_m']:.2f} & {r['p90_m']:.2f} \\\\" for name, r in loo.items()]
    tex += ["\\hline", "\\end{tabular}"]
    (out / "loo.tex").write_text("\n".join(tex) + "\n")
    with open(out / "loo.json", "w") as fh:
        json.dump(loo, fh, indent=2)

    rssi_deltas = [abs(r["rssi_delta_db"]) for r in rows if r["rssi_delta_db"] is not None]
    dcfr = [r["dcfr_distance"] for r in rows if r["dcfr_distance"] is not None]
    amp = [r["amp_distance"] for r in rows if r["amp_distance"] is not None]
    changed_points = sorted({r["point"] for r in rows if r["rssi_delta_db"] is not None
                             and abs(r["rssi_delta_db"]) > BIG_RSSI_DELTA_DB})
    single_map = [f"{r['point']} (windows {r['n_windows'][0]} trimmed / "
                  f"{r['n_windows'][1]} untrimmed)" for r in rows if r["anchor"] is None]

    def spans(items):
        return ", ".join(f"{p} {m:.1f} min" for p, m in items) or "none"

    lines = [
        "# Trimmed vs untrimmed Calibration windows", "",
        f"- Beacon recording per point: median {rec['median_min']:.1f} min",
        f"- Recordings over {LONG_RECORDING_MIN:.0f} min (trimmed like the rest): "
        f"{spans(rec['long'])}",
        f"- Recordings short of skip + keep (span cut at the last Record): "
        f"{spans(rec['short'])}",
    ]
    for name, missing in unmapped.items():
        lines.append(f"- Reference points in the {name} map: "
                     f"{n_reference_points - len(missing)}/{n_reference_points}; "
                     f"no sufficient window: {', '.join(missing) or 'none'}")
    lines += [
        f"- Points in one map but not the other: {', '.join(single_map) or 'none'}",
        f"- (point, Anchor) pairs compared: {len(rssi_deltas)}",
        f"- |RSSI change|: {_stats(rssi_deltas, '.2f')} dB",
        f"- D-CFR distance: {_stats(dcfr, '.4f')}",
        f"- Raw amplitude distance: {_stats(amp, '.4f')}",
        f"- Points with an Anchor's RSSI changed > {BIG_RSSI_DELTA_DB:.0f} dB: "
        f"{', '.join(changed_points) or 'none'}",
        "", "Leave-one-out k-NN over the mapped points "
        "(sanity check, not a result; ADR-0003):", "",
        "| map | k | points | median m | mean m | p90 m |", "|---|---|---|---|---|---|",
    ]
    lines += [f"| {n} | {r['k']} | {r['n_points']}/{n_reference_points} | "
              f"{r['median_m']:.2f} | {r['mean_m']:.2f} | {r['p90_m']:.2f} |"
              for n, r in loo.items()]
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
    trimmed, truth = _session_map(args.trimmed, args.out / "trimmed_windows.jsonl")
    untrimmed, untrimmed_truth = _session_map(args.untrimmed,
                                              args.out / "untrimmed_windows.jsonl")
    loo = {"trimmed": leave_one_out(trimmed, args.k),
           "untrimmed": leave_one_out(untrimmed, args.k)}
    unmapped = {"trimmed": unmapped_points(trimmed, truth),
                "untrimmed": unmapped_points(untrimmed, untrimmed_truth)}
    print(write_outputs(args.out, compare_maps(trimmed, untrimmed), loo, unmapped,
                        len(truth["trials"]), recordings(truth)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
