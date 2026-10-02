"""The Scout: a mixture density network over per-Anchor RSSI (ADR-0002).

    python -m gateway.scout --sim sim_data --layout layouts/techhub_default.yaml \
        --out out/eval

Input is the window's four smoothed RSSI values, z-scored over the Anchors
present with a missing Anchor imputed exactly as the k-NN baseline does
(`gateway.knn.zscored_rssi`), plus a four-bit presence mask. Output is a
mixture of K = 3 diagonal Gaussians over (x, y) in Bishop's (1994) form:
softmax mixing coefficients, `exp` standard deviations with a floor, and a
negative log-likelihood loss computed with log-sum-exp.

Training data is the Radio map's Reference points plus path-loss-perturbed
copies of each. Within-window z-scoring already cancels a device's gain
offset, and a change of path-loss exponent too (both are affine in dBm and
common to all Anchors), so what the perturbation adds is what z-scoring
cannot remove: independent per-Anchor shadowing, a gain offset that moves
readings relative to the imputation floor, and dropped Anchors so the
presence-mask path is trained.

The estimate is the mean of the most probable kernel (ADR-0002); the 95 %
bounding box comes from sampling the mixture. `run_scout()` trains on the
Calibration session, saves the weights and training config next to the
Radio map they came from, and scores the Scout next to the k-NN baseline.
Needs the `scout` extra (PyTorch): `pip install '.[scout]'`.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple, Union

import numpy as np
import torch
from torch import nn

from gateway.evaluate import evaluate, format_comparison, format_table, run_baseline
from gateway.io import read_jsonl
from gateway.knn import RSSI_FLOOR_DBM, window_rssi, zscored_rssi
from gateway.radiomap import RadioMap
from gateway.sim import Layout, load_layout

Box = Tuple[float, float, float, float]  # (x0, y0, x1, y1), metres


@dataclass
class ScoutConfig:
    k: int = 3                     # mixture kernels (ADR-0002)
    hidden: int = 64
    epochs: int = 500
    lr: float = 1e-2
    sigma_floor_m: float = 0.05    # variance floor, as a standard deviation
    n_augment: int = 200           # perturbed copies per Reference point
    # Per-Anchor sd of a perturbed copy. A Reference point's stored RSSI
    # carries its own shadowing and a window elsewhere carries another, so
    # the two differ by ~sqrt(2) x a ~3 dB shadowing sd.
    rssi_noise_db: float = 4.2
    gain_offset_db: float = 6.0    # device offset drawn from +/- this
    anchor_drop_p: float = 0.1     # chance a perturbed copy loses one Anchor
    seed: int = 0


@dataclass
class Mixture:
    """K diagonal Gaussians over (x, y) in metres."""
    weights: np.ndarray   # (K,), sums to 1
    means: np.ndarray     # (K, 2)
    sds: np.ndarray       # (K, 2)

    def mean(self) -> np.ndarray:
        return self.weights @ self.means

    def mode_mean(self, room: Tuple[float, float]) -> Tuple[float, float]:
        """The Scout's estimate: the mean of the most probable kernel, not
        the mixture mean, which can fall between modes (Bishop 1994);
        clipped to the room."""
        x, y = self.means[int(np.argmax(self.weights))]
        return float(np.clip(x, 0, room[0])), float(np.clip(y, 0, room[1]))

    def log_pdf(self, xy: np.ndarray) -> np.ndarray:
        z = (xy[:, None, :] - self.means) / self.sds
        log_n = (-0.5 * z ** 2 - np.log(self.sds) - 0.5 * np.log(2 * np.pi)).sum(axis=2)
        with np.errstate(divide="ignore"):
            terms = np.log(self.weights) + log_n
        top = terms.max(axis=1, keepdims=True)
        return (top + np.log(np.exp(terms - top).sum(axis=1, keepdims=True)))[:, 0]

    def sample(self, n: int, rng: np.random.Generator) -> np.ndarray:
        kernel = rng.choice(len(self.weights), size=n, p=self.weights)
        return self.means[kernel] + self.sds[kernel] * rng.standard_normal((n, 2))


def bbox(mixture: Mixture, room: Tuple[float, float], coverage: float = 0.95,
         n_samples: int = 4000, seed: int = 0) -> Box:
    """Axis-aligned box around the densest `coverage` of mixture samples,
    clipped to the room (ADR-0002). One deliberate departure from a pure
    95 % box: it is widened to take in the mixture mean if the densest
    samples miss it (a light, far kernel can pull the mean outside them),
    so the Sniper's search region always holds it. A mean beyond a wall is
    held at its nearest in-room point, since the box is clipped last."""
    pts = mixture.sample(n_samples, np.random.default_rng(seed))
    dens = mixture.log_pdf(pts)
    keep = pts[dens >= np.quantile(dens, 1.0 - coverage)]
    keep = np.vstack([keep, mixture.mean()])
    (x0, y0), (x1, y1) = keep.min(axis=0), keep.max(axis=0)
    w, h = room
    return (float(np.clip(x0, 0, w)), float(np.clip(y0, 0, h)),
            float(np.clip(x1, 0, w)), float(np.clip(y1, 0, h)))


def scout_input(
    rssi: Dict[str, Optional[float]],
    anchor_ids: Sequence[str],
    floor_dbm: float = RSSI_FLOOR_DBM,
) -> np.ndarray:
    """[z-scored RSSI per Anchor, presence mask per Anchor]."""
    mask = np.array([rssi.get(a) is not None for a in anchor_ids], dtype=np.float64)
    return np.concatenate([zscored_rssi(rssi, anchor_ids, floor_dbm), mask])


def augmented_samples(
    radio_map: RadioMap, config: ScoutConfig
) -> Tuple[List[Dict[str, Optional[float]]], np.ndarray]:
    """Each Reference point's RSSI as stored, plus `n_augment` path-loss
    perturbed copies (see the module docstring)."""
    rng = np.random.default_rng(config.seed)
    rssi: List[Dict[str, Optional[float]]] = []
    xy = []
    for p in radio_map.points.values():
        base = {a: None if fp is None else fp.rssi for a, fp in p.anchors.items()}
        rssi.append(base)
        xy.append((p.x, p.y))
        for _ in range(config.n_augment):
            offset = rng.uniform(-config.gain_offset_db, config.gain_offset_db)
            copy = {
                a: None if r is None else r + offset + rng.normal(0, config.rssi_noise_db)
                for a, r in base.items()
            }
            present = [a for a, r in copy.items() if r is not None]
            if len(present) > 2 and rng.random() < config.anchor_drop_p:
                copy[present[rng.integers(len(present))]] = None
            rssi.append(copy)
            xy.append((p.x, p.y))
    return rssi, np.array(xy)


class _Mdn(nn.Module):
    def __init__(self, n_in: int, hidden: int, k: int):
        super().__init__()
        self.k = k
        self.body = nn.Sequential(
            nn.Linear(n_in, hidden), nn.Tanh(),
            nn.Linear(hidden, hidden), nn.Tanh(),
            nn.Linear(hidden, k * 5),
        )

    def forward(self, x):
        """(mixing logits, means, log sds) for K kernels."""
        out = self.body(x)
        k = self.k
        return out[:, :k], out[:, k:3 * k].reshape(-1, k, 2), out[:, 3 * k:].reshape(-1, k, 2)


class MdnScout:
    name = "scout"

    def __init__(self, anchor_ids: Sequence[str], room: Tuple[float, float],
                 config: Optional[ScoutConfig] = None,
                 floor_dbm: float = RSSI_FLOOR_DBM):
        self.anchor_ids = list(anchor_ids)
        self.room = (float(room[0]), float(room[1]))
        self.config = config or ScoutConfig()
        self.floor_dbm = floor_dbm
        self.radio_map_sha256: Optional[str] = None
        torch.manual_seed(self.config.seed)
        self.net = _Mdn(2 * len(self.anchor_ids), self.config.hidden, self.config.k)
        # Positions are learned as fractions of the room, so one learning
        # rate suits any room size.
        self._scale = np.array(self.room)

    @classmethod
    def from_radio_map(cls, radio_map: RadioMap, room: Tuple[float, float],
                       config: Optional[ScoutConfig] = None) -> Tuple["MdnScout", List[float]]:
        """A Scout trained on `radio_map`, and its loss per epoch."""
        scout = cls(radio_map.anchor_ids, room, config)
        losses = scout.fit(*augmented_samples(radio_map, scout.config))
        return scout, losses

    def _params(self, x: torch.Tensor):
        """(log mixing coefficients, means, sds) in room-scaled units."""
        logits, mu, log_sd = self.net(x)
        floor = torch.as_tensor(self.config.sigma_floor_m / self._scale, dtype=x.dtype)
        return torch.log_softmax(logits, dim=1), mu, torch.exp(log_sd) + floor

    def _nll(self, x: torch.Tensor, y: torch.Tensor) -> torch.Tensor:
        log_pi, mu, sd = self._params(x)
        z = (y[:, None, :] - mu) / sd
        log_n = (-0.5 * z ** 2 - torch.log(sd) - 0.5 * np.log(2 * np.pi)).sum(dim=2)
        return -torch.logsumexp(log_pi + log_n, dim=1).mean()

    def fit(self, rssi: Sequence[Dict[str, Optional[float]]], xy) -> List[float]:
        """Full-batch Adam on exactly these samples (no augmentation);
        returns the loss per epoch."""
        torch.manual_seed(self.config.seed)
        x = torch.as_tensor(np.stack([self._input(r) for r in rssi]), dtype=torch.float32)
        y = torch.as_tensor(np.asarray(xy) / self._scale, dtype=torch.float32)
        opt = torch.optim.Adam(self.net.parameters(), lr=self.config.lr)
        losses = []
        for _ in range(self.config.epochs):
            opt.zero_grad()
            loss = self._nll(x, y)
            loss.backward()
            opt.step()
            losses.append(loss.item())
        return losses

    def _input(self, rssi: Dict[str, Optional[float]]) -> np.ndarray:
        return scout_input(rssi, self.anchor_ids, self.floor_dbm)

    def predict(self, window: dict) -> Optional[Mixture]:
        """The mixture over (x, y) in metres for one preprocessed window."""
        if not window["sufficient"]:
            return None
        rssi = window_rssi(window["anchors"])
        x = torch.as_tensor(self._input(rssi)[None, :], dtype=torch.float32)
        with torch.no_grad():
            log_pi, mu, sd = self._params(x)
        weights = log_pi.exp()[0].double().numpy()
        return Mixture(
            weights=weights / weights.sum(),
            means=mu[0].double().numpy() * self._scale,
            sds=sd[0].double().numpy() * self._scale,
        )

    def estimate(self, window: dict) -> Optional[Tuple[float, float]]:
        mixture = self.predict(window)
        return None if mixture is None else mixture.mode_mean(self.room)

    def locate(self, window: dict) -> Optional[dict]:
        """Estimate plus 95 % bounding box, for the harness's bbox metrics."""
        mixture = self.predict(window)
        if mixture is None:
            return None
        x, y = mixture.mode_mean(self.room)
        return {"x": x, "y": y, "bbox": bbox(mixture, self.room)}

    def save(self, path: Union[str, Path], radio_map_path: Union[str, Path]) -> None:
        """Weights and training config, tied to the Radio map file (by name
        and SHA-256) that the Scout was trained on."""
        radio_map_path = Path(radio_map_path)
        torch.save({
            "state_dict": self.net.state_dict(),
            "config": asdict(self.config),
            "anchor_ids": self.anchor_ids,
            "room": list(self.room),
            "floor_dbm": self.floor_dbm,
            "radio_map": radio_map_path.name,
            "radio_map_sha256": hashlib.sha256(radio_map_path.read_bytes()).hexdigest(),
        }, path)

    @classmethod
    def load(cls, path: Union[str, Path]) -> "MdnScout":
        doc = torch.load(path, weights_only=True)
        scout = cls(doc["anchor_ids"], tuple(doc["room"]),
                    ScoutConfig(**doc["config"]), doc["floor_dbm"])
        scout.net.load_state_dict(doc["state_dict"])
        scout.radio_map_sha256 = doc["radio_map_sha256"]
        return scout


def run_scout(sim_dir: Path, layout: Layout, out_dir: Path,
              config: Optional[ScoutConfig] = None, knn_k: int = 3) -> dict:
    """The k-NN baseline (which also builds the Radio map), then the Scout
    trained on that Radio map and scored on the same test windows. Writes
    <out_dir>/scout.pt (weights + config) and <out_dir>/scout.json."""
    sim_dir, out_dir = Path(sim_dir), Path(out_dir)
    baseline = run_baseline(sim_dir, layout, out_dir, k=knn_k)
    radio_map_path = out_dir / "radio_map.json"
    radio_map = RadioMap.load(radio_map_path)

    t0 = time.perf_counter()
    scout, losses = MdnScout.from_radio_map(
        radio_map, (layout.width_m, layout.height_m), config)
    train_s = time.perf_counter() - t0
    scout.save(out_dir / "scout.pt", radio_map_path)

    _, test_windows = read_jsonl(out_dir / "test_windows.jsonl")
    test_truth = json.loads((sim_dir / "test" / "ground_truth.json").read_text())
    result = evaluate(scout, test_windows, test_truth, layout)
    result["meta"] = {
        "localizer": scout.name,
        "config": asdict(scout.config),
        "train_seconds": train_s,
        "final_loss": losses[-1],
        "radio_map": radio_map_path.name,
        "reference_points": len(radio_map.points),
        "layout": str(layout.path) if layout.path else None,
        "sim": str(sim_dir),
    }
    out = {"baseline": baseline, "scout": result}
    with open(out_dir / "scout.json", "w") as fh:
        json.dump(out, fh, indent=2)
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        prog="gateway.scout", description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--sim", type=Path, default=Path("sim_data"),
                    help="directory holding calibration/ and test/ sessions")
    ap.add_argument("--layout", type=Path, default=Path("layouts/techhub_default.yaml"))
    ap.add_argument("--out", type=Path, default=Path("out/eval"))
    ap.add_argument("--epochs", type=int, default=ScoutConfig.epochs)
    ap.add_argument("--seed", type=int, default=ScoutConfig.seed)
    args = ap.parse_args(argv)

    config = ScoutConfig(epochs=args.epochs, seed=args.seed)
    result = run_scout(args.sim, load_layout(args.layout), args.out, config)
    meta = result["scout"]["meta"]
    print(f"Scout (MDN, K={config.k}), {meta['reference_points']} Reference points, "
          f"trained in {meta['train_seconds']:.1f} s")
    print(format_table(result["scout"]))
    print()
    print(format_comparison({"k-NN": result["baseline"], "Scout": result["scout"]}))
    print(f"\nwrote {args.out / 'scout.json'} and {args.out / 'scout.pt'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
