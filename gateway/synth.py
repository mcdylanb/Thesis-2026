"""Synthetic capture-session generator.

Writes gateway_logger.py-format files plus a ground_truth.json so the
pipeline can be verified end-to-end without hardware:

    python -m gateway.synth --out synth_data/ --duration 60 \
        --dropout A3:10-20 --malformed 0.02
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np

from gateway.csi import HW_TO_USABLE

DEFAULT_ANCHORS = ("A1", "A2", "A3", "A4")
DEFAULT_MACS = ("a4:cf:12:3b:9e:01", "3c:22:fb:aa:10:07")
GUARD_HW_INDICES = [0] + list(range(27, 38))


def make_csi_template(rng: np.random.Generator) -> np.ndarray:
    """A plausible 64-entry hardware-order amplitude template: smooth
    multipath-like ripple on usable subcarriers, zero on DC/guard."""
    amps = np.zeros(64, dtype=np.float64)
    x = np.linspace(0, 2 * np.pi, len(HW_TO_USABLE))
    ripple = (
        30
        + 12 * np.sin(x * rng.uniform(1, 3) + rng.uniform(0, 2 * np.pi))
        + 6 * np.sin(x * rng.uniform(3, 6) + rng.uniform(0, 2 * np.pi))
    )
    amps[HW_TO_USABLE] = np.clip(ripple, 1, None)
    return amps


def parse_dropout(spec: str) -> Tuple[str, float, float]:
    """'A3:10-20' -> (anchor, start_s, end_s) relative to session start."""
    anchor, _, span = spec.partition(":")
    lo, _, hi = span.partition("-")
    return anchor, float(lo), float(hi)


def generate(
    outdir: Path,
    duration_s: float = 60.0,
    anchors: Tuple[str, ...] = DEFAULT_ANCHORS,
    macs: Tuple[str, ...] = DEFAULT_MACS,
    rate_hz: float = 20.0,
    dropouts: Optional[List[Tuple[str, float, float]]] = None,
    malformed_frac: float = 0.0,
    seed: int = 42,
) -> dict:
    rng = np.random.default_rng(seed)
    dropouts = dropouts or []
    outdir.mkdir(parents=True, exist_ok=True)

    t_session = datetime.now(timezone.utc).timestamp()
    period = 1.0 / rate_hz

    # Per (anchor, mac): a stable CSI template and a mean RSSI.
    templates: Dict[str, Dict[str, np.ndarray]] = {}
    rssi_means: Dict[str, Dict[str, float]] = {}
    for a in anchors:
        templates[a] = {m: make_csi_template(rng) for m in macs}
        rssi_means[a] = {m: float(rng.integers(-75, -45)) for m in macs}

    truth = {
        "duration_s": duration_s,
        "rate_hz": rate_hz,
        "anchors": list(anchors),
        "macs": list(macs),
        "rssi_means": rssi_means,
        "templates_hw": {
            a: {m: templates[a][m].tolist() for m in macs} for a in anchors
        },
        "dropouts": [list(d) for d in dropouts],
        "malformed_per_anchor": {},
        "lines_per_anchor": {},
    }

    for anchor in anchors:
        path = outdir / f"{anchor}_synth.csv"
        n_lines = 0
        n_malformed = 0
        with open(path, "w") as fh:
            fh.write("host_iso,host_ns,line\n")
            seq = 0
            t = 0.0
            while t < duration_s:
                for mac in macs:
                    seq += 1
                    t_pkt = t + rng.uniform(0, period * 0.2)
                    if any(a == anchor and lo <= t_pkt < hi for a, lo, hi in dropouts):
                        continue
                    t_abs = t_session + t_pkt
                    host_iso = datetime.fromtimestamp(t_abs, timezone.utc).isoformat()
                    host_ns = int(t_abs * 1e9)

                    if rng.random() < malformed_frac:
                        line = "CSI,%s,garbled" % anchor
                        n_malformed += 1
                    else:
                        rssi = int(
                            round(rssi_means[anchor][mac] + rng.normal(0, 2.0))
                        )
                        amps = templates[anchor][mac] + rng.normal(0, 0.8, 64)
                        amps[GUARD_HW_INDICES] = 0
                        amps = np.clip(np.round(amps), 0, 181).astype(int)
                        ts_us = int((t_pkt * 1e6) % 2**32)
                        line = (
                            f"CSI,{anchor},{seq},{mac},{rssi},1,6,{ts_us},64,"
                            + ",".join(str(v) for v in amps)
                        )
                    fh.write(f'{host_iso},{host_ns},"{line}"\n')
                    n_lines += 1
                t += period

            # One trailing STAT line per anchor.
            host_iso = datetime.fromtimestamp(
                t_session + duration_s, timezone.utc
            ).isoformat()
            stat = (
                f"STAT,{anchor},{int(duration_s * 1000)},{seq},{seq},{seq},0,180000"
            )
            fh.write(f'{host_iso},{int((t_session + duration_s) * 1e9)},"{stat}"\n')

        truth["malformed_per_anchor"][anchor] = n_malformed
        truth["lines_per_anchor"][anchor] = n_lines

    truth_path = outdir / "ground_truth.json"
    with open(truth_path, "w") as fh:
        json.dump(truth, fh, indent=2)
    return truth


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="gateway.synth", description=__doc__)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--duration", type=float, default=60.0)
    ap.add_argument("--rate", type=float, default=20.0)
    ap.add_argument("--macs", type=int, default=2, choices=(1, 2))
    ap.add_argument("--dropout", action="append", default=[],
                    help="anchor:start-end seconds, e.g. A3:10-20; repeatable")
    ap.add_argument("--malformed", type=float, default=0.0,
                    help="fraction of lines to garble (0..1)")
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args(argv)

    truth = generate(
        args.out,
        duration_s=args.duration,
        macs=DEFAULT_MACS[: args.macs],
        rate_hz=args.rate,
        dropouts=[parse_dropout(d) for d in args.dropout],
        malformed_frac=args.malformed,
        seed=args.seed,
    )
    print(json.dumps({k: truth[k] for k in
                      ("lines_per_anchor", "malformed_per_anchor", "rssi_means")},
                     indent=2))
    return 0


if __name__ == "__main__":
    import sys

    sys.exit(main())
