"""RSSI smoothing filters.

Default is EWMA: O(1)-state, behaves identically on irregular packet
arrivals, and carries over unchanged to a future live/streaming mode —
unlike fixed-k moving-average/median filters that need buffering. Raw
values are preserved in the output so smoothing can be redone offline.
"""

from __future__ import annotations

import numpy as np

METHODS = ("ewma", "median", "mean")


def ewma(values: np.ndarray, alpha: float = 0.3) -> np.ndarray:
    values = np.asarray(values, dtype=np.float64)
    out = np.empty_like(values)
    acc = values[0]
    for i, v in enumerate(values):
        acc = alpha * v + (1.0 - alpha) * acc
        out[i] = acc
    return out


def median_filter(values: np.ndarray, k: int = 5) -> np.ndarray:
    values = np.asarray(values, dtype=np.float64)
    half = k // 2
    out = np.empty_like(values)
    for i in range(len(values)):
        lo = max(0, i - half)
        hi = min(len(values), i + half + 1)
        out[i] = np.median(values[lo:hi])
    return out


def moving_average(values: np.ndarray, k: int = 5) -> np.ndarray:
    values = np.asarray(values, dtype=np.float64)
    half = k // 2
    out = np.empty_like(values)
    for i in range(len(values)):
        lo = max(0, i - half)
        hi = min(len(values), i + half + 1)
        out[i] = values[lo:hi].mean()
    return out


def smooth_series(values, method: str = "ewma", **params) -> np.ndarray:
    """Dispatch to the configured smoothing filter."""
    values = np.asarray(values, dtype=np.float64)
    if len(values) == 0:
        return values
    if method == "ewma":
        return ewma(values, **params)
    if method == "median":
        return median_filter(values, **params)
    if method == "mean":
        return moving_average(values, **params)
    raise ValueError(f"unknown smoothing method {method!r}")
