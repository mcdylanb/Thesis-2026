"""Import a real session recorded as one zip per Reference point (#45).

    python -m gateway.session_import --src data/<capture>/compiled_data \
        --out out/techhub [--layout layouts/techhub_default.yaml] [--untrimmed]

The team uploads a Calibration session as one folder per Reference point,
`<src>/pN/data_pN.zip`, each zip holding that point's per-Anchor Captures
(`data/A1_<stamp>.csv` ...). This writes the same shape `gateway.sim`
produces: `<out>/<session>/pN/A*.csv` plus `<out>/<session>/ground_truth.json`,
so preprocessing, the Radio map builder and the evaluation harness read a
real session exactly like a simulated one.

There is no hand-written schedule: a Trial's host-time span comes from the
Beacon's own Records. Trimmed (the default) skips the first DEFAULT_TRIM
skip_s (30 s), when someone is still walking away from the placed Beacon,
and keeps the next keep_s (4 min), so every point carries equal weight. A point whose Beacon Records do
not cover that is kept with its span cut at its last Record and listed under
`short`. Untrimmed spans the Beacon's first to last Record.
"""

from __future__ import annotations

import argparse
import json
import sys
import zipfile
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

from gateway.parser import iter_logged_records
from gateway.records import CsiRecord, ParseStats
from gateway.sim import Layout, load_layout, reference_grid

DEFAULT_TRIM = (30.0, 240.0)   # (skip_s, keep_s)
_EPS = 1e-3                    # keeps the last Record inside [t_start, t_end)


def _unpack_point(src: Path, point: str, dest: Path) -> List[Path]:
    """Copy one point's Captures to <dest>/: the CSVs of its zip(s), or CSVs
    already unpacked in its folder. Only base names are kept, so nothing in
    a zip can write outside <dest>."""
    folder = src / point
    if not folder.is_dir():
        raise FileNotFoundError(f"no recording for {point} under {src}")
    dest.mkdir(parents=True, exist_ok=True)
    written = []
    for zpath in sorted(folder.glob("*.zip")):
        with zipfile.ZipFile(zpath) as zf:
            for name in zf.namelist():
                base = Path(name).name
                if base.endswith(".csv") and not base.startswith("."):
                    target = dest / base
                    target.write_bytes(zf.read(name))
                    written.append(target)
    for csv_path in sorted(folder.glob("*.csv")):
        target = dest / csv_path.name
        target.write_bytes(csv_path.read_bytes())
        written.append(target)
    if not written:
        raise FileNotFoundError(f"no Captures for {point} under {folder}")
    return sorted(written)


def _beacon_span(captures: Sequence[Path], mac: str) -> Tuple[float, float]:
    """Host time of the Beacon's first and last Record across all Anchors."""
    first, last = None, None
    stats = ParseStats()
    for path in captures:
        for rec in iter_logged_records(path, stats):
            if isinstance(rec, CsiRecord) and rec.mac.lower() == mac:
                first = rec.t_host if first is None else min(first, rec.t_host)
                last = rec.t_host if last is None else max(last, rec.t_host)
    if first is None:
        raise ValueError(f"no Beacon ({mac}) Records in {captures[0].parent}")
    return first, last


def import_session(
    src: Path,
    layout: Layout,
    out: Path,
    session: str = "calibration",
    points: Optional[Sequence[str]] = None,
    trim: Optional[Tuple[float, float]] = DEFAULT_TRIM,
) -> dict:
    """Write <out>/<session>/ (Captures + ground_truth.json) from the
    per-point recordings under `src`; `points` defaults to every Reference
    point of the layout, in walk order. `trim` is (skip_s, keep_s), or None
    for the untrimmed span."""
    src, session_dir = Path(src), Path(out) / session
    beacon = next(d for d in layout.devices.values() if d.role == "beacon")
    mac = beacon.mac.lower()
    grid = {name: (x, y) for name, x, y in reference_grid(layout)}
    points = list(grid) if points is None else list(points)

    trials, short = [], []
    for point in points:
        if point not in grid:
            raise ValueError(f"{point} is not a Reference point of {layout.path}")
        captures = _unpack_point(src, point, session_dir / point)
        first, last = _beacon_span(captures, mac)
        if trim is None:
            t_start, t_end, is_short = first, last + _EPS, False
        else:
            skip_s, keep_s = trim
            t_start = first + skip_s
            t_end = t_start + keep_s
            is_short = last < t_end
            if is_short:
                t_end = max(t_start, last + _EPS)
                short.append(point)
        x, y = grid[point]
        trials.append({
            "id": point,
            "t_start": t_start,
            "t_end": t_end,
            "beacon_first": first,
            "beacon_last": last,
            "short": is_short,
            "captures": [p.name for p in captures],
            "devices": [{"name": beacon.name, "role": beacon.role, "mac": mac,
                         "x": x, "y": y}],
        })

    truth = {
        "session": session,
        "source": str(src),
        "layout": str(layout.path) if layout.path else None,
        "trim": None if trim is None else {"skip_s": trim[0], "keep_s": trim[1]},
        "room": {"width_m": layout.width_m, "height_m": layout.height_m},
        "anchors": {a: list(p) for a, p in layout.anchors.items()},
        "short": short,
        "trials": trials,
    }
    with open(session_dir / "ground_truth.json", "w") as fh:
        json.dump(truth, fh, indent=2)
    return truth


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        prog="gateway.session_import", description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--src", required=True, type=Path,
                    help="folder holding one pN/ folder per Reference point")
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--layout", type=Path, default=Path("layouts/techhub_default.yaml"))
    ap.add_argument("--session", default="calibration")
    skip_s, keep_s = DEFAULT_TRIM
    ap.add_argument("--untrimmed", action="store_true",
                    help="span the Beacon's first to last Record instead of "
                         f"skipping {skip_s:g} s and keeping {keep_s:g} s")
    args = ap.parse_args(argv)

    truth = import_session(args.src, load_layout(args.layout), args.out,
                           session=args.session,
                           trim=None if args.untrimmed else DEFAULT_TRIM)
    for point in truth["short"]:
        print(f"warning: {point}'s Beacon Records end before its {keep_s:g} s "
              "are kept; span cut at the last Record", file=sys.stderr)
    print(f"{args.session}: {len(truth['trials'])} Trials -> {args.out / args.session}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
