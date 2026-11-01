"""Radio map plus calibration-quality report for a real Calibration session (#46).

    python -m gateway.calibration_report --session out/techhub/calibration \
        --out out/techhub/report --fault A1:p28,p47,p53,p57,p61

Preprocesses an imported session (gateway.session_import) with the default
settings (min_anchors = 3, -80 dBm floor), builds and saves its Radio map,
and writes report.json and report.md. The report is what the team reads to
choose between recapturing points and accepting holes, and between keeping
and moving Anchors (ADR-0003); it changes no threshold itself.

- Holes: each Reference point's sufficient-window count; < 30 is
  `below_30`, none is `empty`, and both are listed under `recapture`.
- Anchor coverage: per point and Anchor, `heard` (in >= 1 Beacon window),
  `fault` (named with --fault from the field notes), or `out_of_range`.
  Faults are not inferred: the Relay forwards no STAT lines, and a far
  Anchor's traffic can be as thin as a faulted one's. An Anchor whose
  Capture holds < 10 % of its median Records per point is marked
  `low_traffic` as a hint to check the notes.
- Sniper eligibility: the above-floor rate over heard (window, Anchor)
  pairs, and the share of Beacon windows with >= min_anchors Anchors above
  the floor, which bounds how often the Sniper can run.
- Distance fit: Pearson r between each heard (point, Anchor)'s median
  Beacon RSSI and log10 of its surveyed distance. Strongly negative r says
  the Reference point positions (the walk order) match the data.
- Day boundary: the session is split into days at gaps > 6 h. Per day,
  its first and last Beacon Record and how often each Anchor heard the
  Beacon (share of the day's Beacon windows); and, for every
  ambient transmitter heard >= 50 times by an Anchor on both sides, the
  change in its median RSSI. Only a device that sits still separates drift
  from movement: a locally administered (randomized) MAC is usually a phone
  and is marked `random_mac`.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Sequence

import numpy as np

from gateway.evaluate import MIN_SUFFICIENT_WINDOWS, preprocess_session
from gateway.parser import iter_logged_records
from gateway.preprocess import DEFAULT_MIN_ANCHORS
from gateway.radiomap import build_radio_map
from gateway.records import CsiRecord, ParseStats
from gateway.trials import placed_device, windows_by_trial

LOW_TRAFFIC_FRAC = 0.1
DAY_GAP_S = 6 * 3600.0
MIN_DRIFT_RECORDS = 50


def scan_captures(session_dir: Path, truth: dict) -> dict:
    """Per point and Anchor: total CSI Records in its Capture, and the RSSI
    of every non-Beacon Record keyed by MAC (the drift check's input)."""
    records: Dict[str, Dict[str, int]] = {}
    ambient: Dict[str, Dict[str, Dict[str, List[int]]]] = {}
    for trial in truth["trials"]:
        beacon = placed_device(trial)["mac"].lower()
        records[trial["id"]], ambient[trial["id"]] = {}, {}
        for path in sorted((Path(session_dir) / trial["id"]).glob("*.csv")):
            n, by_mac, anchor = 0, {}, None
            for rec in iter_logged_records(path, ParseStats()):
                if not isinstance(rec, CsiRecord):
                    continue
                n, anchor = n + 1, rec.anchor
                mac = rec.mac.lower()
                if mac != beacon:
                    by_mac.setdefault(mac, []).append(rec.rssi)
            if anchor is not None:
                records[trial["id"]][anchor] = n
                ambient[trial["id"]][anchor] = by_mac
    return {"records": records, "ambient_rssi": ambient}


def _days(trials: List[dict]) -> List[List[str]]:
    ordered = sorted(trials, key=lambda t: t["t_start"])
    days = [[ordered[0]["id"]]]
    for prev, cur in zip(ordered, ordered[1:]):
        if cur["t_start"] - prev["t_end"] > DAY_GAP_S:
            days.append([])
        days[-1].append(cur["id"])
    return days


def _day_summary(points: List[str], truth: dict, by_trial: Dict[str, List[dict]],
                 anchor_ids: List[str]) -> dict:
    trials = {t["id"]: t for t in truth["trials"]}
    ws = [w for p in points for w in by_trial[p]]
    return {
        "points": points,
        "start": min(trials[p].get("beacon_first", trials[p]["t_start"]) for p in points),
        "end": max(trials[p].get("beacon_last", trials[p]["t_end"]) for p in points),
        "hear_rate": {a: (sum(1 for w in ws if w["anchors"].get(a)) / len(ws)
                          if ws else None) for a in anchor_ids},
    }


def _distance_fit(points: Dict[str, dict], anchor_xy: Optional[dict]) -> Optional[dict]:
    if not anchor_xy:
        return None
    log_d, rssi = [], []
    for p in points.values():
        for a, cell in p["anchors"].items():
            if cell["median_rssi"] is None or a not in anchor_xy:
                continue
            ax, ay = anchor_xy[a]
            log_d.append(np.log10(max(np.hypot(p["x"] - ax, p["y"] - ay), 0.1)))
            rssi.append(cell["median_rssi"])
    if len(rssi) < 3:
        return None
    return {"r": float(np.corrcoef(log_d, rssi)[0, 1]), "n_pairs": len(rssi)}


def _random_mac(mac: str) -> bool:
    """Locally administered bit set: a randomized MAC, usually a phone."""
    return bool(int(mac.split(":")[0], 16) & 0x02)


def _drift(days: List[List[str]], ambient: dict) -> List[dict]:
    rows = []
    for i, (day_a, day_b) in enumerate(zip(days, days[1:])):
        def pooled(points):
            out: Dict[tuple, List[int]] = {}
            for p in points:
                for anchor, by_mac in ambient.get(p, {}).items():
                    for mac, values in by_mac.items():
                        out.setdefault((anchor, mac), []).extend(values)
            return out
        a, b = pooled(day_a), pooled(day_b)
        for key in sorted(set(a) & set(b)):
            if len(a[key]) < MIN_DRIFT_RECORDS or len(b[key]) < MIN_DRIFT_RECORDS:
                continue
            med_a, med_b = statistics.median(a[key]), statistics.median(b[key])
            rows.append({"days": [i, i + 1], "anchor": key[0], "mac": key[1],
                         "random_mac": _random_mac(key[1]),
                         "median_a": med_a, "median_b": med_b,
                         "delta_db": med_b - med_a,
                         "n_a": len(a[key]), "n_b": len(b[key])})
    return rows


def calibration_report(
    windows: List[dict],
    truth: dict,
    traffic: dict,
    faults: Optional[Dict[str, Sequence[str]]] = None,
    min_anchors: int = DEFAULT_MIN_ANCHORS,
) -> dict:
    """The four-part report (module docstring) as a JSON-ready dict."""
    faults = {a: set(ps) for a, ps in (faults or {}).items()}
    by_trial = windows_by_trial(windows, truth)
    anchor_ids = sorted({a for w in windows for a in w["anchors"]})
    median_records = {
        a: statistics.median([r.get(a, 0) for r in traffic["records"].values()])
        for a in anchor_ids
    }

    points, recapture = {}, []
    heard_pairs = above_pairs = eligible = n_windows = 0
    for trial in truth["trials"]:
        tid, ws = trial["id"], by_trial[trial["id"]]
        n_sufficient = sum(1 for w in ws if w["sufficient"])
        hole = "empty" if n_sufficient == 0 else (
            "below_30" if n_sufficient < MIN_SUFFICIENT_WINDOWS else None)
        if hole:
            recapture.append(tid)
        anchors = {}
        for a in anchor_ids:
            obs = [w["anchors"][a] for w in ws if w["anchors"].get(a)]
            above = sum(1 for o in obs if o["above_floor"])
            heard_pairs, above_pairs = heard_pairs + len(obs), above_pairs + above
            status = ("fault" if tid in faults.get(a, ()) else
                      "heard" if obs else "out_of_range")
            records = traffic["records"].get(tid, {}).get(a, 0)
            anchors[a] = {
                "status": status,
                "windows_heard": len(obs),
                "median_rssi": statistics.median(o["rssi"] for o in obs) if obs else None,
                "above_floor_rate": above / len(obs) if obs else None,
                "records": records,
                "low_traffic": records < LOW_TRAFFIC_FRAC * median_records[a],
            }
        n_windows += len(ws)
        eligible += sum(
            1 for w in ws
            if sum(1 for o in w["anchors"].values() if o and o["above_floor"]) >= min_anchors
        )
        device = placed_device(trial)
        points[tid] = {"x": device["x"], "y": device["y"], "n_windows": len(ws),
                       "n_sufficient": n_sufficient, "hole": hole, "anchors": anchors}

    days = _days(truth["trials"])
    return {
        "points": points,
        "recapture": recapture,
        "above_floor": {
            "rate": above_pairs / heard_pairs if heard_pairs else None,
            "sniper_eligible_rate": eligible / n_windows if n_windows else None,
            "min_anchors": min_anchors,
        },
        "faults": {a: sorted(ps) for a, ps in faults.items()},
        "distance_fit": _distance_fit(points, truth.get("anchors")),
        "drift": {"days": [_day_summary(d, truth, by_trial, anchor_ids) for d in days],
                  "rows": _drift(days, traffic["ambient_rssi"])},
    }


def _pct(v: Optional[float]) -> str:
    if v is None:
        return "-"
    return f"{100 * v:.1f}%" if 0 < v < 0.01 else f"{100 * v:.0f}%"


def format_markdown(report: dict, title: str) -> str:
    floor = report["above_floor"]
    anchors = sorted(next(iter(report["points"].values()))["anchors"])
    lines = [
        f"# {title}", "",
        f"- Reference points: {len(report['points'])}",
        f"- Need recapture (< {MIN_SUFFICIENT_WINDOWS} sufficient windows): "
        f"{', '.join(report['recapture']) or 'none'}",
        f"- Above-floor rate (heard window x Anchor pairs): {_pct(floor['rate'])}",
        f"- Beacon windows with >= {floor['min_anchors']} Anchors above the floor "
        f"(Sniper can run): {_pct(floor['sniper_eligible_rate'])}",
        "- Median Beacon RSSI vs log10 distance to the Anchor: " + (
            f"r = {report['distance_fit']['r']:.2f} over "
            f"{report['distance_fit']['n_pairs']} heard (point, Anchor) pairs"
            if report.get("distance_fit") else "no Anchor positions"),
        "- Field-noted faults (from the field notes, not inferred from the data): "
        + (", ".join(f"{a} at {', '.join(ps)}" for a, ps in report["faults"].items())
           or "none"),
        "", "Cells: median Beacon RSSI (above-floor share); `range` = not heard, "
        "`FAULT` = field-noted fault, `*` = low traffic.", "",
        "| point | x, y | sufficient | hole | " + " | ".join(anchors) + " |",
        "|---|---|---|---|" + "---|" * len(anchors),
    ]
    for pid, p in report["points"].items():
        cells = []
        for a in anchors:
            c = p["anchors"][a]
            if c["status"] == "heard":
                text = f"{c['median_rssi']:.0f} ({_pct(c['above_floor_rate'])})"
            else:
                text = {"fault": "FAULT", "out_of_range": "range"}[c["status"]]
            cells.append(text + ("*" if c["low_traffic"] else ""))
        lines.append(f"| {pid} | {p['x']:g}, {p['y']:g} | {p['n_sufficient']} | "
                     f"{p['hole'] or ''} | " + " | ".join(cells) + " |")
    drift = report["drift"]
    lines += ["", "## Day boundary", "",
              "Times are the first and last Beacon Record, in this machine's local "
              "time. Hear rate: share of the day's Beacon windows in which the "
              "Anchor heard the Beacon.", "",
              "| day | points | from | to | " + " | ".join(anchors) + " |",
              "|---|---|---|---|" + "---|" * len(anchors)]
    for i, d in enumerate(drift["days"]):
        start, end = datetime.fromtimestamp(d["start"]), datetime.fromtimestamp(d["end"])
        lines.append(f"| {i + 1} | {d['points'][0]}-{d['points'][-1]} | "
                     f"{start:%Y-%m-%d %H:%M} | {end:%H:%M} | "
                     + " | ".join(_pct(d["hear_rate"][a]) for a in anchors) + " |")
    lines.append("")
    if drift["rows"]:
        lines += ["`(random)` = randomized MAC, likely a phone that moved; "
                  "only the others measure drift.", "",
                  "| Anchor | ambient MAC | median before | median after | change dB | n |",
                  "|---|---|---|---|---|---|"]
        lines += [f"| {r['anchor']} | {r['mac']}{' (random)' if r['random_mac'] else ''} | "
                  f"{r['median_a']:.1f} | "
                  f"{r['median_b']:.1f} | {r['delta_db']:+.1f} | {r['n_a']}/{r['n_b']} |"
                  for r in drift["rows"]]
    else:
        lines.append(f"No ambient device heard >= {MIN_DRIFT_RECORDS} times on both sides.")
    return "\n".join(lines) + "\n"


def parse_fault(spec: str) -> tuple:
    """`A1:p28,p47` -> ("A1", ["p28", "p47"])."""
    anchor, _, points = spec.partition(":")
    if not anchor or not points:
        raise argparse.ArgumentTypeError(f"expected ANCHOR:p1,p2,... got {spec!r}")
    return anchor, [p for p in points.split(",") if p]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        prog="gateway.calibration_report", description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--session", required=True, type=Path,
                    help="imported session folder holding ground_truth.json")
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--fault", action="append", default=[], type=parse_fault,
                    help="field-noted Anchor fault, e.g. A1:p28,p47; repeatable")
    args = ap.parse_args(argv)

    args.out.mkdir(parents=True, exist_ok=True)
    meta, windows, truth = preprocess_session(args.session, args.out / "windows.jsonl")
    build_radio_map(windows, meta, truth).save(args.out / "radio_map.json")
    faults: Dict[str, List[str]] = {}
    for anchor, pts in args.fault:
        faults.setdefault(anchor, []).extend(pts)
    report = calibration_report(
        windows, truth, scan_captures(args.session, truth), faults,
        min_anchors=meta.get("min_anchors", DEFAULT_MIN_ANCHORS))
    with open(args.out / "report.json", "w") as fh:
        json.dump(report, fh, indent=2)
    md = format_markdown(report, f"Calibration report: {args.session}")
    (args.out / "report.md").write_text(md)
    print(md)
    return 0


if __name__ == "__main__":
    sys.exit(main())
