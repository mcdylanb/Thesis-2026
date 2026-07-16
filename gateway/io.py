"""Serialization of window features (JSONL default, parquet optional) and
the session summary report."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional, Union

import numpy as np

from gateway.records import ParseStats, StatRecord, WindowFeature


def _anchor_dict(feat, include_csi52: bool) -> Optional[dict]:
    if feat is None:
        return None
    d = {
        "n_pkts": feat.n_pkts,
        "rssi": round(feat.rssi, 2),
        "rssi_raw": feat.rssi_raw,
        "csi_n": feat.csi_n,
        "dcfr": None if feat.dcfr is None else [round(float(v), 6) for v in feat.dcfr],
    }
    if include_csi52:
        d["csi52"] = (
            None if feat.csi52 is None else [round(float(v), 6) for v in feat.csi52]
        )
    return d


def feature_to_dict(wf: WindowFeature, include_csi52: bool = False) -> dict:
    return {
        "window_id": wf.window_id,
        "t_start": wf.t_start,
        "t_end": wf.t_end,
        "t_start_iso": datetime.fromtimestamp(wf.t_start, timezone.utc).isoformat(),
        "mac": wf.mac,
        "label": wf.label,
        "tag": wf.tag,
        "sufficient": wf.sufficient,
        "anchors": {a: _anchor_dict(f, include_csi52) for a, f in wf.anchors.items()},
    }


def write_jsonl(
    path: Union[str, Path],
    features: List[WindowFeature],
    meta: dict,
    include_csi52: bool = False,
) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as fh:
        fh.write(json.dumps({"_meta": meta}) + "\n")
        for wf in features:
            fh.write(json.dumps(feature_to_dict(wf, include_csi52)) + "\n")


def write_parquet(
    path: Union[str, Path],
    features: List[WindowFeature],
    meta: dict,
    include_csi52: bool = False,
) -> None:
    try:
        import pandas as pd
    except ImportError as exc:  # pragma: no cover
        raise SystemExit(
            "parquet output requires pandas+pyarrow: pip install 'gateway[parquet]'"
        ) from exc
    rows = [feature_to_dict(wf, include_csi52) for wf in features]
    df = pd.json_normalize(rows)
    df.attrs["meta"] = meta
    df.to_parquet(path)


def summarize(
    features: List[WindowFeature],
    stats: ParseStats,
    stat_records: List[StatRecord],
) -> dict:
    total = len(features)
    sufficient = sum(1 for f in features if f.sufficient)

    per_mac: dict = {}
    for f in features:
        m = per_mac.setdefault(
            f.mac, {"label": f.label, "tag": f.tag, "windows": 0, "sufficient": 0}
        )
        m["windows"] += 1
        m["sufficient"] += int(f.sufficient)

    # Firmware-side drop counts: last STAT per anchor is cumulative.
    fw_dropped = {}
    for s in stat_records:
        fw_dropped[s.anchor] = s.dropped

    t_span = None
    if features:
        t_span = [
            min(f.t_start for f in features),
            max(f.t_end for f in features),
        ]

    return {
        "parse": {
            "total_rows": stats.total_rows,
            "csi_records": stats.csi,
            "stat_records": stats.stat,
            "malformed": stats.malformed,
            "ignored_prefix": stats.ignored_prefix,
            "csi_per_anchor": stats.per_anchor,
            "malformed_examples": stats.malformed_examples,
        },
        "firmware_dropped_per_anchor": fw_dropped,
        "windows": {
            "total": total,
            "sufficient": sufficient,
            "usable_window_rate": round(sufficient / total, 4) if total else None,
        },
        "per_device": per_mac,
        "session_span_epoch": t_span,
    }


def print_summary(summary: dict) -> None:
    print(json.dumps(summary, indent=2, default=_json_default))


def _json_default(obj):
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        return float(obj)
    raise TypeError(f"not JSON serializable: {type(obj)}")
