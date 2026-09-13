#!/usr/bin/env python3
"""Anchor hardware acceptance check.

Sanity-checks a replacement/new anchor board (e.g. after losing or
breaking one, or trying a different ESP32 batch) by running its capture
file(s) through gateway.parser and printing a pass/fail parse summary plus
a sample of RSSI/CSI values, side by side with one or more known-good
anchors' captures from the same side-by-side session.

This is a hardware acceptance check, not a pipeline stage, so it lives
here rather than in gateway.preprocess. It imports the gateway package
directly, so run it with that package's venv active:

    source .venv/bin/activate   # repo root
    python firmware/tools/anchor_hw_check.py \\
        data/A1_20260914_101500.csv data/A_NEW_20260914_101500.csv

PASS means every line in the file parsed cleanly (zero malformed/skipped)
and at least one CSI packet was recorded. It does not compare RSSI/CSI
values numerically between anchors — unit-to-unit calibration variance is
normal — the printed samples are for a human eyeball comparison only.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from gateway.csi import remap_hw64_to_usable  # noqa: E402
from gateway.parser import load_session  # noqa: E402


def check_one(path: str, n_sample: int) -> bool:
    csi, stat, stats = load_session([path])
    anchors = sorted({r.anchor for r in csi} | {r.anchor for r in stat})
    label = ",".join(anchors) if anchors else "(no anchor id seen)"
    passed = stats.malformed == 0 and stats.csi > 0

    print(f"\n=== {path}  [anchor(s): {label}] ===")
    print(
        f"  rows={stats.total_rows}  csi={stats.csi}  stat={stats.stat}  "
        f"malformed={stats.malformed}  ignored={stats.ignored_prefix}"
    )
    if stats.malformed:
        print(f"  malformed examples: {stats.malformed_examples}")
    if len(anchors) > 1:
        print(f"  NOTE: multiple anchor ids in one file ({anchors}) — expected one per capture file")

    if csi:
        print(f"  sample of first {n_sample} CSI packets (usable subcarriers, first 6 shown):")
        for rec in csi[:n_sample]:
            usable = remap_hw64_to_usable(rec.amps_hw)
            print(
                f"    anchor={rec.anchor} mac={rec.mac} rssi={rec.rssi} ch={rec.channel} "
                f"usable[:6]={np.round(usable[:6], 1).tolist()}"
            )
    else:
        print("  no CSI records parsed")

    print(f"  -> {'PASS' if passed else 'FAIL'}")
    return passed


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "captures",
        nargs="+",
        help="capture CSV file(s), one per anchor, from the same side-by-side session",
    )
    parser.add_argument(
        "--n-sample", type=int, default=5, help="CSI packets to print per anchor for eyeballing (default: 5)"
    )
    args = parser.parse_args()

    results = [check_one(path, args.n_sample) for path in args.captures]

    print(f"\n{'ALL PASS' if all(results) else 'AT LEAST ONE FAIL'}")
    sys.exit(0 if all(results) else 1)


if __name__ == "__main__":
    main()
