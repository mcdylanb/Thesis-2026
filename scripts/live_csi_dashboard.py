"""Live CSI dashboard: tails the newest Capture for one Anchor and plots it.

Python replacement for ``firmware/tools/matlab/realtime_csi_dashboard.m`` —
same two heatmaps (raw hardware-order amplitudes, and cleaned + time-smoothed
usable subcarriers) plus what the MATLAB version lacked: an RSSI trace and a
per-source-MAC frame counter, so a Capture dominated by the wrong transmitter
(e.g. the Relay's own UDP traffic) is obvious within seconds.

Reads the ``host_iso,host_ns,line`` rows that ``make listen`` / ``make capture``
write, via the same ``gateway.parser`` the preprocessing pipeline uses.

    make dashboard                 # newest data/A1_*.csv
    make dashboard ANCHOR=A2
    uv run python scripts/live_csi_dashboard.py --file data/A1_x.csv --exclude-mac 68:fe:71:fa:df:fc
    uv run python scripts/live_csi_dashboard.py --file data/A1_x.csv --snapshot out/a1.png   # figure for the thesis
    uv run python scripts/live_csi_dashboard.py --file data/A1_x.csv --from-start --replay-rate 6   # replay offline

Needs matplotlib: ``uv sync --extra viz`` (included in ``make setup``).
"""

from __future__ import annotations

import argparse
import csv
import sys
from collections import Counter, deque
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Deque, IO, Iterator, List, Optional, Tuple

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from gateway.csi import remap_hw64_to_usable, usable_subcarriers  # noqa: E402
from gateway.parser import CsiPayload, parse_firmware_line  # noqa: E402

N_HW = 64
CLIM = (0, 60)  # amplitude colour range, matches the MATLAB dashboard


def newest_capture(data_dir: Path, anchor: str) -> Optional[Path]:
    files = sorted(data_dir.glob(f"{anchor}_*.csv"), key=lambda p: p.stat().st_mtime)
    return files[-1] if files else None


def read_new_lines(fh: IO[str], limit: Optional[int] = None) -> Iterator[str]:
    """Yield complete lines appended since the last call, at most ``limit``.
    A trailing partial line (listener mid-write) is left for the next call."""
    n = 0
    while limit is None or n < limit:
        pos = fh.tell()
        line = fh.readline()
        if not line:
            return
        if not line.endswith("\n"):
            fh.seek(pos)
            return
        n += 1
        yield line


def payload_from_row(row: str) -> Optional[Tuple[CsiPayload, float]]:
    """``host_iso,host_ns,"CSI,..."`` -> (CsiPayload, t_host epoch seconds), or
    None for STAT / header / malformed rows."""
    try:
        fields = next(csv.reader([row]))
        if len(fields) != 3:
            return None
        t_host = datetime.fromisoformat(fields[0]).timestamp()
    except (csv.Error, StopIteration, ValueError):
        return None
    payload = parse_firmware_line(fields[2])
    return (payload, t_host) if isinstance(payload, CsiPayload) else None


def clean_amplitudes(amps_hw: np.ndarray) -> np.ndarray:
    """MATLAB's "dropped zeros" step on the usable subcarriers: null bins are
    replaced with the mean of the non-null ones so they don't streak the map."""
    usable = remap_hw64_to_usable(amps_hw)
    nonzero = usable != 0
    if nonzero.any() and not nonzero.all():
        usable = usable.copy()
        usable[~nonzero] = usable[nonzero].mean()
    return usable


def moving_average_rows(buf: np.ndarray, span: int) -> np.ndarray:
    """movmean(buf, span, 1): centred running mean down the time axis,
    shrinking the window at the edges."""
    if span <= 1:
        return buf
    n = buf.shape[0]
    cs = np.cumsum(np.vstack([np.zeros((1, buf.shape[1])), buf]), axis=0)
    half = span // 2
    lo = np.clip(np.arange(n) - half, 0, n)
    hi = np.clip(np.arange(n) + (span - half), 0, n)
    return (cs[hi] - cs[lo]) / (hi - lo)[:, None]


@dataclass
class DashboardState:
    """Rolling buffers behind the plots. Pure: no matplotlib, testable."""

    window: int
    smooth_span: int
    mac_filter: Optional[str] = None
    exclude_macs: frozenset = frozenset()
    raw: np.ndarray = field(init=False)
    clean: np.ndarray = field(init=False)
    rssi: Deque[int] = field(init=False)
    t_rows: Deque[float] = field(init=False)
    mac_counts: Counter = field(default_factory=Counter)
    shown: int = 0
    skipped: int = 0
    last_seq: Optional[int] = None
    seq_gaps: int = 0

    def __post_init__(self) -> None:
        self.raw = np.zeros((self.window, N_HW), dtype=np.float32)
        self.clean = np.zeros((self.window, len(usable_subcarriers())), dtype=np.float32)
        self.rssi = deque(maxlen=self.window)
        self.t_rows = deque(maxlen=self.window)

    def push(self, p: CsiPayload, t_host: float) -> bool:
        """Account the record; returns True if it entered the plot buffers."""
        self.mac_counts[p.mac] += 1
        if self.last_seq is not None and p.seq > self.last_seq + 1:
            self.seq_gaps += p.seq - self.last_seq - 1
        self.last_seq = p.seq
        if p.mac in self.exclude_macs or (self.mac_filter and p.mac != self.mac_filter):
            self.skipped += 1
            return False
        self.raw = np.roll(self.raw, -1, axis=0)
        self.raw[-1] = p.amps_hw
        self.clean = np.roll(self.clean, -1, axis=0)
        self.clean[-1] = clean_amplitudes(p.amps_hw)
        self.rssi.append(p.rssi)
        self.t_rows.append(t_host)
        self.shown += 1
        return True

    def smoothed(self) -> np.ndarray:
        return moving_average_rows(self.clean, self.smooth_span)

    def rate_hz(self, horizon_s: float = 5.0) -> float:
        if len(self.t_rows) < 2:
            return 0.0
        now = self.t_rows[-1]
        recent = [t for t in self.t_rows if now - t <= horizon_s]
        return (len(recent) - 1) / horizon_s if len(recent) > 1 else 0.0

    def top_macs(self, n: int = 6) -> List[tuple]:
        return self.mac_counts.most_common(n)


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--data", type=Path, default=Path("data"), help="Capture directory")
    ap.add_argument("--anchor", default="A1", help="Anchor whose newest Capture to tail")
    ap.add_argument("--file", type=Path, help="Explicit Capture to tail (overrides --data/--anchor)")
    ap.add_argument("--window", type=int, default=150, help="Records shown along the time axis")
    ap.add_argument("--smooth", type=int, default=9, help="Moving-average span (records)")
    ap.add_argument("--mac", help="Only plot this source MAC")
    ap.add_argument("--exclude-mac", action="append", default=[], help="Never plot this MAC (repeatable); e.g. the Relay")
    ap.add_argument("--from-start", action="store_true", help="Replay the whole file instead of only new rows")
    ap.add_argument("--replay-rate", type=int, default=0,
                    help="With --from-start: records consumed per redraw (0 = all at once). 6 at 200 ms ≈ 30/s")
    ap.add_argument("--interval-ms", type=int, default=200, help="Redraw period")
    ap.add_argument("--snapshot", type=Path, help="Replay the file, save one PNG here, exit (no window)")
    return ap


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        import matplotlib
        import matplotlib.pyplot as plt
        from matplotlib.animation import FuncAnimation
    except ImportError:
        print("matplotlib missing: run `uv sync --extra viz` (or `make setup`)", file=sys.stderr)
        return 2

    path = args.file or newest_capture(args.data, args.anchor)
    if path is None or not path.exists():
        print(f"no {args.anchor}_*.csv in {args.data}/ — start `make listen` first", file=sys.stderr)
        return 1
    print(f"tailing {path}")

    state = DashboardState(
        window=args.window,
        smooth_span=args.smooth,
        mac_filter=args.mac.lower() if args.mac else None,
        exclude_macs=frozenset(m.lower() for m in args.exclude_mac),
    )
    fh = open(path, newline="")
    if not (args.from_start or args.snapshot):
        fh.seek(0, 2)

    fig, axes = plt.subplots(2, 2, figsize=(13, 8), layout="constrained")
    fig.canvas.manager.set_window_title(f"Live CSI — {path.name}")
    ax_raw, ax_rssi, ax_clean, ax_mac = axes[0, 0], axes[0, 1], axes[1, 0], axes[1, 1]

    im_raw = ax_raw.imshow(state.raw.T, aspect="auto", origin="lower", cmap="jet",
                           vmin=CLIM[0], vmax=CLIM[1], interpolation="nearest")
    ax_raw.set_title(f"{args.anchor}: raw CSI (hardware order)")
    ax_raw.set_xlabel("record (rolling window)"); ax_raw.set_ylabel("hw index")

    sub = usable_subcarriers()
    im_clean = ax_clean.imshow(state.clean.T, aspect="auto", origin="lower", cmap="jet",
                               vmin=CLIM[0], vmax=CLIM[1], interpolation="nearest")
    ax_clean.set_title(f"{args.anchor}: cleaned + smoothed (span {args.smooth})")
    ax_clean.set_xlabel("record (rolling window)"); ax_clean.set_ylabel("subcarrier")
    ticks = [i for i, k in enumerate(sub) if k % 10 == 0 or k in (-26, 26)]
    ax_clean.set_yticks(ticks); ax_clean.set_yticklabels([str(sub[i]) for i in ticks])
    fig.colorbar(im_clean, ax=[ax_raw, ax_clean], label="amplitude")

    (rssi_line,) = ax_rssi.plot([], [], lw=1)
    ax_rssi.set_xlim(0, args.window); ax_rssi.set_ylim(-100, -10)
    ax_rssi.set_title("RSSI (dBm)"); ax_rssi.set_xlabel("record"); ax_rssi.grid(True, alpha=0.3)

    ax_mac.set_title("frames per source MAC (whole session)")
    ax_mac.set_xlabel("frames")

    status = fig.suptitle("", family="monospace", fontsize=9)

    def refresh(_frame):
        new = 0
        for row in read_new_lines(fh):
            parsed = payload_from_row(row)
            if parsed is not None:
                state.push(*parsed)
                new += 1
        if new == 0 and state.shown == 0:
            return ()
        im_raw.set_data(state.raw.T)
        im_clean.set_data(state.smoothed().T)
        r = np.fromiter(state.rssi, dtype=float)
        rssi_line.set_data(np.arange(len(r)), r)
        ax_mac.cla()
        top = state.top_macs()
        if top:
            labels = [m for m, _ in top][::-1]
            counts = [c for _, c in top][::-1]
            colors = ["#999" if (m in state.exclude_macs or (state.mac_filter and m != state.mac_filter))
                      else "#1f77b4" for m in labels]
            ax_mac.barh(labels, counts, color=colors)
            ax_mac.tick_params(axis="y", labelsize=8)
        ax_mac.set_title("frames per source MAC (whole session; grey = filtered out)")
        ax_mac.set_xlabel("frames")
        status.set_text(
            f"plotted={state.shown} filtered={state.skipped} seq_gaps={state.seq_gaps} "
            f"rate={state.rate_hz():.1f}/s  last_rssi={r[-1] if len(r) else float('nan'):.0f} dBm"
        )
        return ()

    if args.snapshot:
        refresh(0)
        fig.savefig(args.snapshot, dpi=120)
        print(f"wrote {args.snapshot}  ({state.shown} plotted, {state.skipped} filtered)")
        fh.close()
        return 0

    anim = FuncAnimation(fig, refresh, interval=args.interval_ms, cache_frame_data=False)  # noqa: F841
    plt.show()
    fh.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
