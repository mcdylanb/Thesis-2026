"""Cross-anchor synchronization: fixed-length capture windows on host time.

Anchor clocks are unsynchronized (and their timestamp_us wraps), so windows
are keyed exclusively on the logger's host timestamps — all four anchors
are logged by one laptop, giving a common clock.
"""

from __future__ import annotations

import math
from typing import Dict, List, Optional, Tuple

from gateway.records import CsiRecord

# (window_id, mac) -> anchor -> records
WindowGroups = Dict[Tuple[int, str], Dict[str, List[CsiRecord]]]


def assign_windows(
    records: List[CsiRecord],
    window_s: float,
    t0: Optional[float] = None,
) -> Tuple[float, WindowGroups]:
    """Group records into half-open windows [t0 + k*W, t0 + (k+1)*W).

    t0 defaults to the earliest host timestamp in the session, making window
    ids deterministic for a given input set. A record exactly on a boundary
    belongs to the later window (floor semantics).
    """
    if not records:
        return (t0 if t0 is not None else 0.0), {}
    if t0 is None:
        t0 = min(r.t_host for r in records)

    groups: WindowGroups = {}
    for rec in records:
        window_id = math.floor((rec.t_host - t0) / window_s)
        key = (window_id, rec.mac)
        groups.setdefault(key, {}).setdefault(rec.anchor, []).append(rec)

    for per_anchor in groups.values():
        for recs in per_anchor.values():
            recs.sort(key=lambda r: r.t_host)
    return t0, groups


def is_sufficient(
    per_anchor: Dict[str, List[CsiRecord]],
    min_anchors: int = 3,
    min_pkts: int = 1,
) -> bool:
    """The algorithms' 'valid anchor observations < minimum required' check:
    a (window, mac) group is usable when at least min_anchors anchors
    contributed at least min_pkts packets each."""
    qualifying = sum(1 for recs in per_anchor.values() if len(recs) >= min_pkts)
    return qualifying >= min_anchors
