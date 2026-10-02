"""Radio map: per-(Reference point, Anchor) fingerprints from a Calibration
session (ADR-0002).

Built from the preprocessed windows of a Calibration session (run with
--include-csi52 so the raw normalized amplitude is kept for the #29
ablation) joined to its positions file — `ground_truth.json` from
`gateway.sim`, or the #30 runbook's equivalent with the same `trials`
shape. A window belongs to the Trial whose host-time span it overlaps, and
only the Trial's non-ambient device (the Beacon) contributes.

Per Reference point and Anchor the map stores the mean smoothed RSSI, the
element-wise median D-CFR and the median raw amplitude over the point's
sufficient windows. It is saved as JSON together with the preprocess
`_meta` it was built from, so a consumer can check that the windows it
localizes were preprocessed the same way.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Union

import numpy as np

from gateway.trials import placed_device, windows_by_trial


@dataclass
class AnchorFingerprint:
    rssi: float
    dcfr: np.ndarray
    amp: np.ndarray


@dataclass
class ReferencePoint:
    x: float
    y: float
    n_windows: int
    anchors: Dict[str, Optional[AnchorFingerprint]]


@dataclass
class RadioMap:
    anchor_ids: List[str]
    points: Dict[str, ReferencePoint] = field(default_factory=dict)
    meta: dict = field(default_factory=dict)

    def save(self, path: Union[str, Path]) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        doc = {
            "meta": self.meta,
            "anchor_ids": self.anchor_ids,
            "points": {
                rp: {
                    "x": p.x,
                    "y": p.y,
                    "n_windows": p.n_windows,
                    "anchors": {
                        a: None if fp is None else {
                            "rssi": fp.rssi,
                            "dcfr": fp.dcfr.tolist(),
                            "amp": fp.amp.tolist(),
                        }
                        for a, fp in p.anchors.items()
                    },
                }
                for rp, p in self.points.items()
            },
        }
        with open(path, "w") as fh:
            json.dump(doc, fh)

    @classmethod
    def load(cls, path: Union[str, Path]) -> "RadioMap":
        with open(path) as fh:
            doc = json.load(fh)
        points = {
            rp: ReferencePoint(
                x=p["x"],
                y=p["y"],
                n_windows=p["n_windows"],
                anchors={
                    a: None if fp is None else AnchorFingerprint(
                        rssi=fp["rssi"],
                        dcfr=np.array(fp["dcfr"]),
                        amp=np.array(fp["amp"]),
                    )
                    for a, fp in p["anchors"].items()
                },
            )
            for rp, p in doc["points"].items()
        }
        return cls(anchor_ids=doc["anchor_ids"], points=points, meta=doc["meta"])


def build_radio_map(windows: List[dict], meta: dict, truth: dict) -> RadioMap:
    """Aggregate a Calibration session's sufficient Beacon windows into one
    fingerprint per (Reference point, Anchor)."""
    anchor_ids = list(meta.get("anchor_ids") or truth["anchors"])
    by_trial = {
        tid: [w for w in ws if w["sufficient"]]
        for tid, ws in windows_by_trial(windows, truth).items()
    }
    if any("csi52" not in obs for ws in by_trial.values() for w in ws
           for obs in w["anchors"].values() if obs is not None):
        raise ValueError(
            "windows lack raw amplitude: preprocess with --include-csi52"
        )

    rmap = RadioMap(anchor_ids=anchor_ids, meta=meta)
    for trial in truth["trials"]:
        trial_windows = by_trial.get(trial["id"])
        if not trial_windows:
            continue
        device = placed_device(trial)
        anchors: Dict[str, Optional[AnchorFingerprint]] = {}
        for a in anchor_ids:
            obs = [w["anchors"][a] for w in trial_windows if w["anchors"].get(a)]
            with_csi = [o for o in obs if o["dcfr"] is not None and o["csi52"] is not None]
            if not obs or not with_csi:
                anchors[a] = None
                continue
            anchors[a] = AnchorFingerprint(
                rssi=float(np.mean([o["rssi"] for o in obs])),
                dcfr=np.median([o["dcfr"] for o in with_csi], axis=0),
                amp=np.median([o["csi52"] for o in with_csi], axis=0),
            )
        rmap.points[trial["id"]] = ReferencePoint(
            x=device["x"], y=device["y"], n_windows=len(trial_windows), anchors=anchors,
        )
    return rmap
