"""Live point checker for a Calibration session (#50).

    make check-point                          # newest `make listen` session in data/
    python -m gateway.check_point --data data --layout layouts/techhub_trial_4p8.yaml
    python -m gateway.check_point --data out/techhub/calibration/p56 --once   # replay a point

While the Beacon sits on a Reference point, tails the newest Capture of every
Anchor (as `make listen` writes them) and every few seconds prints, per
Anchor, how often it heard the Beacon, its median RSSI and how often it was
above the Sniper's floor, then a verdict:

- GOOD: >= 3 Anchors strong, >= 30 sufficient windows and the full
  recording (30 s settle + 4 min kept) done: move to the next point.
- KEEP RECORDING: strong enough, but not yet recorded long enough.
- WEAK: fewer than 3 Anchors strong; the Sniper cannot run here (k-NN and
  the Scout still can). Check the Anchors and antennas, then note it.
- NO BEACON: no Beacon Records at all.

It reuses the preprocessing (1 s windows, EWMA-smoothed RSSI, -80 dBm floor,
min_anchors) and the import's trim, so its verdict matches what
`calibration-report` later says about the point. An Anchor is strong when
it is above the floor in more than half of the Beacon windows: the Sniper
needs 3 Anchors above the floor in the same window, so an Anchor that is
loud but mostly silent does not count. (The report's coverage figure
counts only the windows an Anchor heard; the two differ at pilot point
p56 only.) The median is over the heard windows. Strength is judged over the last `--span`
seconds (default 30) so a change shows within half a minute; sufficient
windows are counted over the kept part of the recording.

Plain Python, plain ASCII output: runs the same on Windows.
"""

from __future__ import annotations

import argparse
import csv
import os
import re
import statistics
import sys
import time
from datetime import datetime
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Sequence

from gateway.devices import DeviceRegistry
from gateway.evaluate import MIN_SUFFICIENT_WINDOWS
from gateway.features import build_window_features
from gateway.parser import LEGACY_HEADER, parse_logged_row
from gateway.preprocess import PreprocessConfig
from gateway.records import CsiRecord, ParseStats
from gateway.session_import import DEFAULT_TRIM
from gateway.sim import load_layout
from gateway.windowing import assign_windows, is_sufficient

# The pipeline's defaults, read from its own config so the two stay in step.
PIPELINE = PreprocessConfig(inputs=[], out=Path("unused"))
SPAN_S = 30.0
DEFAULT_LAYOUT = Path("layouts/techhub_trial_4p8.yaml")
EVERY_S = 3.0
CAPTURE_NAME = re.compile(r"^(A\d+)_(.+)\.csv$")  # make listen: <Anchor>_<stamp>.csv


@dataclass
class AnchorCheck:
    anchor: str
    windows: int                 # Beacon windows in the span
    windows_heard: int           # ... in which this Anchor heard the Beacon
    median_rssi: Optional[float]
    above_share: Optional[float]  # share of the span's Beacon windows above the floor
    strong: bool


@dataclass
class PointCheck:
    state: str
    anchors: List[AnchorCheck]
    n_strong: int
    sufficient: int
    elapsed_s: float
    beacon_mac: str


def assess(
    records: Sequence[CsiRecord],
    beacon_mac: str,
    anchor_ids: Sequence[str],
    now: Optional[float] = None,
    span_s: Optional[float] = SPAN_S,
) -> PointCheck:
    """The verdict for one point from its Records so far. `now` defaults to
    the newest Record; `span_s=None` judges strength over the whole kept
    recording instead of the last `span_s` seconds."""
    records = [r for r in records if isinstance(r, CsiRecord)]
    beacon_mac = beacon_mac.lower()
    beacon = [r for r in records if r.mac.lower() == beacon_mac]
    if not records:
        return PointCheck("NO BEACON", [AnchorCheck(a, 0, 0, None, None, False)
                                        for a in anchor_ids], 0, 0, 0.0, beacon_mac)
    t_start = min(r.t_host for r in records)
    now = max(r.t_host for r in records) if now is None else now
    # Like the import, the settle and the kept 4 min run from the Beacon's
    # first Record (the recording timer from the first Record of any kind).
    t_beacon = min((r.t_host for r in beacon), default=t_start)
    skip_s, keep_s = DEFAULT_TRIM
    kept_lo, kept_hi = t_beacon + skip_s, t_beacon + skip_s + keep_s

    kept = [r for r in beacon if kept_lo <= r.t_host < kept_hi and r.t_host <= now]
    _, groups = assign_windows(kept, PIPELINE.window_s, t0=t_beacon)
    sufficient = sum(1 for per_anchor in groups.values()
                     if is_sufficient(per_anchor, PIPELINE.min_anchors, PIPELINE.min_pkts))

    if span_s is None:
        span = kept
    else:
        span = [r for r in beacon if now - span_s < r.t_host <= now]
    _, groups = assign_windows(span, PIPELINE.window_s, t0=t_beacon)
    windows = build_window_features(
        groups, t_beacon, PIPELINE.window_s, anchor_ids, DeviceRegistry.empty(),
        min_anchors=PIPELINE.min_anchors, min_pkts=PIPELINE.min_pkts,
        rssi_method=PIPELINE.rssi_method, rssi_params={"alpha": PIPELINE.ewma_alpha},
        rssi_floor=PIPELINE.rssi_floor_dbm,
    )
    anchors = []
    for a in anchor_ids:
        heard = [w.anchors[a] for w in windows if w.anchors.get(a) is not None]
        share = sum(f.above_floor for f in heard) / len(windows) if windows else None
        anchors.append(AnchorCheck(
            anchor=a, windows=len(windows), windows_heard=len(heard),
            median_rssi=statistics.median(f.rssi for f in heard) if heard else None,
            above_share=share, strong=share is not None and share > 0.5,
        ))
    n_strong = sum(a.strong for a in anchors)
    if not beacon:
        state = "NO BEACON"
    elif n_strong < PIPELINE.min_anchors:
        state = "WEAK"
    elif now < kept_hi or sufficient < MIN_SUFFICIENT_WINDOWS:
        state = "KEEP RECORDING"
    else:
        state = "GOOD"
    return PointCheck(state, anchors, n_strong, sufficient, now - t_start, beacon_mac)


# --- following the listener's files -------------------------------------------


class _CaptureTail:
    """One Capture file read as it grows. Bytes, not text mode: a row the
    listener is still writing stays buffered until its newline arrives, and
    byte offsets behave the same on Windows."""

    def __init__(self, path: Path):
        self.path, self.offset, self.partial = path, 0, b""
        self.legacy, self.stats = False, ParseStats()

    def read_new(self) -> List[CsiRecord]:
        with open(self.path, "rb") as fh:
            fh.seek(self.offset)
            chunk = fh.read()
        self.offset += len(chunk)
        *lines, self.partial = (self.partial + chunk).split(b"\n")
        out = []
        for raw in lines:
            text = raw.decode("utf-8-sig", errors="replace").rstrip("\r")
            row = next(csv.reader([text]), None)
            if not row:
                continue
            if row[0] == "host_iso":
                self.legacy = row == LEGACY_HEADER
                continue
            rec = parse_logged_row(row, self.stats, self.legacy)
            if isinstance(rec, CsiRecord):
                out.append(rec)
        return out


class SessionTail:
    """The newest `make listen` session in a folder: every Anchor's Capture
    with the newest file's stamp. A newer stamp means a new point, so the
    Records gathered so far are dropped."""

    def __init__(self, data_dir: Path):
        self.data_dir = Path(data_dir)
        self.stamp: Optional[str] = None
        self.tails: Dict[Path, _CaptureTail] = {}
        self.records: List[CsiRecord] = []

    def _captures(self) -> List[Path]:
        return [p for p in self.data_dir.glob("A*_*.csv") if CAPTURE_NAME.match(p.name)]

    def poll(self) -> List[CsiRecord]:
        """All Records of the current session, after reading what was appended."""
        files = self._captures()
        if files:
            newest = max(files, key=lambda p: p.stat().st_mtime)
            stamp = CAPTURE_NAME.match(newest.name).group(2)
            if stamp != self.stamp:
                self.stamp, self.tails, self.records = stamp, {}, []
            for p in files:
                if CAPTURE_NAME.match(p.name).group(2) == self.stamp and p not in self.tails:
                    self.tails[p] = _CaptureTail(p)
        for tail in self.tails.values():
            self.records.extend(tail.read_new())
        return self.records


# --- output and command -------------------------------------------------------


def _mmss(seconds: float) -> str:
    seconds = max(0, int(seconds))
    return f"{seconds // 60}:{seconds % 60:02d}"


ADVICE = {
    "GOOD": "move to the next point.",
    "KEEP RECORDING": "keep the Beacon here.",
    "WEAK": "the Sniper cannot run here (k-NN and the Scout still can). Check the "
            "weak Anchors and antennas; if nothing helps, finish the point and note it.",
    "NO BEACON": "no Beacon Records: is the Beacon on, and is `make listen` receiving?",
}


def format_check(check: PointCheck, span_s: Optional[float]) -> str:
    """The checker's screen: one row per Anchor, then the verdict. ASCII only."""
    floor = PIPELINE.rssi_floor_dbm
    full = DEFAULT_TRIM[0] + DEFAULT_TRIM[1]
    over = f"last {span_s:g} s" if span_s else "whole kept recording"
    lines = [
        f"Point check  {datetime.now():%H:%M:%S}  recording {_mmss(check.elapsed_s)} "
        f"of {_mmss(full)}  Beacon {check.beacon_mac}  ({over})",
        "",
        f"{'Anchor':<7}{'heard':>7}{'median':>10}{'above ' + format(floor, 'g'):>11}  status",
    ]
    for a in check.anchors:
        if a.windows_heard == 0:
            lines.append(f"{a.anchor:<7}{'0 %':>7}{'-':>10}{'-':>11}  not heard")
            continue
        heard = f"{100 * a.windows_heard / a.windows:.0f} %"
        median = f"{a.median_rssi:.0f} dBm"
        above = f"{100 * a.above_share:.0f} %"
        lines.append(f"{a.anchor:<7}{heard:>7}{median:>10}{above:>11}  "
                     f"{'strong' if a.strong else 'weak'}")
    lines += [
        "",
        f"{check.state}: {check.n_strong}/{len(check.anchors)} Anchors strong "
        f"(the Sniper needs {PIPELINE.min_anchors}); sufficient windows "
        f"{check.sufficient} (need {MIN_SUFFICIENT_WINDOWS}).",
        f"-> {ADVICE[check.state]}",
    ]
    return "\n".join(lines)


def _beacon_mac(layout) -> str:
    for device in layout.devices.values():
        if device.role == "beacon":
            return device.mac
    raise SystemExit(f"{layout.path} has no device with role: beacon; pass --beacon")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        prog="gateway.check_point", description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--data", type=Path, default=Path("data"),
                    help="folder `make listen` writes to (default data)")
    ap.add_argument("--layout", type=Path, default=DEFAULT_LAYOUT,
                    help="layout naming the Anchors and the Beacon")
    ap.add_argument("--beacon", help="Beacon MAC (default: the layout's beacon)")
    ap.add_argument("--span", type=float, default=SPAN_S,
                    help="seconds of recent data to judge strength over (0: whole recording)")
    ap.add_argument("--every", type=float, default=EVERY_S, help="seconds between updates")
    ap.add_argument("--once", action="store_true",
                    help="read what is there, print one verdict and stop (replay a point)")
    ap.add_argument("--no-clear", action="store_true", help="don't clear the screen")
    args = ap.parse_args(argv)

    layout = load_layout(args.layout)
    beacon = args.beacon or _beacon_mac(layout)
    anchors = sorted(layout.anchors)
    span = args.span or None
    tail = SessionTail(args.data)
    if args.once:
        print(format_check(assess(tail.poll(), beacon, anchors, span_s=span), span))
        return 0
    clear = sys.stdout.isatty() and not args.no_clear
    try:
        while True:
            records = tail.poll()
            if clear:
                os.system("cls" if os.name == "nt" else "clear")
            if not records:
                print(f"Waiting for `make listen` Captures in {args.data} ... (Ctrl+C stops)",
                      flush=True)
            else:
                print(format_check(assess(records, beacon, anchors, now=time.time(),
                                          span_s=span), span))
                print(f"\nPoint session {tail.stamp}. Ctrl+C stops.", flush=True)
            if not clear:
                print("-" * 72, flush=True)
            time.sleep(args.every)
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    sys.exit(main())
