#!/usr/bin/env python3
"""Single-port ESP-NOW Gateway logger with active Heartbeat monitoring and real-time packet alerts."""

import argparse
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
import socket
import serial

VALID_PREFIXES = ("CSI,", "STAT,", "HEARTBEAT,")

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", type=str, default="/dev/ttyUSB0", help="Gateway serial port (e.g., /dev/ttyUSB0 or /dev/ttyACM0)")
    ap.add_argument("--baud", type=int, default=921600)
    ap.add_argument("--outdir", type=Path, default=Path("data"))
    ap.add_argument("--verbose", action="store_true", help="Print every received packet")
    args = ap.parse_args()

    args.outdir.mkdir(parents=True, exist_ok=True)

    try:
        ser = serial.Serial(args.port, args.baud, timeout=1)
    except serial.SerialException as exc:
        print(f"[Gateway] Cannot open {args.port}: {exc}", file=sys.stderr)
        return

    print("==================================================")
    print(f"[Gateway] Connected to {args.port} at {args.baud} baud")
    print(f"[Gateway] Saving output files into: {args.outdir.absolute()}")
    print("==================================================\n")

    active_files = {}   
    udp_sockets = {}   
    anchor_lines = {}   
    anchor_skipped = 0  
    prev_counts = {}   

    session_stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    sock_global = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    try:
        last_print = time.time()
        while True:
            raw = ser.readline()
            if not raw:
                continue
                
            line = raw.decode("ascii", errors="replace").strip()
            if not line.startswith(VALID_PREFIXES):
                anchor_skipped += 1
                continue

            # --- HEARTBEAT HANDLER ---
            if line.startswith("HEARTBEAT,"):
                if args.verbose:
                    uptime_ms = line.split(",")[1]
                    sys.stdout.write(f"\r[Heartbeat] Pi <-> Gateway USB active (Uptime: {int(uptime_ms)//1000}s)")
                    sys.stdout.flush()
                continue

            # --- CSI / STAT HANDLER ---
            # Do a basic split just to get the anchor ID and MAC for printing
            basic_parts = line.split(',', 4)
            if len(basic_parts) < 2:
                continue
            anchor = basic_parts[1]

            host_iso = datetime.now(timezone.utc).isoformat()
            host_ns = time.perf_counter_ns()

            # Initialize anchor file on first arrival
            if anchor not in active_files:
                outfile = args.outdir / f"{anchor}_{session_stamp}.csv"
                f = open(outfile, "w", buffering=1)
                
                # Header now accurately reflects 'csi_payload' as a single column
                f.write("host_iso,host_ns,type,anchor_id,seq,mac,rssi,channel,len,csi_payload\n")
                active_files[anchor] = f
                anchor_lines[anchor] = 0
                prev_counts[anchor] = 0

                try:
                    anchor_num = int(''.join(filter(str.isdigit, anchor)))
                    udp_port = 6000 + anchor_num
                except ValueError:
                    udp_port = 6001
                udp_sockets[anchor] = udp_port

                print(f"\n[WIRELESS LINK ESTABLISHED] Discovered Anchor [{anchor}] -> {outfile.name} | UDP {udp_port}\n")

            # --- SINGLE CELL FORMATTING LOGIC ---
            if line.startswith("CSI,"):
                # Split only 7 times. Everything after the 7th comma stays grouped in parts[7]
                parts = line.split(',', 7)
                if len(parts) == 8:
                    meta = ",".join(parts[:7])
                    payload = parts[7]
                    
                    # Write metadata normally, but wrap the payload in double quotes
                    csv_line = f'{host_iso},{host_ns},{meta},"{payload}"\n'
                else:
                    csv_line = f'{host_iso},{host_ns},{line}\n'
            else:
                # Handle non-CSI lines normally
                csv_line = f'{host_iso},{host_ns},{line}\n'

            # Save line to CSV
            active_files[anchor].write(csv_line)
            anchor_lines[anchor] += 1

            # Verbose mode packet output
            if args.verbose and line.startswith("CSI,"):
                seq_num = basic_parts[2] if len(basic_parts) > 2 else "?"
                mac_addr = basic_parts[3] if len(basic_parts) > 3 else "?"
                rssi = basic_parts[4] if len(basic_parts) > 4 else "?"
                print(f"[WIRELESS RECV] Anchor {anchor} | Seq #{seq_num} | From MAC: {mac_addr} | RSSI: {rssi} dBm")

            # Send via UDP to MATLAB (Leaving this as the raw line so MATLAB logic doesn't break)
            udp_payload = f"{anchor}|{line}"
            try:
                sock_global.sendto(udp_payload.encode('ascii'), ('127.0.0.1', udp_sockets[anchor]))
            except Exception:
                pass

            # Summary stats every 5s
            now = time.time()
            if now - last_print >= 5.0:
                status = []
                for anc, total in anchor_lines.items():
                    rate = (total - prev_counts[anc]) / 5.0
                    prev_counts[anc] = total
                    status.append(f"{anc}: {rate:.0f} pkts/s ({total} total)")
                if status:
                    print(f"\n--- [STAT SUMMARY] " + " | ".join(status) + f" (Skipped noise: {anchor_skipped}) ---")
                last_print = now

    except KeyboardInterrupt:
        print("\nStopping logger. Closing all anchor files...")
    finally:
        ser.close()
        sock_global.close()
        for f in active_files.values():
            f.close()
        print("Exited cleanly.")

if __name__ == "__main__":
    main()
