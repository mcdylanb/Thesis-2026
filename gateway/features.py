"""Assemble WindowFeature records from windowed groups. Pure glue, no I/O."""

from __future__ import annotations

from typing import Dict, List, Optional, Sequence

from gateway.csi import aggregate, dcfr, dcfr_stability, valid_spectra
from gateway.devices import DeviceRegistry
from gateway.records import AnchorFeature, CsiRecord, WindowFeature
from gateway.rssi import smooth_series
from gateway.windowing import WindowGroups, is_sufficient

# Sniper RSSI floor (ADR-0002 fallback rule): an Anchor counts only when its
# smoothed window RSSI is strictly above this.
DEFAULT_RSSI_FLOOR_DBM = -80.0


def build_anchor_feature(
    records: List[CsiRecord],
    rssi_method: str = "ewma",
    rssi_params: Optional[dict] = None,
    csi_norm: str = "l2",
    hw_indices=None,
    rssi_floor: float = DEFAULT_RSSI_FLOOR_DBM,
) -> AnchorFeature:
    rssi_raw = [r.rssi for r in records]
    smoothed = smooth_series(rssi_raw, rssi_method, **(rssi_params or {}))
    rssi_value = float(smoothed.mean())

    spectra = valid_spectra([r.amps_hw for r in records], csi_norm, hw_indices)
    csi52 = aggregate(spectra, "median") if spectra else None
    return AnchorFeature(
        n_pkts=len(records),
        rssi_raw=rssi_raw,
        rssi=rssi_value,
        csi_n=len(spectra),
        csi52=csi52,
        dcfr=dcfr(csi52) if csi52 is not None else None,
        stability=dcfr_stability([dcfr(h) for h in spectra]),
        above_floor=rssi_value > rssi_floor,
    )


def build_window_features(
    groups: WindowGroups,
    t0: float,
    window_s: float,
    anchor_ids: Sequence[str],
    registry: DeviceRegistry,
    min_anchors: int = 3,
    min_pkts: int = 1,
    rssi_method: str = "ewma",
    rssi_params: Optional[dict] = None,
    csi_norm: str = "l2",
    hw_indices=None,
    rssi_floor: float = DEFAULT_RSSI_FLOOR_DBM,
) -> List[WindowFeature]:
    features: List[WindowFeature] = []
    for (window_id, mac), per_anchor in sorted(groups.items()):
        role, label = registry.tag(mac)
        anchors: Dict[str, Optional[AnchorFeature]] = {a: None for a in anchor_ids}
        for anchor, recs in per_anchor.items():
            anchors[anchor] = build_anchor_feature(
                recs, rssi_method, rssi_params, csi_norm, hw_indices, rssi_floor
            )
        features.append(
            WindowFeature(
                window_id=window_id,
                t_start=t0 + window_id * window_s,
                t_end=t0 + (window_id + 1) * window_s,
                mac=mac,
                label=label,
                tag=role,
                sufficient=is_sufficient(per_anchor, min_anchors, min_pkts),
                anchors=anchors,
            )
        )
    return features
