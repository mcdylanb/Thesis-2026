"""The k-NN baseline localizer (ADR-0002).

k = 3, inverse-distance weighted (the RADAR setting), over the
concatenated per-Anchor [z-scored RSSI, D-CFR] vector:

- RSSI is z-scored *within the window across the Anchors*, which cancels a
  per-device gain offset (a dB-difference fingerprint).
- Each Anchor's D-CFR is mean-centred, so a spectral tilt — which D-CFR
  turns into a constant — does not move the Euclidean distance.
- The RSSI block (4 dims) and the D-CFR block (4 x N_DCFR dims) are each
  scaled by 1/sqrt(dim), so both carry equal total weight.
- A missing Anchor is imputed at the RSSI floor with zero D-CFR, rather
  than dropping the window. The z-score's mean and sd come from the Anchors
  present only (ADR-0002); the imputed value is then placed on that scale.
  It is the floor or the weakest present reading, whichever is lower, so a
  missing Anchor never looks stronger than one that was heard.

`KnnLocalizer.estimate(window)` takes one preprocessed window dict (a line
of the windows JSONL) and returns (x, y), or None when the window is not
sufficient. That signature is the harness's localizer interface.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

from gateway.radiomap import RadioMap

RSSI_FLOOR_DBM = -80.0  # ADR-0002 Sniper floor, reused as the imputation value


def zscored_rssi(
    rssi: Dict[str, Optional[float]],
    anchor_ids: Sequence[str],
    floor_dbm: float = RSSI_FLOOR_DBM,
) -> np.ndarray:
    """Per-Anchor RSSI z-scored over the Anchors present, a missing (None)
    Anchor imputed at min(floor, weakest present reading) on that scale."""
    present = {a: rssi[a] for a in anchor_ids if rssi.get(a) is not None}
    if not present:
        return np.zeros(len(anchor_ids))
    values = np.array(list(present.values()), dtype=np.float64)
    mean, sd = values.mean(), values.std()
    sd = sd if sd > 0 else 1.0
    imputed = min(floor_dbm, values.min())
    return np.array([(present.get(a, imputed) - mean) / sd for a in anchor_ids])


def feature_vector(
    anchors: Dict[str, Optional[dict]],
    anchor_ids: Sequence[str],
    n_dcfr: int,
    floor_dbm: float = RSSI_FLOOR_DBM,
) -> np.ndarray:
    """ADR-0002 baseline vector for one window's (or Reference point's)
    per-Anchor observations, each {"rssi": float, "dcfr": list | None} or None."""
    dcfr_blocks: List[np.ndarray] = []
    for a in anchor_ids:
        obs = anchors.get(a)
        d = None if obs is None else obs.get("dcfr")
        d = np.zeros(n_dcfr) if d is None else np.asarray(d, dtype=np.float64)
        dcfr_blocks.append(d - d.mean())

    z = zscored_rssi(
        {a: None if obs is None else obs["rssi"] for a, obs in anchors.items()},
        anchor_ids, floor_dbm,
    )
    dcfr = np.concatenate(dcfr_blocks)
    return np.concatenate([z / np.sqrt(len(z)), dcfr / np.sqrt(len(dcfr))])


class KnnLocalizer:
    name = "knn"

    def __init__(self, radio_map: RadioMap, k: int = 3,
                 floor_dbm: float = RSSI_FLOOR_DBM):
        if not radio_map.points:
            raise ValueError("radio map is empty")
        self.k = k
        self.floor_dbm = floor_dbm
        self.anchor_ids = list(radio_map.anchor_ids)
        lengths = {
            len(fp.dcfr)
            for p in radio_map.points.values()
            for fp in p.anchors.values()
            if fp is not None
        }
        if len(lengths) != 1:
            raise ValueError(f"radio map has D-CFR lengths {sorted(lengths)}; need exactly one")
        self.n_dcfr = lengths.pop()
        self.positions = np.array([(p.x, p.y) for p in radio_map.points.values()])
        self.vectors = np.stack([
            self._vector({
                a: None if fp is None else {"rssi": fp.rssi, "dcfr": fp.dcfr}
                for a, fp in p.anchors.items()
            })
            for p in radio_map.points.values()
        ])

    def _vector(self, anchors: Dict[str, Optional[dict]]) -> np.ndarray:
        return feature_vector(anchors, self.anchor_ids, self.n_dcfr, self.floor_dbm)

    def estimate(self, window: dict) -> Optional[Tuple[float, float]]:
        if not window["sufficient"]:
            return None
        return self.estimate_from_vector(self._vector(window["anchors"]))

    def estimate_from_vector(self, vec: np.ndarray) -> Tuple[float, float]:
        dist = np.linalg.norm(self.vectors - vec, axis=1)
        nearest = np.argsort(dist)[: self.k]
        if dist[nearest[0]] == 0:
            x, y = self.positions[nearest[0]]
            return float(x), float(y)
        w = 1.0 / dist[nearest]
        x, y = (self.positions[nearest] * w[:, None]).sum(axis=0) / w.sum()
        return float(x), float(y)
