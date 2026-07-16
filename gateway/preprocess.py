"""Pipeline orchestration and CLI.

    python -m gateway.preprocess --in data/ --out out/windows.jsonl \
        --devices devices.yaml --window 1.0 --min-anchors 3 --summary

Orchestration is a plain function (`run`) so tests and the future
baseline/proposed localization drivers can call it without the CLI.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

from gateway import __version__
from gateway.csi import hw_to_usable_indices, usable_subcarriers
from gateway.devices import DeviceRegistry
from gateway.features import build_window_features
from gateway.io import print_summary, summarize, write_jsonl, write_parquet
from gateway.parser import load_session
from gateway.windowing import assign_windows

DEFAULT_ANCHORS = ("A1", "A2", "A3", "A4")


@dataclass
class PreprocessConfig:
    inputs: List[Path]
    out: Path
    devices: Optional[Path] = None
    window_s: float = 1.0
    min_anchors: int = 3
    min_pkts: int = 1
    rssi_method: str = "ewma"
    ewma_alpha: float = 0.3
    csi_norm: str = "l2"
    drop_first_pos: bool = True
    fmt: str = "jsonl"
    include_csi52: bool = False
    mac_filter: List[str] = field(default_factory=list)
    anchor_ids: tuple = DEFAULT_ANCHORS


def run(cfg: PreprocessConfig) -> dict:
    """Execute the full preprocessing pipeline; returns the summary dict."""
    registry = (
        DeviceRegistry.from_file(cfg.devices) if cfg.devices else DeviceRegistry.empty()
    )

    csi_records, stat_records, stats = load_session(cfg.inputs)
    if cfg.mac_filter:
        wanted = {m.lower() for m in cfg.mac_filter}
        csi_records = [r for r in csi_records if r.mac in wanted]

    if not csi_records:
        raise SystemExit("no parsable CSI records found in input")

    rssi_params = {"alpha": cfg.ewma_alpha} if cfg.rssi_method == "ewma" else {}
    hw_indices = hw_to_usable_indices(cfg.drop_first_pos)
    t0, groups = assign_windows(csi_records, cfg.window_s)
    features = build_window_features(
        groups,
        t0,
        cfg.window_s,
        anchor_ids=cfg.anchor_ids,
        registry=registry,
        min_anchors=cfg.min_anchors,
        min_pkts=cfg.min_pkts,
        rssi_method=cfg.rssi_method,
        rssi_params=rssi_params,
        csi_norm=cfg.csi_norm,
        hw_indices=hw_indices,
    )

    meta = {
        "version": __version__,
        "inputs": [str(p) for p in cfg.inputs],
        "devices_file": str(cfg.devices) if cfg.devices else None,
        "window_s": cfg.window_s,
        "min_anchors": cfg.min_anchors,
        "min_pkts": cfg.min_pkts,
        "rssi_method": cfg.rssi_method,
        "rssi_params": rssi_params,
        "csi_norm": cfg.csi_norm,
        "drop_first_pos": cfg.drop_first_pos,
        "n_usable_subcarriers": len(usable_subcarriers(cfg.drop_first_pos)),
        "n_dcfr": len(usable_subcarriers(cfg.drop_first_pos)) - 1,
        "t0": t0,
        "anchor_ids": list(cfg.anchor_ids),
    }

    if cfg.fmt == "parquet":
        write_parquet(cfg.out, features, meta, cfg.include_csi52)
    else:
        write_jsonl(cfg.out, features, meta, cfg.include_csi52)

    return summarize(features, stats, stat_records)


def build_arg_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="gateway.preprocess",
        description="Preprocess anchor capture CSVs into windowed RSSI/D-CFR features.",
    )
    ap.add_argument("--in", dest="inputs", action="append", required=True,
                    metavar="PATH", help="capture file or directory; repeatable")
    ap.add_argument("--out", required=True, help="output file (jsonl or parquet)")
    ap.add_argument("--devices", help="authorized-device list (YAML or JSON)")
    ap.add_argument("--window", type=float, default=1.0, dest="window_s",
                    help="capture window length in seconds (default 1.0)")
    ap.add_argument("--min-anchors", type=int, default=3,
                    help="anchors required for a sufficient window (default 3)")
    ap.add_argument("--min-pkts-per-anchor", type=int, default=1, dest="min_pkts")
    ap.add_argument("--rssi-smoothing", choices=("ewma", "median", "mean"),
                    default="ewma", dest="rssi_method")
    ap.add_argument("--ewma-alpha", type=float, default=0.3)
    ap.add_argument("--csi-norm", choices=("l2", "center", "none"), default="l2")
    ap.add_argument("--keep-first-subcarrier", action="store_true",
                    help="keep subcarrier +1 (textbook 52 usable / 51 D-CFR); "
                         "default drops it as hardware-invalid (51 / 50)")
    ap.add_argument("--format", choices=("jsonl", "parquet"), default="jsonl",
                    dest="fmt")
    ap.add_argument("--include-csi52", action="store_true",
                    help="also emit the normalized median spectrum per anchor")
    ap.add_argument("--mac", action="append", default=[], dest="mac_filter",
                    help="only process this source MAC; repeatable")
    ap.add_argument("--summary", nargs="?", const="-", default=None,
                    metavar="FILE", help="print summary (optionally also write to FILE)")
    return ap


def main(argv: Optional[List[str]] = None) -> int:
    args = build_arg_parser().parse_args(argv)

    cfg = PreprocessConfig(
        inputs=[Path(p) for p in args.inputs],
        out=Path(args.out),
        devices=Path(args.devices) if args.devices else None,
        window_s=args.window_s,
        min_anchors=args.min_anchors,
        min_pkts=args.min_pkts,
        rssi_method=args.rssi_method,
        ewma_alpha=args.ewma_alpha,
        csi_norm=args.csi_norm,
        drop_first_pos=not args.keep_first_subcarrier,
        fmt=args.fmt,
        include_csi52=args.include_csi52,
        mac_filter=args.mac_filter,
    )

    try:
        summary = run(cfg)
    except SystemExit as exc:
        print(exc, file=sys.stderr)
        return 1

    if args.summary is not None:
        print_summary(summary)
        if args.summary != "-":
            import json

            with open(args.summary, "w") as fh:
                json.dump(summary, fh, indent=2)
    return 0


if __name__ == "__main__":
    sys.exit(main())
