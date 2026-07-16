"""Authorized-device list: wanted/unwanted tagging (functional req. 6).

Unlisted MACs get the registry's default role (default "unwanted") — a
hidden device is by definition not on the authorized list.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Optional, Tuple, Union

import yaml

ROLES = ("wanted", "unwanted")


@dataclass(frozen=True)
class DeviceEntry:
    mac: str
    label: str
    role: str
    attrs: dict = field(default_factory=dict)


class DeviceRegistry:
    def __init__(self, entries: Dict[str, DeviceEntry], default_role: str = "unwanted",
                 trial: Optional[str] = None):
        if default_role not in ROLES:
            raise ValueError(f"default_role must be one of {ROLES}")
        self._entries = entries
        self.default_role = default_role
        self.trial = trial

    @classmethod
    def empty(cls) -> "DeviceRegistry":
        return cls({}, "unwanted")

    @classmethod
    def from_file(cls, path: Union[str, Path]) -> "DeviceRegistry":
        path = Path(path)
        with open(path) as fh:
            if path.suffix == ".json":
                data = json.load(fh)
            else:
                data = yaml.safe_load(fh)

        entries: Dict[str, DeviceEntry] = {}
        for item in data.get("devices", []):
            mac = str(item["mac"]).lower()
            role = item.get("role", "unwanted")
            if role not in ROLES:
                raise ValueError(f"device {mac}: role must be one of {ROLES}")
            entries[mac] = DeviceEntry(
                mac=mac,
                label=item.get("label", mac),
                role=role,
                attrs=item.get("attrs", {}),
            )
        return cls(entries,
                   default_role=data.get("default_role", "unwanted"),
                   trial=data.get("trial"))

    def tag(self, mac: str) -> Tuple[str, str]:
        """Return (role, label) for a MAC; unknown MACs get the default role
        and their own MAC as label."""
        entry = self._entries.get(mac.lower())
        if entry is None:
            return self.default_role, mac.lower()
        return entry.role, entry.label

    def is_listed(self, mac: str) -> bool:
        return mac.lower() in self._entries
