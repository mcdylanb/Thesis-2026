"""Gateway preprocessing pipeline for the hybrid RSSI-CSI localization thesis.

Turns raw anchor capture CSVs (from firmware/tools/gateway_logger.py) into
synchronized per-window feature records: smoothed RSSI and D-CFR vectors per
(window, device, anchor), ready for the baseline and proposed localization
modules.
"""

__version__ = "0.1.0"

from gateway.records import (  # noqa: F401
    AnchorFeature,
    CsiRecord,
    ParseStats,
    StatRecord,
    WindowFeature,
)
