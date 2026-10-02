"""The Sniper and the full proposed pipeline (ADR-0002).

    python -m gateway.sniper --sim sim_data --layout layouts/techhub_default.yaml \
        --out out/eval

Per window: the Scout gives a mixture, its 95 % bounding box and its
estimate (the mean of the most probable kernel); the fallback rule then
decides whether the Sniper refines it.

Fallback rule. An Anchor is *Sniper-ready* when it has >= 3 valid CSI
Records, a within-window D-CFR stability >= 0.6 and RSSI above the floor
(the preprocess `above_floor` flag). The Sniper runs only when at least
`min_anchors` Anchors are ready; a failing Anchor is not counted, it does
not veto the window. Otherwise Mode = `fallback` and the estimate is the
Scout's, with the bbox still reported.

Sniper = particle filter. Particles start uniformly inside the bbox. Each
looks up the stored D-CFR of its nearest Reference point; per ready Anchor
the Pearson rho against the live D-CFR is fused as w = prod exp(rho / sigma),
an Anchor that is not ready (or has no stored D-CFR at that Reference point)
contributing a factor of 1. The estimate is the weighted centroid, and the
particles are then systematically resampled. For a stationary target the
particle set carries over to the Trial's next window with a small Gaussian
jitter; particles that leave the new bbox are redrawn uniformly inside it,
so the set stays confined to the Scout's box. The harness calls `reset()` at
the start of each Trial; a fallback window leaves the particle set as it is.

sigma and the jitter were tuned on a simulated validation session (seeds
7/8, not the seed `make eval` uses; 2026-10-02 journal): a small sigma locks
the particles onto a wrong Reference point after one noisy window, a large
one stops them converging, and sigma = 2 with 0.3 m jitter gave the lowest
MAE. `--sigma` overrides it.

The stability threshold defaults to ADR-0002's 0.6, sized on real Captures.
The simulator's D-CFR does not reproduce that: its median within-window
stability is ~0.2, and an Anchor near the target sees an almost flat
spectrum (stability ~0), so at 0.6 no simulated window is Sniper-ready and
any positive threshold only drops whole Test positions. `make eval`
therefore passes `--min-stability 0` (sim-only); the other two conditions
stay as specified, and the tests exercise the 0.6 gate directly.
Needs the `scout` extra (PyTorch), as the Scout does.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

from gateway.evaluate import MIN_SUFFICIENT_WINDOWS, evaluate, format_comparison, format_table
from gateway.io import read_jsonl
from gateway.radiomap import RadioMap
from gateway.scout import Box, MdnScout, ScoutConfig, bbox, run_scout
from gateway.sim import Layout, load_layout

FALLBACK = "fallback"
SNIPER = "sniper"


@dataclass
class SniperConfig:
    n_particles: int = 500
    sigma: float = 2.0             # exp(rho / sigma) temperature (tuned, see above)
    jitter_m: float = 0.3          # per-window particle jitter sd, stationary target
    min_csi: int = 3               # valid CSI Records per Anchor (ADR-0002)
    min_stability: float = 0.6     # within-window D-CFR stability (ADR-0002)
    min_anchors: int = 3           # Sniper-ready Anchors (preprocess --min-anchors)
    seed: int = 0


def sniper_ready(obs: Optional[dict], config: SniperConfig) -> bool:
    """One Anchor's observation passes all three fallback-rule conditions."""
    return (
        obs is not None
        and obs.get("dcfr") is not None
        and obs["csi_n"] >= config.min_csi
        and obs["stability"] is not None
        and obs["stability"] >= config.min_stability
        and bool(obs["above_floor"])
    )


def ready_anchors(window: dict, config: SniperConfig) -> List[str]:
    return [a for a, obs in window["anchors"].items() if sniper_ready(obs, config)]


def _unit(v: np.ndarray) -> np.ndarray:
    """Mean-centred, unit-norm rows, so a dot product is Pearson rho; a
    constant row stays all zeros (rho 0)."""
    v = v - v.mean(axis=-1, keepdims=True)
    norm = np.linalg.norm(v, axis=-1, keepdims=True)
    return np.divide(v, norm, out=np.zeros_like(v), where=norm > 0)


def systematic_resample(weights: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    """Indices drawn by systematic resampling (one uniform offset, n
    evenly spaced pointers into the cumulative weights)."""
    n = len(weights)
    pointers = (rng.random() + np.arange(n)) / n
    cumulative = np.cumsum(weights)
    cumulative[-1] = 1.0
    return np.searchsorted(cumulative, pointers)


class ParticleFilter:
    """D-CFR particle filter over a Radio map's Reference points."""

    def __init__(self, radio_map: RadioMap, config: Optional[SniperConfig] = None):
        if not radio_map.points:
            raise ValueError("radio map is empty")
        self.config = config or SniperConfig()
        self.anchor_ids = list(radio_map.anchor_ids)
        points = list(radio_map.points.values())
        self.positions = np.array([(p.x, p.y) for p in points])
        # Per Anchor: unit-normalized stored D-CFR per Reference point, and
        # which Reference points have one at all.
        self.stored: Dict[str, np.ndarray] = {}
        self.has: Dict[str, np.ndarray] = {}
        for a in self.anchor_ids:
            fps = [p.anchors.get(a) for p in points]
            n = next((len(fp.dcfr) for fp in fps if fp is not None), 0)
            rows = np.array([np.zeros(n) if fp is None else fp.dcfr for fp in fps])
            self.stored[a] = _unit(rows.reshape(len(points), n))
            self.has[a] = np.array([fp is not None for fp in fps])
        self.rng = np.random.default_rng(self.config.seed)
        self.particles: Optional[np.ndarray] = None

    def reset(self) -> None:
        self.particles = None

    def nearest(self, particles: np.ndarray) -> np.ndarray:
        d = np.linalg.norm(particles[:, None, :] - self.positions[None, :, :], axis=2)
        return np.argmin(d, axis=1)

    def log_weights(self, particles: np.ndarray, live: Dict[str, np.ndarray]) -> np.ndarray:
        """sum over Anchors of rho / sigma, i.e. log prod exp(rho / sigma);
        an Anchor missing from `live` or from a particle's Reference point
        adds 0."""
        ref = self.nearest(particles)
        log_w = np.zeros(len(particles))
        for a, dcfr in live.items():
            if a not in self.stored:
                continue
            rho = self.stored[a][ref] @ _unit(np.asarray(dcfr, dtype=np.float64))
            log_w += np.where(self.has[a][ref], rho, 0.0) / self.config.sigma
        return log_w

    def _uniform(self, box: Box, n: int) -> np.ndarray:
        x0, y0, x1, y1 = box
        return self.rng.uniform((x0, y0), (x1, y1), size=(n, 2))

    def step(self, box: Box, live: Dict[str, np.ndarray]) -> Tuple[float, float]:
        """One window: predict (jitter, or initialise), weight, estimate the
        weighted centroid, resample. Returns the estimate."""
        n = self.config.n_particles
        if self.particles is None:
            particles = self._uniform(box, n)
        else:
            particles = self.particles + self.rng.normal(0, self.config.jitter_m, (n, 2))
            x0, y0, x1, y1 = box
            out = ((particles[:, 0] < x0) | (particles[:, 0] > x1)
                   | (particles[:, 1] < y0) | (particles[:, 1] > y1))
            particles[out] = self._uniform(box, int(out.sum()))
        log_w = self.log_weights(particles, live)
        w = np.exp(log_w - log_w.max())
        w /= w.sum()
        x, y = w @ particles
        self.particles = particles[systematic_resample(w, self.rng)]
        return float(x), float(y)


class ProposedLocalizer:
    """Scout -> fallback rule -> Sniper, one estimate and Mode per window."""

    name = "proposed"

    def __init__(self, scout: MdnScout, radio_map: RadioMap,
                 config: Optional[SniperConfig] = None):
        self.scout = scout
        self.config = config or SniperConfig()
        self.filter = ParticleFilter(radio_map, self.config)

    def reset(self) -> None:
        """Start of a Trial: the next Sniper window re-initialises particles."""
        self.filter.reset()

    def estimate(self, window: dict) -> Optional[Tuple[float, float]]:
        loc = self.locate(window)
        return None if loc is None else (loc["x"], loc["y"])

    def locate(self, window: dict) -> Optional[dict]:
        mixture = self.scout.predict(window)
        if mixture is None:
            return None
        box = bbox(mixture, self.scout.room)
        ready = ready_anchors(window, self.config)
        if len(ready) < self.config.min_anchors:
            x, y = mixture.mode_mean(self.scout.room)
            return {"x": x, "y": y, "bbox": box, "mode": FALLBACK}
        live = {a: np.asarray(window["anchors"][a]["dcfr"]) for a in ready}
        x, y = self.filter.step(box, live)
        return {"x": x, "y": y, "bbox": box, "mode": SNIPER}


def run_proposed(sim_dir: Path, layout: Layout, out_dir: Path,
                 config: Optional[SniperConfig] = None,
                 scout_config: Optional[ScoutConfig] = None, knn_k: int = 3) -> dict:
    """Baseline and Scout (`run_scout`), then the proposed pipeline on the
    same Radio map, Scout and test windows. Writes <out_dir>/proposed.json
    holding all three results."""
    sim_dir, out_dir = Path(sim_dir), Path(out_dir)
    config = config or SniperConfig()
    prior = run_scout(sim_dir, layout, out_dir, scout_config, knn_k=knn_k)
    radio_map = RadioMap.load(out_dir / "radio_map.json")
    scout = MdnScout.load(out_dir / "scout.pt")

    test_meta, test_windows = read_jsonl(out_dir / "test_windows.jsonl")
    test_truth = json.loads((sim_dir / "test" / "ground_truth.json").read_text())
    localizer = ProposedLocalizer(scout, radio_map, config)
    result = evaluate(localizer, test_windows, test_truth, layout)
    result["meta"] = {
        "localizer": localizer.name,
        "config": asdict(config),
        "radio_map": "radio_map.json",
        "scout": "scout.pt",
        "reference_points": len(radio_map.points),
        "layout": str(layout.path) if layout.path else None,
        "sim": str(sim_dir),
        "preprocess": test_meta,
    }
    out = {"baseline": prior["baseline"], "scout": prior["scout"], "proposed": result}
    with open(out_dir / "proposed.json", "w") as fh:
        json.dump(out, fh, indent=2)
    return out


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        prog="gateway.sniper", description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--sim", type=Path, default=Path("sim_data"),
                    help="directory holding calibration/ and test/ sessions")
    ap.add_argument("--layout", type=Path, default=Path("layouts/techhub_default.yaml"))
    ap.add_argument("--out", type=Path, default=Path("out/eval"))
    ap.add_argument("--sigma", type=float, default=SniperConfig.sigma)
    ap.add_argument("--min-stability", type=float, default=SniperConfig.min_stability,
                    help="Sniper-ready stability threshold (ADR-0002: 0.6; "
                         "make eval uses 0 on simulated data, see above)")
    ap.add_argument("--particles", type=int, default=SniperConfig.n_particles)
    ap.add_argument("--seed", type=int, default=SniperConfig.seed)
    args = ap.parse_args(argv)

    config = SniperConfig(sigma=args.sigma, min_stability=args.min_stability,
                          n_particles=args.particles, seed=args.seed)
    result = run_proposed(args.sim, load_layout(args.layout), args.out, config)
    proposed = result["proposed"]
    print(f"Proposed (Scout -> fallback rule -> Sniper, sigma={config.sigma:g}, "
          f"min stability {config.min_stability:g}, {config.n_particles} particles), "
          f"{proposed['meta']['reference_points']} Reference points")
    print(format_table(proposed))
    print()
    print(format_comparison({"k-NN": result["baseline"], "Scout": result["scout"],
                             "Proposed": proposed}))
    o = proposed["overall"]
    print(f"\nfallback rate {o['fallback_rate']:.1%} of {o['n_estimates']} estimates; "
          f"latency ms/win mean / p95: k-NN "
          f"{result['baseline']['overall']['latency_ms_mean']:.3f} / "
          f"{result['baseline']['overall']['latency_ms_p95']:.3f}, proposed "
          f"{o['latency_ms_mean']:.3f} / {o['latency_ms_p95']:.3f}")
    for row in proposed["trials"]:
        if row["n_sufficient"] < MIN_SUFFICIENT_WINDOWS:
            print(f"warning: {row['id']} has {row['n_sufficient']} sufficient windows "
                  f"(ADR-0003 needs >= {MIN_SUFFICIENT_WINDOWS}; repeat the Trial)",
                  file=sys.stderr)
    print(f"\nwrote {args.out / 'proposed.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
