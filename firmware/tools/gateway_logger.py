#!/usr/bin/env python3
"""Minimal multi-anchor serial logger for the thesis data collection.

Reads CSV lines from one or more ESP32 anchors over USB serial, prepends
host arrival timestamps (used for cross-anchor window alignment, since the
anchors' own clocks are unsynchronized), and writes one CSV file per anchor.

Usage:
    python gateway_logger.py --port /dev/cu.usbserial-0001:A1 \
                             --port /dev/cu.usbserial-0002:A2 \
                             [--baud 921600] [--outdir data]

The full localization pipeline (windowing, MDN, D-CFR, particle filter)
lives elsewhere; this script only verifies and records raw captures.
"""

import argparse
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import serial

VALID_PREFIXES = ("CSI,", "STAT,")


class AnchorLogger(threading.Thread):
    def __init__(self, port: str, anchor: str, baud: int, outdir: Path):
        super().__init__(daemon=True, name=f"logger-{anchor}")
        self.port = port
        self.anchor = anchor
        self.baud = baud
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.outfile = outdir / f"{anchor}_{stamp}.csv"
        self.lines = 0
        self.skipped = 0

    def run(self):
        try:
            ser = serial.Serial(self.port, self.baud, timeout=1)
        except serial.SerialException as exc:
            print(f"[{self.anchor}] cannot open {self.port}: {exc}", file=sys.stderr)
            return

        with open(self.outfile, "w", buffering=1) as out:
            out.write("host_iso,host_ns,line\n")
            while True:
                try:
                    raw = ser.readline()
                except serial.SerialException as exc:
                    print(f"[{self.anchor}] serial error: {exc}", file=sys.stderr)
                    return
                if not raw:
                    continue
                line = raw.decode("ascii", errors="replace").strip()
                # Boot ROM output and stray log lines are expected; keep
                # only well-formed records.
                if not line.startswith(VALID_PREFIXES):
                    self.skipped += 1
                    continue
                host_iso = datetime.now(timezone.utc).isoformat()
                host_ns = time.perf_counter_ns()
                out.write(f'{host_iso},{host_ns},"{line}"\n')
                self.lines += 1


def parse_port(spec: str):
    """'/dev/cu.usbserial-0001:A1' -> (port, anchor_id)"""
    port, sep, anchor = spec.rpartition(":")
    if not sep or not port:
        raise argparse.ArgumentTypeError(
            f"expected <serial-port>:<anchor-id>, got {spec!r}")
    return port, anchor


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", action="append", required=True, type=parse_port,
                    metavar="PORT:ANCHOR", help="serial port and anchor id, repeatable")
    ap.add_argument("--baud", type=int, default=921600)
    ap.add_argument("--outdir", type=Path, default=Path("data"))
    args = ap.parse_args()

    args.outdir.mkdir(parents=True, exist_ok=True)

    loggers = [AnchorLogger(port, anchor, args.baud, args.outdir)
               for port, anchor in args.port]
    for lg in loggers:
        lg.start()
        print(f"[{lg.anchor}] {lg.port} -> {lg.outfile}")

    try:
        prev = {lg.anchor: 0 for lg in loggers}
        while True:
            time.sleep(5)
            status = []
            for lg in loggers:
                rate = (lg.lines - prev[lg.anchor]) / 5.0
                prev[lg.anchor] = lg.lines
                status.append(f"{lg.anchor}: {rate:.0f}/s ({lg.lines} total, "
                              f"{lg.skipped} skipped)")
            print(" | ".join(status))
    except KeyboardInterrupt:
        print("\nstopping.")


if __name__ == "__main__":
    main()
