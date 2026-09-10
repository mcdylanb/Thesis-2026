#!/usr/bin/env python3
"""Gateway-side UDP listener for the Relay's forwarded ASCII line stream.

Binds a UDP socket on the Gateway's known static IP/port (the address the
Relay is configured to send to) and lands the same ``CSI,.../STAT,...``
lines the Relay already forwards as per-anchor ``data/<anchor>_<timestamp>.csv``
files, in the exact ``host_iso,host_ns,line`` format
``gateway.parser.iter_logged_records`` already expects.
"""

from __future__ import annotations

import argparse
import socket
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Dict, TextIO

VALID_PREFIXES = ("CSI,", "STAT,", "HEARTBEAT,")


@dataclass
class ListenerStats:
    lines: int = 0
    heartbeats: int = 0
    skipped: int = 0


def format_logged_row(host_iso: str, host_ns: int, line: str) -> str:
    return f'{host_iso},{host_ns},"{line}"\n'


def handle_line(
    anchor_files: Dict[str, TextIO],
    raw_line: str,
    host_iso: str,
    host_ns: int,
    stats: ListenerStats,
    open_anchor_file: Callable[[str], TextIO],
) -> None:
    """Route one decoded line to its anchor's capture file.

    Mirrors the existing loggers' capture-time policy: only a prefix check
    happens here, never full field validation (that's ``gateway.parser``'s
    job at preprocess time) - so a malformed-but-prefixed line still lands
    in the file for later inspection, matching gateway_logger.py.
    """
    line = raw_line.strip()
    if not line.startswith(VALID_PREFIXES):
        stats.skipped += 1
        return

    if line.startswith("HEARTBEAT,"):
        stats.heartbeats += 1
        return

    parts = line.split(",", 2)
    if len(parts) < 2 or not parts[1]:
        stats.skipped += 1
        return
    anchor = parts[1]

    f = anchor_files.get(anchor)
    if f is None:
        f = open_anchor_file(anchor)
        f.write("host_iso,host_ns,line\n")
        anchor_files[anchor] = f

    f.write(format_logged_row(host_iso, host_ns, line))
    stats.lines += 1


def _now() -> tuple[str, int]:
    return datetime.now(timezone.utc).isoformat(), time.perf_counter_ns()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--bind-ip", default="0.0.0.0", help="Gateway IP to bind (the Relay's configured GATEWAY_IP)")
    ap.add_argument("--port", type=int, default=5555, help="Gateway UDP port (the Relay's configured GATEWAY_PORT)")
    ap.add_argument("--outdir", type=Path, default=Path("data"))
    args = ap.parse_args()

    args.outdir.mkdir(parents=True, exist_ok=True)
    session_stamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind((args.bind_ip, args.port))
    print(f"[relay_udp_listener] listening on {args.bind_ip}:{args.port} -> {args.outdir}/")

    anchor_files: Dict[str, TextIO] = {}
    stats = ListenerStats()

    def open_anchor_file(anchor: str) -> TextIO:
        outfile = args.outdir / f"{anchor}_{session_stamp}.csv"
        print(f"[relay_udp_listener] new anchor {anchor} -> {outfile}")
        return open(outfile, "w", buffering=1)

    last_print = time.time()
    try:
        while True:
            raw, _addr = sock.recvfrom(4096)
            host_iso, host_ns = _now()
            line = raw.decode("ascii", errors="replace")
            handle_line(anchor_files, line, host_iso, host_ns, stats, open_anchor_file)

            now = time.time()
            if now - last_print >= 5.0:
                print(f"[relay_udp_listener] lines={stats.lines} heartbeats={stats.heartbeats} skipped={stats.skipped}")
                last_print = now
    except KeyboardInterrupt:
        print("\nstopping.")
    finally:
        sock.close()
        for f in anchor_files.values():
            f.close()


if __name__ == "__main__":
    main()
