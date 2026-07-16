"""Typed records passed between pipeline stages. No processing logic here."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

import numpy as np


@dataclass(frozen=True)
class CsiRecord:
    """One sniffed packet: the thesis tuple (id, t, RSSI, CSI, anchor).

    Canonical time is ``t_host`` (logger wall clock; all anchors are logged
    on one laptop so it is a common clock). ``timestamp_us`` is the anchor's
    local MAC clock — unsynchronized across anchors and wraps every ~71.6
    minutes — so it must never be used for cross-anchor alignment.
    """

    anchor: str
    seq: int
    mac: str
    rssi: int
    sig_mode: int
    channel: int
    timestamp_us: int
    t_host: float
    host_ns: int
    amps_hw: np.ndarray  # shape (64,) float32, hardware buffer order


@dataclass(frozen=True)
class StatRecord:
    """Firmware health line; feeds the packet-sufficiency reporting."""

    anchor: str
    uptime_ms: int
    pkts_seen: int
    csi_cb_count: int
    queued: int
    dropped: int
    free_heap: int
    t_host: float


@dataclass
class ParseStats:
    total_rows: int = 0
    csi: int = 0
    stat: int = 0
    malformed: int = 0
    ignored_prefix: int = 0
    per_anchor: Dict[str, int] = field(default_factory=dict)
    malformed_examples: List[str] = field(default_factory=list)

    MAX_EXAMPLES = 5

    def note_malformed(self, line: str) -> None:
        self.malformed += 1
        if len(self.malformed_examples) < self.MAX_EXAMPLES:
            self.malformed_examples.append(line[:120])


@dataclass
class AnchorFeature:
    """Per-anchor features within one (window, mac) group."""

    n_pkts: int
    rssi_raw: List[int]
    rssi: float                      # smoothed window value
    csi_n: int                       # packets whose CSI survived validation
    csi52: Optional[np.ndarray]      # normalized median spectrum, shape (52,)
    dcfr: Optional[np.ndarray]       # shape (51,)


@dataclass
class WindowFeature:
    """One output record: everything downstream localization needs for one
    device in one synchronized capture window."""

    window_id: int
    t_start: float
    t_end: float
    mac: str
    label: str
    tag: str                         # "wanted" | "unwanted"
    sufficient: bool
    anchors: Dict[str, Optional[AnchorFeature]]  # all anchor keys present
