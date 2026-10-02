"""Joining preprocessed windows to the Trials of a positions file.

A positions file is `ground_truth.json` from `gateway.sim` (or the #30
runbook's equivalent): a `trials` list, each with a host-time span
[t_start, t_end) and its `devices`, one of which is placed for the Trial
(the Beacon or target) while the rest are ambient.
"""

from __future__ import annotations

from typing import Dict, List, Optional


def trial_of(window: dict, trials: List[dict]) -> Optional[dict]:
    """The Trial whose [t_start, t_end) host-time span the window overlaps."""
    for trial in trials:
        if window["t_start"] < trial["t_end"] and window["t_end"] > trial["t_start"]:
            return trial
    return None


def placed_device(trial: dict) -> dict:
    """The device a Trial is about: the Beacon or target, not the ambients."""
    return next(d for d in trial["devices"] if d["role"] != "ambient")


def windows_by_trial(windows: List[dict], truth: dict) -> Dict[str, List[dict]]:
    """Each Trial's windows of its placed device, keyed by Trial id (every
    Trial present, possibly with an empty list)."""
    out: Dict[str, List[dict]] = {t["id"]: [] for t in truth["trials"]}
    for w in windows:
        trial = trial_of(w, truth["trials"])
        if trial is not None and w["mac"] == placed_device(trial)["mac"]:
            out[trial["id"]].append(w)
    return out
