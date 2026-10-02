"""Spatial simulator: Trial layout -> Captures with ground-truth positions.

Places virtual transmitters in a rectangular room described by a Trial
layout file (layouts/techhub_default.yaml) and writes, per Trial, one
gateway_logger.py-format Capture per Anchor plus a ground_truth.json, so
`gateway.preprocess` and the localizers run on simulated Trials unchanged:

    python -m gateway.sim --layout layouts/techhub_default.yaml --out sim_data

Physics (ADR-0002):

- RSSI: log-distance path loss P0 - 10 n log10(d), plus the device's TX
  offset, plus log-normal shadowing fixed per (Anchor, position), plus
  per-packet jitter. Packets below the sensitivity floor are not received.
- CSI: a small ray model — the direct path plus wall reflections up to
  `reflection_order` (image sources of the rectangular room), each with
  amplitude r^bounces / L and delay L/c, summed over the 64 subcarriers
  (312.5 kHz spacing). |H| is rescaled to a fixed mean level (per-frame
  auto-scaling), then the device nuisance is applied as
  gain * (|H| + tilt * k) — the s(c + t k + m_k) form of ADR-0002. DC and
  guard entries are zero and subcarrier +1 reads low, as on hardware.

  Two deliberate departures from a literal ray trace, both physics keys:
  * reflection_order defaults to 4, not 1. First-order reflections in an
    8 x 6 m room add < 1 ripple across the 20 MHz band, so per-packet noise
    swamps the D-CFR (same-spot stability ~0.1); order 4 gives ~0.6, close
    to the ~0.75 seen on a strong device in the 2026-08-28 capture.
  * Each path's carrier phase is taken at an effective wavelength
    `phase_wavelength_m` (default 8 m) instead of the real 12 cm, so
    fingerprints vary smoothly at Reference-grid scale (ADR-0003, ~1 m)
    rather than decorrelating within half a wavelength.

Transmitters are `steady` (Beacon: fixed rate) or `sporadic` (ambient IoT:
Poisson bursts of geometric size, 50 ms apart inside a burst).

A characterization noise JSON (--noise) overrides any `physics` key of the
layout; recognised keys are the ones in DEFAULT_PHYSICS (e.g.
path_loss_exponent, rssi_shadowing_db, rssi_jitter_db, csi_noise). Unknown
keys are ignored.

Two session types (ADR-0003), each written to <out>/<session>/<trial>/:
- calibration: the Beacon at every Reference point for a fixed dwell;
- test: the target (Beacon by default, --target for the cross-device Trial)
  at Test positions P1..P10, long enough for >= 30 windows each.
Ambient devices from the layout transmit in every Trial.
"""

from __future__ import annotations

import argparse
import itertools
import json
import sys
import zlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np
import yaml

from gateway.csi import HW_TO_USABLE
from gateway.synth import GUARD_HW_INDICES, parse_dropout, write_capture

SPEED_OF_LIGHT = 299_792_458.0
SUBCARRIER_SPACING_HZ = 312_500.0
# Hardware buffer order: entry i holds subcarrier +i (i < 32) or i - 64.
HW_SUBCARRIER = np.array([i if i < 32 else i - 64 for i in range(64)])
CORRUPT_HW_INDEX = 1
CORRUPT_LEVEL = 3.0
INTRA_BURST_S = 0.05
MIN_DISTANCE_M = 0.1
HELD_OUT_MIN_M = 0.3   # Test position clearance from every Reference point
ZONE_EDGE_MIN_M = 0.3  # Test position clearance from internal zone edges
RSSI_FLOOR_DBM = -80.0

DEFAULT_PHYSICS = {
    "rssi_at_1m_dbm": -40.0,
    "path_loss_exponent": 2.7,
    "rssi_shadowing_db": 3.0,
    "rssi_jitter_db": 2.0,
    "sensitivity_dbm": -95.0,
    "wall_reflection": 0.8,
    "reflection_order": 4,
    "phase_wavelength_m": 8.0,
    "csi_mean_amplitude": 30.0,
    "csi_noise": 0.8,
}

Point = Tuple[float, float]


@dataclass
class Device:
    name: str
    role: str
    mac: str
    mode: str = "steady"
    rate_hz: float = 20.0
    burst_mean: float = 3.0
    position: Optional[Point] = None
    tx_offset_db: float = 0.0
    gain: float = 1.0
    tilt: float = 0.0


@dataclass
class Layout:
    width_m: float
    height_m: float
    anchors: Dict[str, Point]
    grid_spacing_m: float
    grid_margin_m: float
    test_positions: Dict[str, Point]
    devices: Dict[str, Device]
    physics: Dict[str, float] = field(default_factory=dict)
    zones: Dict[str, Tuple[float, float, float, float]] = field(default_factory=dict)
    path: Optional[Path] = None


def _point(v) -> Point:
    return (float(v[0]), float(v[1]))


def load_layout(path: Path) -> Layout:
    """Read and validate a Trial layout YAML file."""
    path = Path(path)
    raw = yaml.safe_load(path.read_text())
    devices = {}
    for name, d in raw.get("devices", {}).items():
        d = dict(d)
        if "position" in d:
            d["position"] = _point(d["position"])
        devices[name] = Device(name=name, **d)
    layout = Layout(
        width_m=float(raw["room"]["width_m"]),
        height_m=float(raw["room"]["height_m"]),
        anchors={a: _point(p) for a, p in raw["anchors"].items()},
        grid_spacing_m=float(raw["grid"]["spacing_m"]),
        grid_margin_m=float(raw["grid"]["margin_m"]),
        test_positions={p: _point(v) for p, v in raw["test_positions"].items()},
        devices=devices,
        physics={**DEFAULT_PHYSICS, **raw.get("physics", {})},
        zones={z: tuple(float(v) for v in r) for z, r in raw.get("zones", {}).items()},
        path=path,
    )
    _validate(layout)
    return layout


def _validate(layout: Layout) -> None:
    def inside(p: Point) -> bool:
        return 0 <= p[0] <= layout.width_m and 0 <= p[1] <= layout.height_m

    named = {**layout.anchors, **layout.test_positions}
    named.update(
        {n: d.position for n, d in layout.devices.items() if d.position is not None}
    )
    for name, p in named.items():
        if not inside(p):
            raise ValueError(f"{name} at {p} is outside the room")
    grid = reference_grid(layout)
    for name, (x, y) in layout.test_positions.items():
        nearest = min(np.hypot(x - gx, y - gy) for _, gx, gy in grid)
        if nearest < HELD_OUT_MIN_M:
            raise ValueError(
                f"Test position {name} is {nearest:.2f} m from a Reference point; "
                f"held-out positions must be >= {HELD_OUT_MIN_M} m off the grid"
            )
    for name, d in layout.devices.items():
        if d.mode not in ("steady", "sporadic"):
            raise ValueError(f"device {name}: unknown mode {d.mode!r}")
    if layout.zones:
        _validate_zones(layout)


def _validate_zones(layout: Layout) -> None:
    """Zones must lie inside the room and tile it: no overlap, no gap."""
    rects = list(layout.zones.items())
    for name, (x0, y0, x1, y1) in rects:
        if not (0 <= x0 < x1 <= layout.width_m and 0 <= y0 < y1 <= layout.height_m):
            raise ValueError(f"zone {name} is empty or outside the room")
    for (a, ra), (b, rb) in itertools.combinations(rects, 2):
        overlap_x = min(ra[2], rb[2]) - max(ra[0], rb[0])
        overlap_y = min(ra[3], rb[3]) - max(ra[1], rb[1])
        if overlap_x > 1e-9 and overlap_y > 1e-9:
            raise ValueError(f"zones {a} and {b} overlap")
    area = sum((x1 - x0) * (y1 - y0) for _, (x0, y0, x1, y1) in rects)
    if abs(area - layout.width_m * layout.height_m) > 1e-6:
        raise ValueError("zones leave a gap: they must tile the whole room")
    for name, (x, y) in layout.test_positions.items():
        own = zone_of(layout, x, y)
        for dx, dy in ((ZONE_EDGE_MIN_M, 0), (-ZONE_EDGE_MIN_M, 0),
                       (0, ZONE_EDGE_MIN_M), (0, -ZONE_EDGE_MIN_M)):
            nx, ny = x + dx, y + dy
            inside = 0 <= nx <= layout.width_m and 0 <= ny <= layout.height_m
            if inside and zone_of(layout, nx, ny) != own:
                raise ValueError(
                    f"Test position {name} is within {ZONE_EDGE_MIN_M} m of a zone "
                    "edge; its zone hit would be a coin flip"
                )


def zone_of(layout: Layout, x: float, y: float) -> Optional[str]:
    """The zone containing (x, y); a point on a shared edge goes to the zone
    with the larger coordinate. None if no zones are defined or it is outside."""
    hits = [
        (y0, x0, name)
        for name, (x0, y0, x1, y1) in layout.zones.items()
        if x0 <= x <= x1 and y0 <= y <= y1
    ]
    return max(hits)[2] if hits else None


def reference_grid(layout: Layout) -> List[Tuple[str, float, float]]:
    """Reference points R01, R02, ... row by row (x fastest)."""
    step, margin = layout.grid_spacing_m, layout.grid_margin_m
    xs = np.arange(margin, layout.width_m - margin + 1e-9, step)
    ys = np.arange(margin, layout.height_m - margin + 1e-9, step)
    width = max(2, len(str(len(xs) * len(ys))))
    points = []
    for y in ys:
        for x in xs:
            points.append(
                (f"R{len(points) + 1:0{width}d}", round(float(x), 6), round(float(y), 6))
            )
    return points


# --- physics --------------------------------------------------------------


def _shadowing_db(
    physics: Dict[str, float], anchor: str, pos: Point, seed: int
) -> float:
    """Log-normal shadowing, fixed per (Anchor, position) for a given seed."""
    sd = physics["rssi_shadowing_db"]
    if sd <= 0:
        return 0.0
    key = [seed, zlib.crc32(anchor.encode()), round(pos[0] * 1000), round(pos[1] * 1000)]
    return float(np.random.default_rng([abs(k) for k in key]).normal(0, sd))


def rssi_mean(
    layout: Layout,
    physics: Dict[str, float],
    device: Device,
    anchor: str,
    pos: Point,
    seed: int = 0,
) -> float:
    """Mean RSSI (dBm) at `anchor` for `device` placed at `pos`."""
    ax, ay = layout.anchors[anchor]
    d = max(np.hypot(pos[0] - ax, pos[1] - ay), MIN_DISTANCE_M)
    return (
        physics["rssi_at_1m_dbm"]
        - 10 * physics["path_loss_exponent"] * np.log10(d)
        + device.tx_offset_db
        + _shadowing_db(physics, anchor, pos, seed)
    )


def _image_sources(
    pos: Point, width: float, height: float, order: int
) -> List[Tuple[float, float, int]]:
    """(x, y, bounces) of every image of `pos` in a rectangular room with up
    to `order` wall reflections; bounces == 0 is the direct path."""

    def axis(p: float, size: float) -> List[Tuple[float, int]]:
        out = []
        for a in range(-order, order + 1):
            out.append((2 * a * size + p, 2 * abs(a)))
            out.append((2 * a * size - p, abs(2 * a - 1)))
        return out

    return [
        (ix, iy, bx + by)
        for ix, bx in axis(pos[0], width)
        for iy, by in axis(pos[1], height)
        if bx + by <= order
    ]


def csi_fingerprint(
    layout: Layout,
    physics: Dict[str, float],
    device: Device,
    anchor: str,
    pos: Point,
) -> np.ndarray:
    """Noise-free 64-entry hardware-order CSI amplitudes for `device` at `pos`."""
    ax, ay = layout.anchors[anchor]
    k = HW_SUBCARRIER
    channel = np.zeros(64, dtype=np.complex128)
    images = _image_sources(
        pos, layout.width_m, layout.height_m, int(physics["reflection_order"])
    )
    for sx, sy, bounces in images:
        length = max(np.hypot(sx - ax, sy - ay), MIN_DISTANCE_M)
        amplitude = physics["wall_reflection"] ** bounces / length
        cycles = (
            k * SUBCARRIER_SPACING_HZ * length / SPEED_OF_LIGHT
            + length / physics["phase_wavelength_m"]
        )
        channel += amplitude * np.exp(-2j * np.pi * cycles)

    mag = np.abs(channel)
    mag *= physics["csi_mean_amplitude"] / mag[HW_TO_USABLE].mean()
    amps = device.gain * (mag + device.tilt * k)
    amps = np.clip(amps, 1.0, None)
    amps[GUARD_HW_INDICES] = 0.0
    amps[CORRUPT_HW_INDEX] = CORRUPT_LEVEL
    return amps


def load_physics(layout: Layout, noise_path: Optional[Path] = None) -> Dict[str, float]:
    """The layout's physics, overridden by any DEFAULT_PHYSICS key found in a
    characterization noise JSON. Unknown keys in that file are ignored."""
    physics = dict(layout.physics)
    if noise_path is not None:
        data = json.loads(Path(noise_path).read_text())
        physics.update({k: float(data[k]) for k in DEFAULT_PHYSICS if k in data})
    return physics


def _beacon(layout: Layout) -> Device:
    for device in layout.devices.values():
        if device.role == "beacon":
            return device
    raise ValueError("layout has no device with role: beacon")


def check_coverage(
    layout: Layout,
    physics: Dict[str, float],
    min_anchors: int = 3,
    floor_dbm: float = RSSI_FLOOR_DBM,
    target: Optional[str] = None,
) -> List[Tuple[str, int]]:
    """Test positions where fewer than `min_anchors` Anchors see the target's
    mean RSSI (no shadowing) above `floor_dbm` — the ADR-0003 placement rule.
    `target` names a layout device (default: the Beacon). Returns
    (position, anchors_above) for each failing position."""
    beacon = _beacon(layout) if target is None else layout.devices[target]
    no_shadow = dict(physics, rssi_shadowing_db=0.0)
    failing = []
    for name, pos in layout.test_positions.items():
        above = sum(
            rssi_mean(layout, no_shadow, beacon, a, pos) > floor_dbm
            for a in layout.anchors
        )
        if above < min_anchors:
            failing.append((name, above))
    return failing


# --- transmitters ---------------------------------------------------------


def transmit_times(
    device: Device, duration_s: float, rng: np.random.Generator
) -> np.ndarray:
    """Sorted transmit times in [0, duration_s) for one device."""
    if device.mode == "steady":
        period = 1.0 / device.rate_hz
        t = np.arange(0.0, duration_s, period)
        t = t + rng.uniform(0, 0.1 * period, len(t))
    else:
        burst_rate = device.rate_hz / device.burst_mean
        n_bursts = rng.poisson(burst_rate * duration_s)
        starts = rng.uniform(0, duration_s, n_bursts)
        sizes = rng.geometric(1.0 / device.burst_mean, n_bursts)
        t = np.concatenate(
            [s + INTRA_BURST_S * np.arange(n) for s, n in zip(starts, sizes)]
            or [np.empty(0)]
        )
    return np.sort(t[t < duration_s])


# --- sessions -------------------------------------------------------------


def _simulate_trial(
    layout: Layout,
    physics: Dict[str, float],
    placements: Sequence[Tuple[Device, Point]],
    trial_dir: Path,
    t_session: float,
    dwell_s: float,
    rng: np.random.Generator,
    seed: int,
    dropouts: Sequence[Tuple[str, float, float]],
    malformed_frac: float,
) -> Tuple[Dict[str, int], int]:
    """Write one Trial's Captures; returns (lines per Anchor, malformed)."""
    trial_dir.mkdir(parents=True, exist_ok=True)
    schedules = [transmit_times(d, dwell_s, rng) for d, _ in placements]
    lines: Dict[str, int] = {}
    n_malformed = 0
    for anchor in layout.anchors:
        packets = []
        for (device, pos), times in zip(placements, schedules):
            mu = rssi_mean(layout, physics, device, anchor, pos, seed)
            fp = csi_fingerprint(layout, physics, device, anchor, pos)
            rssi = mu + rng.normal(0, physics["rssi_jitter_db"], len(times))
            noise = rng.normal(0, physics["csi_noise"], (len(times), 64))
            for t, r, n in zip(times, rssi, noise):
                if r < physics["sensitivity_dbm"]:
                    continue
                if any(a == anchor and lo <= t < hi for a, lo, hi in dropouts):
                    continue
                packets.append((float(t), device.mac, int(round(r)), fp + n))
        packets.sort(key=lambda p: p[0])
        lines[anchor], malformed = write_capture(
            trial_dir / f"{anchor}_sim.csv", anchor, packets, t_session,
            dwell_s, malformed_frac, rng,
        )
        n_malformed += malformed
    return lines, n_malformed


def simulate_session(
    layout: Layout,
    out: Path,
    session: str,
    dwell_s: float,
    seed: int = 42,
    positions: Optional[Sequence[Tuple[str, float, float]]] = None,
    target: str = "beacon",
    physics: Optional[Dict[str, float]] = None,
    dropouts: Optional[Sequence[Tuple[str, float, float]]] = None,
    malformed_frac: float = 0.0,
    t_start: Optional[float] = None,
    gap_s: float = 10.0,
) -> dict:
    """Write a calibration or test session: one Trial directory per position
    under <out>/<session>/, plus <out>/<session>/ground_truth.json.

    calibration places the Beacon at each Reference point; test places
    `target` at each Test position. Ambient devices with a fixed position
    transmit in every Trial. `dropouts` are (anchor, start_s, end_s) relative
    to each Trial's start. Trials follow each other `gap_s` apart in host
    time, so several Trial directories passed to one preprocess run (one
    --in each) never share a window."""
    if session == "calibration":
        mover = _beacon(layout)
        positions = reference_grid(layout) if positions is None else positions
    elif session == "test":
        mover = layout.devices[target]
        if positions is None:
            positions = [(n, x, y) for n, (x, y) in layout.test_positions.items()]
    else:
        raise ValueError(f"unknown session type {session!r}")
    physics = layout.physics if physics is None else physics
    dropouts = list(dropouts or [])
    ambient = [
        d for d in layout.devices.values()
        if d.role == "ambient" and d.position is not None
    ]
    rng = np.random.default_rng(seed)
    session_dir = Path(out) / session
    t_cursor = datetime.now(timezone.utc).timestamp() if t_start is None else t_start

    trials = []
    for trial_id, x, y in positions:
        placements = [(mover, (x, y))] + [(d, d.position) for d in ambient]
        lines, n_malformed = _simulate_trial(
            layout, physics, placements, session_dir / trial_id, t_cursor,
            dwell_s, rng, seed, dropouts, malformed_frac,
        )
        trials.append({
            "id": trial_id,
            "t_start": t_cursor,
            "t_end": t_cursor + dwell_s,
            "lines": lines,
            "malformed": n_malformed,
            "devices": [
                {"name": d.name, "role": d.role, "mac": d.mac, "mode": d.mode,
                 "x": p[0], "y": p[1]}
                for d, p in placements
            ],
        })
        t_cursor += dwell_s + gap_s

    truth = {
        "session": session,
        "layout": str(layout.path) if layout.path else None,
        "seed": seed,
        "dwell_s": dwell_s,
        "room": {"width_m": layout.width_m, "height_m": layout.height_m},
        "anchors": {a: list(p) for a, p in layout.anchors.items()},
        "physics": physics,
        "dropouts": [list(d) for d in dropouts],
        "malformed_frac": malformed_frac,
        "trials": trials,
    }
    with open(session_dir / "ground_truth.json", "w") as fh:
        json.dump(truth, fh, indent=2)
    return truth


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        prog="gateway.sim", description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--layout", type=Path, default=Path("layouts/techhub_default.yaml"))
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--session", choices=("calibration", "test", "both"), default="both")
    ap.add_argument("--target", default="beacon",
                    help="layout device placed at Test positions (e.g. phone "
                         "for the cross-device Trial)")
    ap.add_argument("--cal-dwell", type=float, default=30.0,
                    help="seconds at each Reference point")
    ap.add_argument("--test-dwell", type=float, default=40.0,
                    help="seconds at each Test position (>= 30 one-second windows)")
    ap.add_argument("--noise", type=Path,
                    help="characterization noise JSON overriding layout physics")
    ap.add_argument("--dropout", action="append", default=[],
                    help="anchor:start-end seconds within each Trial, e.g. A3:10-20; repeatable")
    ap.add_argument("--malformed", type=float, default=0.0,
                    help="fraction of lines to garble (0..1)")
    ap.add_argument("--min-anchors", type=int, default=3,
                    help="for the ADR-0003 coverage check only")
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args(argv)

    layout = load_layout(args.layout)
    physics = load_physics(layout, args.noise)
    for name, above in check_coverage(layout, physics, args.min_anchors, target=args.target):
        print(f"warning: {name} has only {above} Anchor(s) above "
              f"{RSSI_FLOOR_DBM:.0f} dBm (need {args.min_anchors})", file=sys.stderr)

    sessions = ("calibration", "test") if args.session == "both" else (args.session,)
    dropouts = [parse_dropout(d) for d in args.dropout]
    t_start = datetime.now(timezone.utc).timestamp()
    for session in sessions:
        truth = simulate_session(
            layout, args.out, session,
            dwell_s=args.cal_dwell if session == "calibration" else args.test_dwell,
            seed=args.seed, target=args.target, physics=physics,
            dropouts=dropouts, malformed_frac=args.malformed, t_start=t_start,
        )
        t_start = truth["trials"][-1]["t_end"] + 60.0
        n_lines = sum(sum(t["lines"].values()) for t in truth["trials"])
        print(f"{session}: {len(truth['trials'])} Trials, {n_lines} lines -> "
              f"{args.out / session}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
