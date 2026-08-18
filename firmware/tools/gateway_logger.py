#!/usr/bin/env python3
"""Multi-anchor serial logger with real-time localhost UDP loopback for MATLAB."""

import argparse
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
import socket  # NEW: For real-time streaming

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
        
        # NEW: Setup localhost UDP broadcasting socket
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        # Dynamically map A1 -> port 5001, A2 -> port 5002, etc.
        try:
            anchor_num = int(''.join(filter(str.isdigit, anchor)))
            self.udp_port = 6000 + anchor_num
        except ValueError:
            self.udp_port = 6001 # Fallback default

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
                if not line.startswith(VALID_PREFIXES):
                    self.skipped += 1
                    continue
                
                host_iso = datetime.now(timezone.utc).isoformat()
                host_ns = time.perf_counter_ns()
                
                # 1. Save to CSV file (Unchanged)
                out.write(f'{host_iso},{host_ns},"{line}"\n')
                
                # 2. NEW: Shoot a copy to MATLAB over local UDP network loopback
                # Format sent: "A1|CSI,A1,4616,..."
                udp_payload = f"{self.anchor}|{line}"
                try:
                    self.sock.sendto(udp_payload.encode('ascii'), ('127.0.0.1', self.udp_port))
                except Exception:
                    pass # Prevent socket drops from freezing serial collection
                
                self.lines += 1


def parse_port(spec: str):
    port, sep, anchor = spec.rpartition(":")
    if not sep or not port:
        raise argparse.ArgumentTypeError(f"expected <serial-port>:<anchor-id>, got {spec!r}")
    return port, anchor


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", action="append", required=True, type=parse_port, metavar="PORT:ANCHOR")
    ap.add_argument("--baud", type=int, default=921600)
    ap.add_argument("--outdir", type=Path, default=Path("data"))
    args = ap.parse_args()

    args.outdir.mkdir(parents=True, exist_ok=True)

    loggers = [AnchorLogger(port, anchor, args.baud, args.outdir) for port, anchor in args.port]
    for lg in loggers:
        lg.start()
        print(f"[{lg.anchor}] {lg.port} -> {lg.outfile} | Broadcasting live on UDP port {lg.udp_port}")

    try:
        prev = {lg.anchor: 0 for lg in loggers}
        while True:
            time.sleep(5)
            status = []
            for lg in loggers:
                rate = (lg.lines - prev[lg.anchor]) / 5.0
                prev[lg.anchor] = lg.lines
                status.append(f"{lg.anchor}: {rate:.0f}/s ({lg.lines} total, {lg.skipped} skipped)")
            print(" | ".join(status))
    except KeyboardInterrupt:
        print("\nstopping.")


if __name__ == "__main__":
    main()
