"""Evaluation harness: calibration -> Radio map -> localizer -> results.

    python -m gateway.evaluate --sim sim_data --layout layouts/techhub_default.yaml \
        --out out/eval

Preprocesses the Calibration session and builds the Radio map, then runs a
localizer over every window of the test session's placed device and scores
each Trial against ground truth (ADR-0003 metrics): MAE, RMSE, median and
p90 error, coarse-zone accuracy (zones from the layout), availability
(windows with an estimate / all of the device's windows in the Trial) and
per-window processing latency. Results go to stdout as a table and to
<out>/baseline.json for the chapter tables. Each Trial also reports its
sufficient-window count; ADR-0003 repeats a Trial with fewer than 30, and
the CLI warns about those.

A localizer is any object with a `name` and an `estimate(window) ->
(x, y) | None` method over one preprocessed window dict; the k-NN baseline
is the first, and later localizers plug into `evaluate()` unchanged. A
localizer that also reports a bounding box (the Scout) adds a
`locate(window) -> {"x", "y", "bbox"} | None` method; the harness then
scores bbox hit-rate (the box contains the true position) and mean bbox
area as a fraction of the room. Further per-window fields (#28's Mode) go
in the same dict.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

import numpy as np

from gateway.io import read_jsonl
from gateway.knn import KnnLocalizer
from gateway.preprocess import PreprocessConfig, run
from gateway.radiomap import build_radio_map
from gateway.trials import placed_device, windows_by_trial
from gateway.sim import Layout, load_layout, zone_of


MIN_SUFFICIENT_WINDOWS = 30  # per Trial, ADR-0003


def metrics(
    errors: Sequence[float],
    zone_hits: Sequence[bool],
    n_windows: int,
    latencies_s: Sequence[float],
) -> dict:
    """Per-Trial (or pooled) error statistics; error fields are None when
    no window produced an estimate."""
    e = np.asarray(errors, dtype=np.float64)
    lat_ms = np.asarray(latencies_s, dtype=np.float64) * 1000.0
    have = len(e) > 0

    def stat(fn):
        return float(fn(e)) if have else None

    return {
        "n_windows": n_windows,
        "n_estimates": len(e),
        "availability": len(e) / n_windows if n_windows else 0.0,
        "mae_m": stat(np.mean),
        "rmse_m": stat(lambda v: np.sqrt(np.mean(v ** 2))),
        "median_m": stat(np.median),
        "p90_m": stat(lambda v: np.percentile(v, 90)),
        "zone_accuracy": float(np.mean(zone_hits)) if have else None,
        "latency_ms_mean": float(lat_ms.mean()) if len(lat_ms) else None,
        "latency_ms_p95": float(np.percentile(lat_ms, 95)) if len(lat_ms) else None,
    }


def bbox_metrics(box_hits: Sequence[bool], box_area_fracs: Sequence[float]) -> dict:
    """Bbox hit-rate and mean area / room area; None without boxes."""
    return {
        "bbox_hit_rate": float(np.mean(box_hits)) if len(box_hits) else None,
        "bbox_area_frac": float(np.mean(box_area_fracs)) if len(box_area_fracs) else None,
    }


def _locate(localizer, window: dict) -> Optional[dict]:
    if hasattr(localizer, "locate"):
        return localizer.locate(window)
    est = localizer.estimate(window)
    return None if est is None else {"x": est[0], "y": est[1]}


def evaluate(localizer, windows: List[dict], truth: dict, layout: Layout) -> dict:
    """Score `localizer` on every Trial of a test session."""
    per_trial = windows_by_trial(windows, truth)
    room_area = layout.width_m * layout.height_m

    rows = []
    pooled: Tuple[list, ...] = ([], [], [], [], [])
    n_total = 0
    for trial in truth["trials"]:
        device = placed_device(trial)
        tx, ty = device["x"], device["y"]
        true_zone = zone_of(layout, tx, ty)
        errors, hits, latencies, box_hits, box_areas = [], [], [], [], []
        for w in per_trial[trial["id"]]:
            t0 = time.perf_counter()
            loc = _locate(localizer, w)
            elapsed = time.perf_counter() - t0
            if loc is None:
                continue
            latencies.append(elapsed)
            errors.append(float(np.hypot(loc["x"] - tx, loc["y"] - ty)))
            hits.append(zone_of(layout, loc["x"], loc["y"]) == true_zone)
            if loc.get("bbox") is not None:
                x0, y0, x1, y1 = loc["bbox"]
                box_hits.append(x0 <= tx <= x1 and y0 <= ty <= y1)
                box_areas.append((x1 - x0) * (y1 - y0) / room_area)
        n = len(per_trial[trial["id"]])
        rows.append({
            "id": trial["id"], "device": device["name"],
            "x": tx, "y": ty, "zone": true_zone,
            "n_sufficient": sum(w["sufficient"] for w in per_trial[trial["id"]]),
            **metrics(errors, hits, n, latencies),
            **bbox_metrics(box_hits, box_areas),
        })
        for acc, vals in zip(pooled, (errors, hits, latencies, box_hits, box_areas)):
            acc.extend(vals)
        n_total += n
    errors, hits, latencies, box_hits, box_areas = pooled
    return {
        "trials": rows,
        "overall": {**metrics(errors, hits, n_total, latencies),
                    **bbox_metrics(box_hits, box_areas)},
    }


def preprocess_session(session_dir: Path, out: Path) -> Tuple[dict, List[dict], dict]:
    """Preprocess every Trial of a simulated session in one run (raw
    amplitude kept); returns (meta, windows, ground truth)."""
    truth = json.loads((session_dir / "ground_truth.json").read_text())
    run(PreprocessConfig(
        inputs=[session_dir / t["id"] for t in truth["trials"]],
        out=out, include_csi52=True,
    ))
    meta, windows = read_jsonl(out)
    return meta, windows, truth


def run_baseline(sim_dir: Path, layout: Layout, out_dir: Path, k: int = 3) -> dict:
    """Calibration -> Radio map -> k-NN over the test session -> results,
    written to <out_dir>/radio_map.json and <out_dir>/baseline.json."""
    sim_dir, out_dir = Path(sim_dir), Path(out_dir)
    cal_meta, cal_windows, cal_truth = preprocess_session(
        sim_dir / "calibration", out_dir / "calibration_windows.jsonl")
    radio_map = build_radio_map(cal_windows, cal_meta, cal_truth)
    radio_map.save(out_dir / "radio_map.json")

    _, test_windows, test_truth = preprocess_session(
        sim_dir / "test", out_dir / "test_windows.jsonl")
    localizer = KnnLocalizer(radio_map, k=k)
    result = evaluate(localizer, test_windows, test_truth, layout)
    result["meta"] = {
        "localizer": localizer.name,
        "k": k,
        "layout": str(layout.path) if layout.path else None,
        "sim": str(sim_dir),
        "reference_points": len(radio_map.points),
        "preprocess": cal_meta,
    }
    with open(out_dir / "baseline.json", "w") as fh:
        json.dump(result, fh, indent=2)
    return result


def _fmt(v: Optional[float], spec: str = ".2f") -> str:
    return "-" if v is None else format(v, spec)


def format_table(result: dict) -> str:
    """Per-Trial table; bbox columns appear when the localizer reports boxes."""
    boxes = result["overall"]["bbox_hit_rate"] is not None
    head = (f"{'Trial':<8}{'zone':<6}{'win':>5}{'avail':>7}{'MAE':>7}{'RMSE':>7}"
            f"{'median':>8}{'p90':>7}{'zone acc':>10}{'ms/win':>8}")
    if boxes:
        head += f"{'bbox hit':>10}{'bbox area':>11}"
    lines = [head, "-" * len(head)]
    for row in result["trials"] + [dict(result["overall"], id="overall", zone="")]:
        line = (
            f"{row['id']:<8}{row['zone'] or '':<6}{row['n_windows']:>5}"
            f"{_fmt(row['availability'], '.0%'):>7}{_fmt(row['mae_m']):>7}"
            f"{_fmt(row['rmse_m']):>7}{_fmt(row['median_m']):>8}{_fmt(row['p90_m']):>7}"
            f"{_fmt(row['zone_accuracy'], '.0%'):>10}{_fmt(row['latency_ms_mean'], '.3f'):>8}"
        )
        if boxes:
            line += (f"{_fmt(row['bbox_hit_rate'], '.0%'):>10}"
                     f"{_fmt(row['bbox_area_frac'], '.0%'):>11}")
        lines.append(line)
    return "\n".join(lines)


def format_comparison(results: dict) -> str:
    """One overall row per localizer, e.g. {"k-NN": ..., "Scout": ...}."""
    head = (f"{'localizer':<11}{'avail':>7}{'MAE':>7}{'median':>8}{'p90':>7}"
            f"{'zone acc':>10}{'bbox hit':>10}{'bbox area':>11}{'ms/win':>8}")
    lines = [head, "-" * len(head)]
    for name, result in results.items():
        o = result["overall"]
        lines.append(
            f"{name:<11}{_fmt(o['availability'], '.0%'):>7}{_fmt(o['mae_m']):>7}"
            f"{_fmt(o['median_m']):>8}{_fmt(o['p90_m']):>7}"
            f"{_fmt(o['zone_accuracy'], '.0%'):>10}{_fmt(o['bbox_hit_rate'], '.0%'):>10}"
            f"{_fmt(o['bbox_area_frac'], '.0%'):>11}{_fmt(o['latency_ms_mean'], '.3f'):>8}"
        )
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        prog="gateway.evaluate", description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--sim", type=Path, default=Path("sim_data"),
                    help="directory holding calibration/ and test/ sessions")
    ap.add_argument("--layout", type=Path, default=Path("layouts/techhub_default.yaml"))
    ap.add_argument("--out", type=Path, default=Path("out/eval"))
    ap.add_argument("--k", type=int, default=3)
    args = ap.parse_args(argv)

    result = run_baseline(args.sim, load_layout(args.layout), args.out, k=args.k)
    print(f"k-NN baseline (k={args.k}), "
          f"{result['meta']['reference_points']} Reference points")
    print(format_table(result))
    for row in result["trials"]:
        if row["n_sufficient"] < MIN_SUFFICIENT_WINDOWS:
            print(f"warning: {row['id']} has {row['n_sufficient']} sufficient windows "
                  f"(ADR-0003 needs >= {MIN_SUFFICIENT_WINDOWS}; repeat the Trial)",
                  file=sys.stderr)
    print(f"\nwrote {args.out / 'baseline.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
