"""Parsers for firmware CSV lines and Capture files.

Two Capture formats are read, detected from the header row:

- logger: ``host_iso,host_ns,line`` (gateway_logger.py, relay_udp_listener.py);
- legacy: ``host_iso,host_ns,type,anchor_id,seq,mac,rssi,channel,len,csi_payload``
  (``scripts/uart_listener_2.py``, as run on the Pi-era Gateway). It has no
  sig_mode or timestamp_us, so both read as 0, and MACs are uppercase.

``parse_firmware_line`` is a pure function on a single line so the same
code path serves logged files today and a live serial/UDP reader later
(the live reader would stamp ``t_host = time.time()`` itself).

Policy for malformed input: count and skip, never raise — capture sessions
must survive boot-ROM noise, truncated last lines, and glitched bytes.
"""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterator, List, Optional, Sequence, Tuple, Union

import numpy as np

from gateway.records import CsiRecord, ParseStats, StatRecord

MAC_RE = re.compile(r"^[0-9a-f]{2}(:[0-9a-f]{2}){5}$")

CSI_HEADER_FIELDS = 9   # CSI,anchor,seq,mac,rssi,sig_mode,channel,timestamp_us,n_sub
STAT_FIELDS = 8         # STAT,anchor,uptime_ms,pkts_seen,csi_cb_count,queued,dropped,free_heap
LEGACY_HEADER = ["host_iso", "host_ns", "type", "anchor_id", "seq", "mac",
                 "rssi", "channel", "len", "csi_payload"]


@dataclass(frozen=True)
class CsiPayload:
    """A parsed CSI line minus host-time fields."""

    anchor: str
    seq: int
    mac: str
    rssi: int
    sig_mode: int
    channel: int
    timestamp_us: int
    amps_hw: np.ndarray


@dataclass(frozen=True)
class StatPayload:
    anchor: str
    uptime_ms: int
    pkts_seen: int
    csi_cb_count: int
    queued: int
    dropped: int
    free_heap: int


def amplitudes_from_raw_iq(vals: Sequence[int]) -> np.ndarray:
    """128 int8 values alternating [imag, real] -> 64 amplitudes."""
    iq = np.asarray(vals, dtype=np.float32).reshape(-1, 2)
    return np.hypot(iq[:, 0], iq[:, 1]).astype(np.float32)


def parse_firmware_line(line: str) -> Optional[Union[CsiPayload, StatPayload]]:
    """Parse one raw firmware line. Returns None if it is not a well-formed
    CSI or STAT line (unknown prefixes are also None; the caller decides
    whether that counts as malformed or merely ignorable)."""
    fields = line.strip().split(",")

    try:
        if fields[0] == "CSI":
            if len(fields) < CSI_HEADER_FIELDS:
                return None
            n_sub = int(fields[8])
            values = fields[CSI_HEADER_FIELDS:]
            if n_sub not in (64, 128) or len(values) != n_sub:
                return None
            mac = fields[3].lower()
            if not MAC_RE.match(mac):
                return None
            if n_sub == 128:
                amps = amplitudes_from_raw_iq([int(v) for v in values])
            else:
                amps = np.asarray([float(v) for v in values], dtype=np.float32)
            return CsiPayload(
                anchor=fields[1],
                seq=int(fields[2]),
                mac=mac,
                rssi=int(fields[4]),
                sig_mode=int(fields[5]),
                channel=int(fields[6]),
                timestamp_us=int(fields[7]),
                amps_hw=amps,
            )

        if fields[0] == "STAT":
            if len(fields) != STAT_FIELDS:
                return None
            return StatPayload(
                anchor=fields[1],
                uptime_ms=int(fields[2]),
                pkts_seen=int(fields[3]),
                csi_cb_count=int(fields[4]),
                queued=int(fields[5]),
                dropped=int(fields[6]),
                free_heap=int(fields[7]),
            )
    except (ValueError, IndexError):
        return None

    return None


def _parse_host_iso(value: str) -> float:
    return datetime.fromisoformat(value).timestamp()


def _legacy_row_to_line(row: List[str]) -> Optional[str]:
    """A legacy Capture row's firmware line, or None if the row is malformed.
    CSI rows gain sig_mode=0 and timestamp_us=0 so ``parse_firmware_line``
    validates both formats alike; the Pi-era listener wrote any other line
    verbatim after the two host columns."""
    if len(row) < 3:
        return None
    if row[2] != "CSI":
        return ",".join(row[2:])
    if len(row) != len(LEGACY_HEADER):
        return None
    _, _, _, anchor, seq, mac, rssi, channel, n_sub, payload = row
    return f"CSI,{anchor},{seq},{mac},{rssi},0,{channel},0,{n_sub},{payload}"


def iter_logged_records(
    path: Union[str, Path], stats: ParseStats
) -> Iterator[Union[CsiRecord, StatRecord]]:
    """Read one Capture file in either format (see module docstring)."""
    legacy = False
    with open(path, newline="") as fh:
        reader = csv.reader(fh)
        for row in reader:
            if not row:
                continue
            if row[0] == "host_iso":  # header
                legacy = row == LEGACY_HEADER
                continue
            stats.total_rows += 1
            if legacy:
                line = _legacy_row_to_line(row)
            else:
                line = row[2] if len(row) == 3 else None
            if line is None:
                stats.note_malformed(",".join(row))
                continue
            host_iso, host_ns_s = row[0], row[1]

            payload = parse_firmware_line(line)
            if payload is None:
                stripped = line.strip()
                if stripped.startswith(("CSI,", "STAT,")):
                    stats.note_malformed(line)
                else:
                    stats.ignored_prefix += 1
                continue

            try:
                t_host = _parse_host_iso(host_iso)
                host_ns = int(host_ns_s)
            except ValueError:
                stats.note_malformed(",".join(row))
                continue

            if isinstance(payload, CsiPayload):
                stats.csi += 1
                stats.per_anchor[payload.anchor] = (
                    stats.per_anchor.get(payload.anchor, 0) + 1
                )
                yield CsiRecord(
                    anchor=payload.anchor,
                    seq=payload.seq,
                    mac=payload.mac,
                    rssi=payload.rssi,
                    sig_mode=payload.sig_mode,
                    channel=payload.channel,
                    timestamp_us=payload.timestamp_us,
                    t_host=t_host,
                    host_ns=host_ns,
                    amps_hw=payload.amps_hw,
                )
            else:
                stats.stat += 1
                yield StatRecord(
                    anchor=payload.anchor,
                    uptime_ms=payload.uptime_ms,
                    pkts_seen=payload.pkts_seen,
                    csi_cb_count=payload.csi_cb_count,
                    queued=payload.queued,
                    dropped=payload.dropped,
                    free_heap=payload.free_heap,
                    t_host=t_host,
                )


def expand_inputs(paths: Sequence[Union[str, Path]]) -> List[Path]:
    """Expand directories to their sorted *.csv contents."""
    out: List[Path] = []
    for p in paths:
        p = Path(p)
        if p.is_dir():
            out.extend(sorted(p.glob("*.csv")))
        else:
            out.append(p)
    return out


def load_session(
    paths: Sequence[Union[str, Path]]
) -> Tuple[List[CsiRecord], List[StatRecord], ParseStats]:
    """Load and merge capture files; CSI records sorted by host time."""
    stats = ParseStats()
    csi: List[CsiRecord] = []
    stat: List[StatRecord] = []
    for path in expand_inputs(paths):
        for rec in iter_logged_records(path, stats):
            if isinstance(rec, CsiRecord):
                csi.append(rec)
            else:
                stat.append(rec)
    csi.sort(key=lambda r: r.t_host)
    return csi, stat, stats
